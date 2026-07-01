#!/usr/bin/env python3
"""Self-contained smoke test for the adaptive sequential GLRT detector."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

import adaptive_sequential_detector as detector


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_row(idx: int, attack: bool = False, degraded: bool = False) -> dict[str, str]:
    row = {
        "stamp": f"{1000.0 + idx:.3f}",
        "time_s": f"{idx:.3f}",
        "attack_label": "1" if attack else "0",
        "attack_scale": "1.0" if attack else "0.0",
        "loose_gate_chi2": "16.27",
        "loose_maha": "0.4",
        "effective_maha": "0.4",
        "loose_residual_norm_m": "0.2",
        "effective_residual_norm_m": "0.2",
        "effective_pr_rms_m": "1.0",
        "effective_pr_abs_max_m": "2.0",
        "raw_doppler_rms_mps": "0.02",
        "rtk_quality": "1",
        "rtk_ratio": "4.0",
        "rtk_satellites": "14",
        "raw_healthy_pr_count": "12",
        "dop_pdop": "1.3",
        "dop_hdop": "0.8",
        "rinex_satellite_count": "16",
        "rinex_mean_cn0_dbhz": "44.0",
        "rinex_min_cn0_dbhz": "36.0",
        "rinex_low_cn0_satellite_count": "0",
        "raw_raim_used_satellite_count": "6",
        "raw_raim_mean_cn0_dbhz": "44.0",
        "raw_raim_score": "0.03",
        "raw_reference_residual_rms_m": "1.5",
    }
    if degraded:
        row.update(
            {
                "rinex_mean_cn0_dbhz": "29.0",
                "rinex_low_cn0_satellite_count": "5",
                "dop_pdop": "5.5",
                "rtk_ratio": "0.8",
                "rtk_quality": "2",
                "effective_residual_norm_m": "4.0",
                "effective_pr_rms_m": "6.0",
                "effective_pr_abs_max_m": "10.0",
            }
        )
    if attack:
        row.update(
            {
                "effective_maha": "18.0",
                "effective_residual_norm_m": "9.0",
                "effective_pr_rms_m": "18.0",
                "effective_pr_abs_max_m": "34.0",
                "raw_raim_score": "1.2",
                "raw_reference_residual_rms_m": "28.0",
            }
        )
    return row


def write_fixture(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    rows = []
    rows.extend(make_row(idx) for idx in range(12))
    rows.extend(make_row(idx, degraded=True) for idx in range(12, 24))
    rows.extend(make_row(idx, attack=True) for idx in range(24, 42))
    root = PROJECT_ROOT / "build" / "adaptive_detector_smoke"
    csv_path = root / "smoke_detection.csv"
    write_fixture(csv_path, rows)

    outputs = detector.run_detectors(
        rows,
        [
            "robust_raim",
            "ekf_innovation",
            "fixed_fused",
            "fixed_cusum_fused",
            "adaptive_seq_full",
            "adaptive_seq_no_env",
        ],
        detector.DetectorConfig(),
        scenario="smoke",
    )
    by_name = {output.detector: output.metrics for output in outputs}
    robust_raim = by_name["robust_raim"]
    ekf = by_name["ekf_innovation"]
    fixed_cusum = by_name["fixed_cusum_fused"]
    adaptive = by_name["adaptive_seq_full"]
    fixed = by_name["fixed_fused"]
    no_env = by_name["adaptive_seq_no_env"]
    if robust_raim["true_positive"] <= 0 or ekf["true_positive"] <= 0:
        raise SystemExit(f"Expected robust RAIM and EKF baselines to detect attack, robust={robust_raim}, ekf={ekf}")
    if fixed_cusum["recall"] <= 0.5:
        raise SystemExit(f"Expected fixed CUSUM fused baseline to catch sustained attack, got {fixed_cusum}")
    if adaptive["true_positive"] <= 0 or adaptive["recall"] <= 0.5:
        raise SystemExit(f"Expected adaptive detector to catch sustained attack, got {adaptive}")
    if adaptive["false_positive"] > fixed["false_positive"]:
        raise SystemExit(f"Expected adaptive false positives <= fixed, adaptive={adaptive}, fixed={fixed}")
    if adaptive["false_positive"] > no_env["false_positive"]:
        raise SystemExit(f"Expected environment adaptation to reduce false positives, adaptive={adaptive}, no_env={no_env}")

    detector.write_long_csv(root / "smoke_detector_output.csv", outputs)
    print("Adaptive detector smoke test passed")
    print(f"  fixture: {csv_path}")
    print(f"  output: {root / 'smoke_detector_output.csv'}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    raise SystemExit(main())
