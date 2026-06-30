#!/usr/bin/env python3
"""Self-contained smoke test for the paper detection-data pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def create_fixture(root: Path) -> tuple[Path, Path, Path]:
    stamps = [100.0 + float(i) for i in range(9)]
    loose_rows = []
    raw_rows = []
    tight_rows = []
    for i, stamp in enumerate(stamps):
        loose_rows.append(
            {
                "stamp": f"{stamp:.3f}",
                "status": 4,
                "status_name": "accepted",
                "aligned": 1,
                "maha": 0.4 + 0.05 * i,
                "gate_chi2": 16.27,
                "residual_x": 0.03,
                "residual_y": 0.02,
                "residual_z": 0.01,
                "residual_norm": 0.04,
                "correction_norm": 0.02,
                "raw_rtk_stat": 1,
                "raw_rtk_ns": 18,
                "raw_rtk_ratio": 4.0,
                "raw_rtk_dop_gdop": 1.2,
                "raw_rtk_dop_pdop": 1.0,
                "raw_rtk_dop_hdop": 0.5,
                "raw_rtk_dop_vdop": 0.8,
            }
        )
        raw_rows.append(
            {
                "stamp": f"{stamp:.3f}",
                "status": "accepted_with_doppler",
                "raw_pr_count": 14,
                "healthy_pr_count": 12,
                "pr_outlier_reject_count": 0,
                "pr_rms": 1.0,
                "pr_abs_mean": 0.8,
                "pr_abs_max": 2.0,
                "lambda_ratio": 4.0,
                "doppler_rms": 0.02,
                "doppler_used_count": 7,
                "tdcp_valid_count": 7,
            }
        )
        tight_rows.append(
            {
                "stamp": f"{stamp:.3f}",
                "lio_x": i * 0.1,
                "lio_y": i * 0.2,
                "lio_z": 1.0,
                "enu_x": i * 0.1 + 0.02,
                "enu_y": i * 0.2 - 0.01,
                "enu_z": 1.01,
                "clk_bias": 12.0,
                "sat_num": 12,
                "rms_res": 1.0,
            }
        )

    loose_path = root / "gnss_loose_diag.csv"
    raw_path = root / "gnss_raw_update_log.csv"
    tight_path = root / "gnss_tight_pose.csv"
    write_csv(loose_path, list(loose_rows[0].keys()), loose_rows)
    write_csv(raw_path, list(raw_rows[0].keys()), raw_rows)
    write_csv(tight_path, list(tight_rows[0].keys()), tight_rows)
    return loose_path, raw_path, tight_path


def run_command(args: list[str]) -> None:
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    root = PROJECT_ROOT / "build" / "paper_pipeline_smoke"
    source = root / "source"
    loose, raw, tight = create_fixture(source)

    attack_dir = root / "attack"
    run_command(
        [
            sys.executable,
            "tools/build_detection_dataset.py",
            "--loose",
            str(loose),
            "--raw",
            str(raw),
            "--tight",
            str(tight),
            "--name",
            "smoke_attack",
            "--output-dir",
            str(attack_dir),
            "--attack-window",
            "+3:+7",
            "--attack-offset",
            "8,0,0",
            "--pseudorange-delay",
            "18",
            "--threshold",
            "0.8",
            "--consecutive",
            "1",
        ]
    )
    attack_csv = attack_dir / "smoke_attack_detection.csv"
    attack_metrics = attack_dir / "smoke_attack_metrics.json"
    run_command(
        [
            sys.executable,
            "tools/evaluate_detection.py",
            str(attack_csv),
            "--output-json",
            str(attack_metrics),
            "--output-md",
            str(attack_dir / "smoke_attack_metrics.md"),
        ]
    )
    metrics = json.loads(attack_metrics.read_text(encoding="utf-8"))
    if metrics["true_positive"] <= 0 or metrics["recall"] <= 0.0:
        raise SystemExit(f"Expected synthetic attack detections, got {metrics}")

    clean_dir = root / "clean"
    run_command(
        [
            sys.executable,
            "tools/build_detection_dataset.py",
            "--loose",
            str(loose),
            "--raw",
            str(raw),
            "--tight",
            str(tight),
            "--name",
            "smoke_clean",
            "--output-dir",
            str(clean_dir),
            "--threshold",
            "0.8",
            "--consecutive",
            "1",
        ]
    )
    clean_csv = clean_dir / "smoke_clean_detection.csv"
    clean_metrics = clean_dir / "smoke_clean_metrics.json"
    run_command(
        [
            sys.executable,
            "tools/evaluate_detection.py",
            str(clean_csv),
            "--output-json",
            str(clean_metrics),
            "--output-md",
            str(clean_dir / "smoke_clean_metrics.md"),
        ]
    )
    clean = json.loads(clean_metrics.read_text(encoding="utf-8"))
    if clean["false_positive"] != 0:
        raise SystemExit(f"Expected no clean false positives, got {clean}")

    print("Paper pipeline smoke test passed")
    print(f"  attack csv: {attack_csv}")
    print(f"  clean csv: {clean_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
