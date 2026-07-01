#!/usr/bin/env python3
"""Smoke test for route-split tuning, test evaluation, and ML baseline output."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from smoke_adaptive_detector import make_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_route(path: Path, degraded_every: int = 0) -> None:
    rows = []
    for idx in range(54):
        degraded = degraded_every > 0 and idx % degraded_every == 0
        row = make_row(idx, attack=False, degraded=degraded)
        row["attack_label"] = "0"
        row["attack_scale"] = "0.0"
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = PROJECT_ROOT / "build" / "route_split_smoke"
    route_a = root / "route_a_detection.csv"
    route_b = root / "route_b_detection.csv"
    output_dir = root / "outputs"
    write_route(route_a)
    write_route(route_b, degraded_every=7)

    subprocess.run(
        [
            sys.executable,
            "tools/route_split_experiments.py",
            "--route",
            f"route_a={route_a}",
            "--route",
            f"route_b={route_b}",
            "--train-routes",
            "route_a",
            "--test-routes",
            "route_b",
            "--output-dir",
            str(output_dir),
            "--strengths-m",
            "2",
            "--ramps-s",
            "1",
            "--attack-types",
            "position_bias",
            "--adaptive-gains",
            "1.35",
            "--cusum-thresholds",
            "0.5",
            "--ml-max-train-rows",
            "300",
            "--ml-trees",
            "8",
            "--ml-depth",
            "3",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "route_split_summary.json").read_text(encoding="utf-8"))
    if summary["train_routes"] != ["route_a"] or summary["test_routes"] != ["route_b"]:
        raise SystemExit(f"Unexpected route split summary: {summary}")
    if not summary["ml_baseline"]["enabled"]:
        raise SystemExit("Expected ML baseline to be enabled in route split smoke test")
    with (output_dir / "detector_summary.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    detectors = {row["detector"] for row in rows}
    if "adaptive_seq_full" not in detectors or "ml_tree_ensemble" not in detectors:
        raise SystemExit(f"Missing expected detectors in route split summary: {detectors}")

    print("Route split smoke test passed")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
