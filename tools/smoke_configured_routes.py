#!/usr/bin/env python3
"""Smoke test for datasets/routes.yaml style configured route experiments."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from smoke_adaptive_detector import make_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_detection_csv(path: Path, row_offset: int = 0) -> None:
    rows = []
    for idx in range(42):
        row = make_row(idx + row_offset, degraded=(idx % 11 == 0))
        row["attack_label"] = "0"
        row["attack_scale"] = "0.0"
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = PROJECT_ROOT / "build" / "configured_routes_smoke"
    route_a = root / "route_a_detection.csv"
    route_b = root / "route_b_detection.csv"
    config_path = root / "routes.yaml"
    output_dir = root / "outputs"
    write_detection_csv(route_a)
    write_detection_csv(route_b, row_offset=100)
    config_path.write_text(
        "\n".join(
            [
                "routes:",
                "  - name: route_a",
                "    environment: smoke_train",
                f"    detection_csv: {route_a}",
                "  - name: route_b",
                "    environment: smoke_test",
                f"    detection_csv: {route_b}",
                "splits:",
                "  train:",
                "    - route_a",
                "  test:",
                "    - route_b",
                "experiment:",
                "  strengths_m:",
                "    - 2",
                "  ramps_s:",
                "    - 1",
                "  attack_types:",
                "    - position_bias",
                "  adaptive_gains:",
                "    - 1.35",
                "  cusum_thresholds:",
                "    - 0.5",
                "  ml_max_train_rows: 300",
                "  ml_trees: 6",
                "  ml_depth: 3",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            "tools/run_configured_routes.py",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    summary = json.loads((output_dir / "route_split_summary.json").read_text(encoding="utf-8"))
    if summary["train_routes"] != ["route_a"] or summary["test_routes"] != ["route_b"]:
        raise SystemExit(f"Unexpected configured split: {summary}")
    manifest = json.loads((output_dir / "configured_routes_manifest.json").read_text(encoding="utf-8"))
    if "routes" not in manifest["config_content"]:
        raise SystemExit(f"Missing routes in manifest: {manifest}")
    print("Configured routes smoke test passed")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
