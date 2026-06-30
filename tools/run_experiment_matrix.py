#!/usr/bin/env python3
"""Generate the method-paper experiment matrix and detector baselines."""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import sys

import adaptive_sequential_detector as detector


PROJECT_ROOT = Path(__file__).resolve().parents[1]


ATTACK_TYPES = [
    "position_bias",
    "pseudorange_delay",
    "single_sat_outlier",
    "coordinated_spoof",
    "slow_drift",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run clean/degraded/spoofing matrix for the adaptive sequential GLRT paper method.")
    parser.add_argument("--base-csv", default="build/paper_platform/full_data_clean/full_data_clean_detection.csv")
    parser.add_argument("--output-dir", default="build/paper_platform/adaptive_experiments")
    parser.add_argument("--strengths-m", default="1,2,5,10")
    parser.add_argument("--ramps-s", default="1,5,20,60")
    parser.add_argument("--attack-types", default=",".join(ATTACK_TYPES))
    parser.add_argument("--attack-window", default="+20:+260")
    parser.add_argument("--write-scenario-csvs", action="store_true", default=True)
    parser.add_argument("--default-scenario", default="coordinated_spoof_s10_r5")
    parser.add_argument("--cusum-threshold", type=float, default=detector.DetectorConfig.cusum_threshold)
    parser.add_argument("--adaptive-gain", type=float, default=1.35)
    parser.add_argument("--base-threshold", type=float, default=1.0)
    return parser.parse_args()


def clean_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_list_float(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_list_str(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value is None or value == "" or str(value).lower() == "nan":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def set_float(row: dict[str, str], key: str, value: float) -> None:
    if math.isnan(value) or math.isinf(value):
        row[key] = ""
    else:
        row[key] = f"{value:.9f}"


def set_int(row: dict[str, str], key: str, value: int) -> None:
    row[key] = str(int(value))


def safe_norm3(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


def parse_window(value: str) -> tuple[float, float]:
    if ":" not in value:
        raise SystemExit("--attack-window must be start:end")
    start_text, end_text = value.split(":", 1)
    start = float(start_text.lstrip("+")) if start_text.startswith("+") else float(start_text)
    end = float(end_text.lstrip("+")) if end_text.startswith("+") else float(end_text)
    if end <= start:
        raise SystemExit("--attack-window end must be greater than start")
    return start, end


def attack_scale(time_s: float, start_s: float, end_s: float, ramp_s: float, attack_type: str) -> float:
    if time_s < start_s or time_s > end_s:
        return 0.0
    if attack_type == "slow_drift":
        return max(0.0, min(1.0, (time_s - start_s) / max(1e-9, end_s - start_s)))
    if ramp_s <= 1e-9:
        return 1.0
    scale = min(1.0, max(0.0, (time_s - start_s) / ramp_s))
    scale = min(scale, max(0.0, (end_s - time_s) / ramp_s))
    return scale


def ensure_fields(fieldnames: list[str], extra: list[str]) -> list[str]:
    output = fieldnames[:]
    for field in extra:
        if field not in output:
            output.append(field)
    return output


def reset_detection_fields(row: dict[str, str], scenario: str, scenario_type: str) -> None:
    row["scenario"] = scenario
    row["scenario_type"] = scenario_type
    row["detected"] = "0"
    row["triggered"] = "0"
    row["spoof_score"] = "0.000000000"
    row["score_threshold"] = "1.000000000"
    row["attack_label"] = "0"
    row["attack_scale"] = "0.000000000"
    row["attack_kind"] = "none"
    row["attack_strength_m"] = "0.000000000"
    row["attack_ramp_s"] = "0.000000000"
    row["environment_condition"] = "real"


def clone_base_rows(base_rows: list[dict[str, str]], scenario: str, scenario_type: str) -> list[dict[str, str]]:
    rows = [deepcopy(row) for row in base_rows]
    for row in rows:
        reset_detection_fields(row, scenario, scenario_type)
    return rows


def degrade_rows(base_rows: list[dict[str, str]], scenario: str = "degraded_urban") -> list[dict[str, str]]:
    rows = clone_base_rows(base_rows, scenario, "degraded_non_attack")
    for idx, row in enumerate(rows):
        t = to_float(row, "time_s", float(idx))
        # Deterministic urban-canyon-like degradation: multipath/occlusion without adversarial labels.
        scale = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(0.025 * t))
        if 150.0 <= t <= 620.0:
            scale = min(1.0, scale + 0.25)
        row["environment_condition"] = "degraded_urban"
        set_float(row, "rinex_mean_cn0_dbhz", max(24.0, to_float(row, "rinex_mean_cn0_dbhz", 42.0) - 9.0 * scale))
        set_float(row, "rinex_min_cn0_dbhz", max(18.0, to_float(row, "rinex_min_cn0_dbhz", 35.0) - 10.0 * scale))
        set_int(row, "rinex_low_cn0_satellite_count", int(to_float(row, "rinex_low_cn0_satellite_count", 0.0) + 4 * scale))
        set_float(row, "dop_pdop", to_float(row, "dop_pdop", 1.4) * (1.0 + 1.45 * scale))
        set_float(row, "dop_hdop", to_float(row, "dop_hdop", 0.9) * (1.0 + 1.35 * scale))
        set_float(row, "rtk_ratio", max(0.4, to_float(row, "rtk_ratio", 4.0) - 2.4 * scale))
        if scale > 0.72:
            set_int(row, "rtk_quality", 2)
        set_int(row, "rtk_satellites", max(5, int(to_float(row, "rtk_satellites", 14.0) - 5 * scale)))
        set_int(row, "raw_healthy_pr_count", max(4, int(to_float(row, "raw_healthy_pr_count", 10.0) - 4 * scale)))
        set_int(row, "raw_pr_outlier_reject_count", int(to_float(row, "raw_pr_outlier_reject_count", 0.0) + 1 + 2 * scale))
        set_float(row, "effective_residual_norm_m", to_float(row, "effective_residual_norm_m", 0.0) + 1.2 * scale)
        set_float(row, "effective_maha", to_float(row, "effective_maha", 0.0) + 0.25 * scale)
        set_float(row, "effective_pr_rms_m", math.sqrt(to_float(row, "effective_pr_rms_m", 0.0) ** 2 + (3.0 * scale) ** 2))
        set_float(row, "effective_pr_abs_max_m", to_float(row, "effective_pr_abs_max_m", 0.0) + 4.5 * scale)
    return rows


def apply_attack(row: dict[str, str], attack_type: str, strength_m: float, scale: float) -> None:
    if scale <= 0.0:
        return
    set_int(row, "attack_label", 1)
    set_float(row, "attack_scale", scale)
    row["attack_kind"] = attack_type
    set_float(row, "attack_strength_m", strength_m)

    base_x = to_float(row, "loose_residual_x_m", 0.0)
    base_y = to_float(row, "loose_residual_y_m", 0.0)
    base_z = to_float(row, "loose_residual_z_m", 0.0)
    pr_rms = to_float(row, "effective_pr_rms_m", to_float(row, "raw_pr_rms_m", 0.0))
    pr_abs = to_float(row, "effective_pr_abs_max_m", to_float(row, "raw_pr_abs_max_m", 0.0))
    raw_ref = to_float(row, "raw_reference_residual_rms_m", 0.0)
    raw_raim = to_float(row, "raw_raim_score", 0.0)

    pos_bias = 0.0
    pr_delay = 0.0
    raw_ref_bias = 0.0
    raim_boost = 0.0
    if attack_type == "position_bias":
        pos_bias = strength_m
        pr_delay = 0.45 * strength_m
        raw_ref_bias = 0.35 * strength_m
    elif attack_type == "pseudorange_delay":
        pos_bias = 0.18 * strength_m
        pr_delay = 2.6 * strength_m
        raw_ref_bias = 1.1 * strength_m
    elif attack_type == "single_sat_outlier":
        pr_delay = 0.7 * strength_m
        outlier_m = 18.0 * strength_m
        raw_ref_bias = 0.28 * outlier_m
        raim_boost = (outlier_m / 150.0) ** 2
        pr_abs += 0.45 * outlier_m * scale
    elif attack_type == "coordinated_spoof":
        pos_bias = strength_m
        pr_delay = 1.8 * strength_m
        raw_ref_bias = 0.8 * strength_m
        raim_boost = 0.06 * strength_m / 10.0
    elif attack_type == "slow_drift":
        pos_bias = 1.25 * strength_m
        pr_delay = 1.2 * strength_m
        raw_ref_bias = 0.65 * strength_m
        raim_boost = 0.04 * strength_m / 10.0
    else:
        raise ValueError(f"Unknown attack type: {attack_type}")

    sx = pos_bias * scale
    sy = 0.36 * pos_bias * scale
    sz = 0.12 * pos_bias * scale
    set_float(row, "synthetic_offset_x_m", sx)
    set_float(row, "synthetic_offset_y_m", sy)
    set_float(row, "synthetic_offset_z_m", sz)
    set_float(row, "synthetic_pseudorange_delay_m", pr_delay * scale)
    set_float(row, "effective_residual_x_m", base_x + sx)
    set_float(row, "effective_residual_y_m", base_y + sy)
    set_float(row, "effective_residual_z_m", base_z + sz)
    set_float(row, "effective_residual_norm_m", safe_norm3(base_x + sx, base_y + sy, base_z + sz))
    residual_norm = to_float(row, "loose_residual_norm_m", safe_norm3(base_x, base_y, base_z))
    effective_norm = safe_norm3(base_x + sx, base_y + sy, base_z + sz)
    set_float(row, "effective_maha", to_float(row, "loose_maha", 0.0) + max(0.0, effective_norm * effective_norm - residual_norm * residual_norm) / 9.0)
    set_float(row, "effective_pr_rms_m", math.sqrt(pr_rms * pr_rms + (pr_delay * scale) ** 2))
    set_float(row, "effective_pr_abs_mean_m", to_float(row, "effective_pr_abs_mean_m", to_float(row, "raw_pr_abs_mean_m", 0.0)) + 0.45 * abs(pr_delay) * scale)
    set_float(row, "effective_pr_abs_max_m", pr_abs + abs(pr_delay) * scale)
    if to_float(row, "raw_raim_used_satellite_count", 0.0) > 0.0:
        set_float(row, "raw_reference_residual_rms_m", math.sqrt(raw_ref * raw_ref + (raw_ref_bias * scale) ** 2))
        set_float(row, "raw_reference_score", to_float(row, "raw_reference_score", 0.0) + abs(raw_ref_bias) * scale / 18.0)
        set_float(row, "raw_raim_score", raw_raim + raim_boost * scale * scale)
        set_int(row, "raw_raim_detected", 1 if to_float(row, "raw_raim_score", 0.0) >= 1.0 else 0)


def attack_rows(
    base_rows: list[dict[str, str]],
    attack_type: str,
    strength_m: float,
    ramp_s: float,
    window: tuple[float, float],
) -> list[dict[str, str]]:
    scenario = f"{attack_type}_s{strength_m:g}_r{ramp_s:g}".replace(".", "p")
    rows = clone_base_rows(base_rows, scenario, "synthetic_spoofing")
    for row in rows:
        set_float(row, "attack_ramp_s", ramp_s)
        t = to_float(row, "time_s")
        scale = attack_scale(t, window[0], window[1], ramp_s, attack_type)
        apply_attack(row, attack_type, strength_m, scale)
    return rows


def scenario_metadata(name: str, scenario_type: str, rows: list[dict[str, str]], attack_type: str = "none", strength_m: float = 0.0, ramp_s: float = 0.0) -> dict[str, object]:
    labels = [1 if to_float(row, "attack_label") >= 0.5 else 0 for row in rows]
    return {
        "scenario": name,
        "scenario_type": scenario_type,
        "attack_type": attack_type,
        "strength_m": strength_m,
        "ramp_s": ramp_s,
        "rows": len(rows),
        "positive_rows": sum(labels),
    }


def aggregate_detector_metrics(results: list[dict[str, object]]) -> list[dict[str, object]]:
    detectors = sorted({str(row["detector"]) for row in results})
    aggregate: list[dict[str, object]] = []
    for detector_name in detectors:
        items = [row for row in results if row["detector"] == detector_name]
        attack_items = [row for row in items if row["scenario_type"] == "synthetic_spoofing"]
        clean = next((row for row in items if row["scenario_type"] == "clean_real"), None)
        degraded = next((row for row in items if row["scenario_type"] == "degraded_non_attack"), None)
        def mean(key: str, rows: list[dict[str, object]]) -> float:
            values = [float(row[key]) for row in rows]
            return sum(values) / len(values) if values else 0.0
        aggregate.append(
            {
                "detector": detector_name,
                "attack_precision_mean": mean("precision", attack_items),
                "attack_recall_mean": mean("recall", attack_items),
                "attack_f1_mean": mean("f1", attack_items),
                "attack_auc_mean": mean("roc_auc", [row for row in attack_items if row["roc_auc"] != ""]),
                "attack_latency_mean_s": mean("latency_mean_s", [row for row in attack_items if row["latency_mean_s"] != ""]),
                "clean_false_alarm_per_min": clean["false_alarm_per_min"] if clean else 0.0,
                "degraded_false_alarm_per_min": degraded["false_alarm_per_min"] if degraded else 0.0,
                "mean_false_alarm_per_min": mean("false_alarm_per_min", [row for row in items if row["scenario_type"] != "synthetic_spoofing"]),
                "scenario_count": len(items),
                "attack_scenario_count": len(attack_items),
            }
        )
    aggregate.sort(key=lambda row: (float(row["attack_f1_mean"]), -float(row["mean_false_alarm_per_min"])), reverse=True)
    return aggregate


def metric_row(scenario_meta: dict[str, object], output: detector.DetectorOutput) -> dict[str, object]:
    metrics = output.metrics
    latency = metrics["detection_latency_s"]
    assert isinstance(latency, dict)
    return {
        **scenario_meta,
        "detector": output.detector,
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "specificity": metrics["specificity"],
        "f1": metrics["f1"],
        "roc_auc": metrics["roc_auc"] if metrics["roc_auc"] is not None else "",
        "false_alarm_per_min": metrics["false_alarm_per_min"],
        "detected_rows": metrics["detected_rows"],
        "false_positive": metrics["false_positive"],
        "false_negative": metrics["false_negative"],
        "latency_mean_s": latency["mean"] if latency["mean"] is not None else "",
        "latency_min_s": latency["min"] if latency["min"] is not None else "",
        "latency_max_s": latency["max"] if latency["max"] is not None else "",
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(
    path: Path,
    aggregate_rows: list[dict[str, object]],
    scenario_rows: list[dict[str, object]],
    paired_stats: dict[str, object],
) -> None:
    lines = [
        "# Adaptive Sequential GLRT Experiment Matrix",
        "",
        f"- Scenarios: {len(scenario_rows)}",
        f"- Attack scenarios: {sum(1 for row in scenario_rows if row['scenario_type'] == 'synthetic_spoofing')}",
        "",
        "| Detector | Attack F1 | Attack Precision | Attack Recall | Clean FA/min | Degraded FA/min | Latency (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate_rows:
        lines.append(
            f"| {row['detector']} | {float(row['attack_f1_mean']):.3f} | {float(row['attack_precision_mean']):.3f} | "
            f"{float(row['attack_recall_mean']):.3f} | {float(row['clean_false_alarm_per_min']):.3f} | "
            f"{float(row['degraded_false_alarm_per_min']):.3f} | {float(row['attack_latency_mean_s']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Paired F1 Difference",
            "",
            f"- Primary: `{paired_stats['primary']}`",
            f"- Baseline: `{paired_stats['baseline']}`",
            f"- Paired attack scenarios: {paired_stats['paired_scenarios']}",
            f"- Mean F1 difference: {float(paired_stats['mean_f1_difference']):.6f}",
            f"- Bootstrap 95% CI: [{float(paired_stats['ci95_low']):.6f}, {float(paired_stats['ci95_high']):.6f}]",
            f"- Sign-test p-value: {float(paired_stats['sign_test_p_value']):.6g}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sign_test_p_value(wins: int, losses: int) -> float:
    n = wins + losses
    if n <= 0:
        return 1.0
    observed = max(wins, losses)
    tail = sum(math.comb(n, k) for k in range(observed, n + 1)) / (2.0**n)
    return min(1.0, 2.0 * tail)


def paired_detector_stats(
    matrix_rows: list[dict[str, object]],
    primary: str = "adaptive_seq_full",
    baseline: str = "fixed_fused",
    bootstrap_samples: int = 2000,
) -> dict[str, object]:
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in matrix_rows:
        if row["scenario_type"] != "synthetic_spoofing":
            continue
        by_key[(str(row["scenario"]), str(row["detector"]))] = row
    scenarios = sorted({scenario for scenario, detector_name in by_key if detector_name == primary and (scenario, baseline) in by_key})
    diffs = [float(by_key[(scenario, primary)]["f1"]) - float(by_key[(scenario, baseline)]["f1"]) for scenario in scenarios]
    if not diffs:
        return {
            "primary": primary,
            "baseline": baseline,
            "paired_scenarios": 0,
            "mean_f1_difference": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "sign_test_p_value": 1.0,
        }
    rng = random.Random(20260701)
    means = []
    for _ in range(bootstrap_samples):
        sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    wins = sum(1 for diff in diffs if diff > 1e-12)
    losses = sum(1 for diff in diffs if diff < -1e-12)
    ties = len(diffs) - wins - losses
    return {
        "primary": primary,
        "baseline": baseline,
        "paired_scenarios": len(diffs),
        "mean_f1_difference": sum(diffs) / len(diffs),
        "ci95_low": low,
        "ci95_high": high,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "sign_test_p_value": sign_test_p_value(wins, losses),
    }


def main() -> int:
    args = parse_args()
    base_path = clean_path(args.base_csv)
    output_dir = clean_path(args.output_dir)
    scenario_dir = output_dir / "scenarios"
    output_dir.mkdir(parents=True, exist_ok=True)
    base_rows, fieldnames = read_csv(base_path)
    if not base_rows:
        raise SystemExit(f"No rows found in {base_path}")

    extra_fields = [
        "scenario",
        "scenario_type",
        "attack_kind",
        "attack_strength_m",
        "attack_ramp_s",
        "environment_condition",
    ]
    scenario_fields = ensure_fields(fieldnames, extra_fields)
    strengths = parse_list_float(args.strengths_m)
    ramps = parse_list_float(args.ramps_s)
    attack_types = parse_list_str(args.attack_types)
    unknown = [attack_type for attack_type in attack_types if attack_type not in ATTACK_TYPES]
    if unknown:
        raise SystemExit(f"Unknown attack types: {', '.join(unknown)}")
    window = parse_window(args.attack_window)

    scenarios: list[tuple[dict[str, object], list[dict[str, str]]]] = []
    clean_rows = clone_base_rows(base_rows, "clean_real", "clean_real")
    scenarios.append((scenario_metadata("clean_real", "clean_real", clean_rows), clean_rows))
    degraded = degrade_rows(base_rows)
    scenarios.append((scenario_metadata("degraded_urban", "degraded_non_attack", degraded), degraded))
    for attack_type in attack_types:
        for strength_m in strengths:
            for ramp_s in ramps:
                rows = attack_rows(base_rows, attack_type, strength_m, ramp_s, window)
                scenario_name = rows[0]["scenario"]
                scenarios.append((scenario_metadata(scenario_name, "synthetic_spoofing", rows, attack_type, strength_m, ramp_s), rows))

    config = detector.DetectorConfig(
        base_threshold=args.base_threshold,
        adaptive_gain=args.adaptive_gain,
        cusum_threshold=args.cusum_threshold,
    )
    detectors = detector.DETECTORS
    matrix_rows: list[dict[str, object]] = []
    default_timeline: list[dict[str, str]] | None = None

    for meta, rows in scenarios:
        if args.write_scenario_csvs:
            write_csv(scenario_dir / f"{meta['scenario']}.csv", scenario_fields, rows)
        outputs = detector.run_detectors(rows, detectors, config, scenario=str(meta["scenario"]))
        for output in outputs:
            matrix_rows.append(metric_row(meta, output))
            if meta["scenario"] == args.default_scenario and output.detector == "adaptive_seq_full":
                default_timeline = output.rows

    scenario_rows = [meta for meta, _rows in scenarios]
    aggregate_rows = aggregate_detector_metrics(matrix_rows)
    paired_stats = paired_detector_stats(matrix_rows)

    matrix_columns = [
        "scenario",
        "scenario_type",
        "attack_type",
        "strength_m",
        "ramp_s",
        "rows",
        "positive_rows",
        "detector",
        "precision",
        "recall",
        "specificity",
        "f1",
        "roc_auc",
        "false_alarm_per_min",
        "detected_rows",
        "false_positive",
        "false_negative",
        "latency_mean_s",
        "latency_min_s",
        "latency_max_s",
    ]
    aggregate_columns = [
        "detector",
        "attack_precision_mean",
        "attack_recall_mean",
        "attack_f1_mean",
        "attack_auc_mean",
        "attack_latency_mean_s",
        "clean_false_alarm_per_min",
        "degraded_false_alarm_per_min",
        "mean_false_alarm_per_min",
        "scenario_count",
        "attack_scenario_count",
    ]
    scenario_columns = ["scenario", "scenario_type", "attack_type", "strength_m", "ramp_s", "rows", "positive_rows"]
    write_csv(output_dir / "matrix_results.csv", matrix_columns, matrix_rows)
    write_csv(output_dir / "detector_summary.csv", aggregate_columns, aggregate_rows)
    write_csv(output_dir / "scenario_summary.csv", scenario_columns, scenario_rows)
    if default_timeline is None:
        # Fall back to the strongest coordinated scenario if the requested one was not generated.
        for meta, rows in scenarios:
            if str(meta["scenario"]).startswith("coordinated_spoof_s10"):
                default_timeline = detector.run_detector(rows, "adaptive_seq_full", config, scenario=str(meta["scenario"])).rows
                break
    if default_timeline:
        detector.write_long_csv(output_dir / "adaptive_timeline.csv", [detector.DetectorOutput("adaptive_seq_full", default_timeline, detector.evaluate_rows(default_timeline))])

    summary = {
        "base_csv": str(base_path),
        "scenarios": len(scenario_rows),
        "attack_scenarios": sum(1 for row in scenario_rows if row["scenario_type"] == "synthetic_spoofing"),
        "detectors": detectors,
        "best_detector": aggregate_rows[0] if aggregate_rows else {},
        "paired_statistics": paired_stats,
        "config": config.__dict__,
        "outputs": {
            "matrix_results_csv": str(output_dir / "matrix_results.csv"),
            "detector_summary_csv": str(output_dir / "detector_summary.csv"),
            "scenario_summary_csv": str(output_dir / "scenario_summary.csv"),
            "adaptive_timeline_csv": str(output_dir / "adaptive_timeline.csv"),
        },
    }
    write_json(output_dir / "experiment_summary.json", summary)
    write_json(output_dir / "statistical_tests.json", paired_stats)
    write_markdown(output_dir / "experiment_summary.md", aggregate_rows, scenario_rows, paired_stats)

    print("Adaptive experiment matrix complete")
    print(f"  scenarios: {summary['scenarios']}")
    print(f"  attack scenarios: {summary['attack_scenarios']}")
    if aggregate_rows:
        print(f"  best detector: {aggregate_rows[0]['detector']} F1={float(aggregate_rows[0]['attack_f1_mean']):.3f}")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    raise SystemExit(main())
