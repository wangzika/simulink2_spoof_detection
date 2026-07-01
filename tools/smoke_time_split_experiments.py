#!/usr/bin/env python3
"""Smoke test for temporal held-out validation output."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from smoke_adaptive_detector import make_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_detection_csv(path: Path) -> None:
    rows = []
    for idx in range(80):
        degraded = 12 <= idx < 20 or 52 <= idx < 60
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
    root = PROJECT_ROOT / "build" / "time_split_smoke"
    input_csv = root / "single_route_detection.csv"
    output_dir = root / "outputs"
    write_detection_csv(input_csv)

    subprocess.run(
        [
            sys.executable,
            "tools/time_split_experiments.py",
            "--base-csv",
            str(input_csv),
            "--output-dir",
            str(output_dir),
            "--train-fraction",
            "0.55",
            "--min-segment-rows",
            "20",
            "--strengths-m",
            "5",
            "--ramps-s",
            "1",
            "--attack-types",
            "coordinated_spoof",
            "--adaptive-gains",
            "0.75,1.35",
            "--cusum-thresholds",
            "0.35,0.75",
            "--operating-fa-limit",
            "6.0",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "time_split_summary.json").read_text(encoding="utf-8"))
    if summary["validation_type"] != "temporal_holdout":
        raise SystemExit(f"Unexpected validation type: {summary}")
    if int(summary["split"]["train_rows"]) <= 0 or int(summary["split"]["test_rows"]) <= 0:
        raise SystemExit(f"Invalid temporal split sizes: {summary['split']}")
    with (output_dir / "detector_summary.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    detectors = {row["detector"] for row in rows}
    splits = {row["split"] for row in rows}
    if "adaptive_seq_full" not in detectors or splits != {"calibration", "heldout_test"}:
        raise SystemExit(f"Unexpected detector summary content: detectors={detectors}, splits={splits}")
    selected = [row for row in csv.DictReader((output_dir / "tuning_summary.csv").open(newline="")) if row["is_selected_config"] == "1"]
    if len(selected) != 1:
        raise SystemExit(f"Expected exactly one selected config, got {len(selected)}")

    print("Temporal split smoke test passed")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
