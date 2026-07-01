#!/usr/bin/env python3
"""Temporal held-out validation for a single route/dataset.

This is weaker than true route-held-out validation, but it prevents tuning and
testing on the exact same time segment when only one field collection exists.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import adaptive_sequential_detector as detector
import run_experiment_matrix as matrix


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run temporal held-out calibration/test evaluation on one detection CSV.")
    parser.add_argument("--base-csv", default="build/paper_platform/full_data_clean/full_data_clean_detection.csv")
    parser.add_argument("--output-dir", default="build/paper_platform/time_split_experiments")
    parser.add_argument("--train-fraction", type=float, default=0.60, help="Fraction of the time span used for calibration when --split-time-s is omitted.")
    parser.add_argument("--split-time-s", type=float, help="Original time_s boundary. Rows <= boundary are calibration; later rows are held-out test.")
    parser.add_argument("--min-segment-rows", type=int, default=24)
    parser.add_argument("--strengths-m", default="1,2,5,10")
    parser.add_argument("--ramps-s", default="1,5,20,60")
    parser.add_argument("--attack-types", default=",".join(matrix.ATTACK_TYPES))
    parser.add_argument("--attack-window", default="+20:+260")
    parser.add_argument("--adaptive-gains", default="0,0.75,1.35,2.0")
    parser.add_argument("--cusum-thresholds", default="0.35,0.5,0.75,1.0")
    parser.add_argument("--operating-fa-limit", type=float, default=6.0)
    parser.add_argument(
        "--calibration-fa-margin",
        type=float,
        default=0.55,
        help="Train-segment false-alarm target is operating-fa-limit times this margin.",
    )
    return parser.parse_args()


def clean_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def row_time(row: dict[str, str], fallback: int) -> float:
    return matrix.to_float(row, "time_s", float(fallback))


def normalize_segment(rows: list[dict[str, str]], name: str) -> list[dict[str, str]]:
    if not rows:
        return []
    start = row_time(rows[0], 0)
    normalized: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        item = dict(row)
        original_time = row_time(row, idx)
        item["segment"] = name
        item["original_time_s"] = f"{original_time:.9f}"
        item["time_s"] = f"{max(0.0, original_time - start):.9f}"
        normalized.append(item)
    return normalized


def split_rows(
    rows: list[dict[str, str]],
    train_fraction: float,
    split_time_s: float | None,
    min_segment_rows: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, float]]:
    indexed = sorted(enumerate(rows), key=lambda item: row_time(item[1], item[0]))
    ordered = [row for _idx, row in indexed]
    if not ordered:
        raise SystemExit("No rows available for temporal split.")
    times = [row_time(row, idx) for idx, row in enumerate(ordered)]
    start, end = min(times), max(times)
    if split_time_s is None:
        fraction = max(0.05, min(0.95, train_fraction))
        split_time_s = start + fraction * (end - start)
    train_raw = [row for idx, row in enumerate(ordered) if row_time(row, idx) <= split_time_s]
    test_raw = [row for idx, row in enumerate(ordered) if row_time(row, idx) > split_time_s]
    if len(train_raw) < min_segment_rows or len(test_raw) < min_segment_rows:
        split_idx = max(min_segment_rows, min(len(ordered) - min_segment_rows, int(round(len(ordered) * train_fraction))))
        train_raw = ordered[:split_idx]
        test_raw = ordered[split_idx:]
        split_time_s = row_time(train_raw[-1], split_idx - 1)
    if len(train_raw) < min_segment_rows or len(test_raw) < min_segment_rows:
        raise SystemExit(
            f"Temporal split too small: train={len(train_raw)}, test={len(test_raw)}, "
            f"minimum={min_segment_rows}. Process a longer held-out bag segment first."
        )
    train = normalize_segment(train_raw, "calibration")
    test = normalize_segment(test_raw, "heldout_test")
    meta = {
        "original_start_time_s": start,
        "original_end_time_s": end,
        "split_time_s": float(split_time_s),
        "train_rows": float(len(train)),
        "test_rows": float(len(test)),
        "train_duration_s": row_time(train[-1], len(train) - 1),
        "test_duration_s": row_time(test[-1], len(test) - 1),
    }
    return train, test, meta


def segment_scenarios(
    segment_name: str,
    base_rows: list[dict[str, str]],
    strengths: list[float],
    ramps: list[float],
    attack_types: list[str],
    window: tuple[float, float],
) -> list[tuple[dict[str, object], list[dict[str, str]]]]:
    scenarios: list[tuple[dict[str, object], list[dict[str, str]]]] = []
    clean = matrix.clone_base_rows(base_rows, "clean_real", "clean_real")
    degraded = matrix.degrade_rows(base_rows)
    for meta, rows in [
        (matrix.scenario_metadata("clean_real", "clean_real", clean), clean),
        (matrix.scenario_metadata("degraded_urban", "degraded_non_attack", degraded), degraded),
    ]:
        meta = {**meta, "split": segment_name, "split_scenario": f"{segment_name}:{meta['scenario']}"}
        scenarios.append((meta, rows))
    for attack_type in attack_types:
        for strength in strengths:
            for ramp in ramps:
                rows = matrix.attack_rows(base_rows, attack_type, strength, ramp, window)
                meta = matrix.scenario_metadata(rows[0]["scenario"], "synthetic_spoofing", rows, attack_type, strength, ramp)
                meta = {**meta, "split": segment_name, "split_scenario": f"{segment_name}:{meta['scenario']}"}
                scenarios.append((meta, rows))
    return scenarios


def non_attack_false_alarm(
    scenarios: list[tuple[dict[str, object], list[dict[str, str]]]],
    config: detector.DetectorConfig,
) -> float:
    values: list[float] = []
    for meta, rows in scenarios:
        if meta["scenario_type"] == "synthetic_spoofing":
            continue
        output = detector.run_detector(rows, "adaptive_seq_full", config, scenario=str(meta["split_scenario"]))
        values.append(float(output.metrics["false_alarm_per_min"]))
    return sum(values) / len(values) if values else 0.0


def tune_on_non_attack(
    scenarios: list[tuple[dict[str, object], list[dict[str, str]]]],
    gains: list[float],
    cusum_thresholds: list[float],
    operating_fa_limit: float,
    calibration_fa_limit: float,
) -> tuple[detector.DetectorConfig, list[dict[str, object]], str]:
    rows: list[dict[str, object]] = []
    for gain in gains:
        for threshold in cusum_thresholds:
            config = detector.DetectorConfig(adaptive_gain=gain, cusum_threshold=threshold)
            fa = non_attack_false_alarm(scenarios, config)
            rows.append(
                {
                    "adaptive_gain": gain,
                    "cusum_threshold": threshold,
                    "train_non_attack_false_alarm_per_min": fa,
                    "calibration_fa_limit": calibration_fa_limit,
                    "operating_fa_limit": operating_fa_limit,
                    "satisfies_budget": int(fa <= calibration_fa_limit),
                }
            )
    feasible = [row for row in rows if int(row["satisfies_budget"]) == 1]
    if feasible:
        best = min(
            feasible,
            key=lambda row: (
                float(row["cusum_threshold"]),
                float(row["adaptive_gain"]),
                float(row["train_non_attack_false_alarm_per_min"]),
            ),
        )
        rule = "train_non_attack_budget_most_sensitive"
    else:
        best = min(rows, key=lambda row: float(row["train_non_attack_false_alarm_per_min"]))
        rule = "minimum_false_alarm_no_feasible_budget"
    for row in rows:
        row["selection_rule"] = rule
        row["is_selected_config"] = int(row is best)
    rows.sort(key=lambda row: (-int(row["is_selected_config"]), float(row["cusum_threshold"]), float(row["adaptive_gain"])))
    selected = detector.DetectorConfig(adaptive_gain=float(best["adaptive_gain"]), cusum_threshold=float(best["cusum_threshold"]))
    return selected, rows, rule


def evaluate_scenarios(
    scenarios: list[tuple[dict[str, object], list[dict[str, str]]]],
    config: detector.DetectorConfig,
) -> list[dict[str, object]]:
    detectors = [
        "raim_only",
        "robust_raim",
        "ekf_innovation",
        "pseudorange_glrt_only",
        "lio_residual_only",
        "fixed_fused",
        "adaptive_fused",
        "adaptive_seq_full",
    ]
    rows: list[dict[str, object]] = []
    for meta, scenario_rows in scenarios:
        outputs = detector.run_detectors(scenario_rows, detectors, config, scenario=str(meta["split_scenario"]))
        for output in outputs:
            rows.append(matrix.metric_row(meta, output))
    return rows


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(rows: list[dict[str, object]], split_name: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for detector_name in sorted({str(row["detector"]) for row in rows}):
        items = [row for row in rows if row["detector"] == detector_name]
        attacks = [row for row in items if row["scenario_type"] == "synthetic_spoofing"]
        non_attack = [row for row in items if row["scenario_type"] != "synthetic_spoofing"]
        recall = mean([float(row["recall"]) for row in attacks])
        output.append(
            {
                "split": split_name,
                "detector": detector_name,
                "scenario_count": len(items),
                "attack_scenario_count": len(attacks),
                "attack_precision_mean": mean([float(row["precision"]) for row in attacks]),
                "attack_recall_mean": recall,
                "attack_f1_mean": mean([float(row["f1"]) for row in attacks]),
                "missed_detection_rate": 1.0 - recall,
                "false_alarm_per_min_mean": mean([float(row["false_alarm_per_min"]) for row in non_attack]),
                "latency_mean_s": mean([float(row["latency_mean_s"]) for row in attacks if row["latency_mean_s"] != ""]),
            }
        )
    output.sort(key=lambda row: (row["split"], float(row["attack_f1_mean"])), reverse=True)
    return output


def write_markdown(
    path: Path,
    summary_rows: list[dict[str, object]],
    selected: detector.DetectorConfig,
    split_meta: dict[str, float],
    rule: str,
    operating_fa_limit: float,
    calibration_fa_limit: float,
) -> None:
    lines = [
        "# Temporal Held-Out Experiments",
        "",
        f"- Validation type: temporal_holdout",
        f"- Calibration rows: {int(split_meta['train_rows'])}",
        f"- Held-out test rows: {int(split_meta['test_rows'])}",
        f"- Original split time_s: {split_meta['split_time_s']:.3f}",
        f"- Selected adaptive_gain: {selected.adaptive_gain:.3f}",
        f"- Selected cusum_threshold: {selected.cusum_threshold:.3f}",
        f"- Calibration FA limit: {calibration_fa_limit:.3f} alarms/min",
        f"- Held-out operating FA budget: {operating_fa_limit:.3f} alarms/min",
        f"- Selection rule: `{rule}`",
        "",
        "| Split | Detector | Attack F1 | Precision | Recall | PMD | FA/min | Latency (s) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['split']} | {row['detector']} | {float(row['attack_f1_mean']):.3f} | "
            f"{float(row['attack_precision_mean']):.3f} | {float(row['attack_recall_mean']):.3f} | "
            f"{float(row['missed_detection_rate']):.3f} | {float(row['false_alarm_per_min_mean']):.3f} | "
            f"{float(row['latency_mean_s']):.3f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    base_path = clean_path(args.base_csv)
    output_dir = clean_path(args.output_dir)
    base_rows, fieldnames = read_csv(base_path)
    if not base_rows:
        raise SystemExit(f"No rows found in {base_path}")
    train_rows, test_rows, split_meta = split_rows(base_rows, args.train_fraction, args.split_time_s, args.min_segment_rows)
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_fields = matrix.ensure_fields(fieldnames, ["segment", "original_time_s"])
    write_csv(output_dir / "calibration_segment.csv", segment_fields, train_rows)
    write_csv(output_dir / "heldout_test_segment.csv", segment_fields, test_rows)

    strengths = matrix.parse_list_float(args.strengths_m)
    ramps = matrix.parse_list_float(args.ramps_s)
    attack_types = matrix.parse_list_str(args.attack_types)
    unknown = [attack_type for attack_type in attack_types if attack_type not in matrix.ATTACK_TYPES]
    if unknown:
        raise SystemExit(f"Unknown attack types: {', '.join(unknown)}")
    window = matrix.parse_window(args.attack_window)

    train_scenarios = segment_scenarios("calibration", train_rows, strengths, ramps, attack_types, window)
    test_scenarios = segment_scenarios("heldout_test", test_rows, strengths, ramps, attack_types, window)
    selected, tuning_rows, rule = tune_on_non_attack(
        train_scenarios,
        matrix.parse_list_float(args.adaptive_gains),
        matrix.parse_list_float(args.cusum_thresholds),
        args.operating_fa_limit,
        args.operating_fa_limit * args.calibration_fa_margin,
    )
    train_results = evaluate_scenarios(train_scenarios, selected)
    test_results = evaluate_scenarios(test_scenarios, selected)
    summary_rows = aggregate(train_results, "calibration") + aggregate(test_results, "heldout_test")

    result_columns = [
        "split",
        "split_scenario",
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
    summary_columns = [
        "split",
        "detector",
        "scenario_count",
        "attack_scenario_count",
        "attack_precision_mean",
        "attack_recall_mean",
        "attack_f1_mean",
        "missed_detection_rate",
        "false_alarm_per_min_mean",
        "latency_mean_s",
    ]
    tuning_columns = [
        "adaptive_gain",
        "cusum_threshold",
        "train_non_attack_false_alarm_per_min",
        "calibration_fa_limit",
        "operating_fa_limit",
        "satisfies_budget",
        "selection_rule",
        "is_selected_config",
    ]
    write_csv(output_dir / "train_results.csv", result_columns, train_results)
    write_csv(output_dir / "test_results.csv", result_columns, test_results)
    write_csv(output_dir / "detector_summary.csv", summary_columns, summary_rows)
    write_csv(output_dir / "tuning_summary.csv", tuning_columns, tuning_rows)

    payload = {
        "validation_type": "temporal_holdout",
        "base_csv": str(base_path),
        "split": split_meta,
        "selected_config": selected.__dict__,
        "selection_rule": rule,
        "operating_fa_limit": args.operating_fa_limit,
        "calibration_fa_margin": args.calibration_fa_margin,
        "calibration_fa_limit": args.operating_fa_limit * args.calibration_fa_margin,
        "outputs": {
            "calibration_segment_csv": str(output_dir / "calibration_segment.csv"),
            "heldout_test_segment_csv": str(output_dir / "heldout_test_segment.csv"),
            "train_results_csv": str(output_dir / "train_results.csv"),
            "test_results_csv": str(output_dir / "test_results.csv"),
            "detector_summary_csv": str(output_dir / "detector_summary.csv"),
            "tuning_summary_csv": str(output_dir / "tuning_summary.csv"),
        },
    }
    write_json(output_dir / "time_split_summary.json", payload)
    write_markdown(
        output_dir / "time_split_summary.md",
        summary_rows,
        selected,
        split_meta,
        rule,
        args.operating_fa_limit,
        args.operating_fa_limit * args.calibration_fa_margin,
    )

    print("Temporal held-out experiments complete")
    print(f"  calibration rows: {len(train_rows)}")
    print(f"  held-out test rows: {len(test_rows)}")
    print(f"  split time_s: {split_meta['split_time_s']:.3f}")
    print(f"  selected adaptive_gain={selected.adaptive_gain:.3f}, cusum_threshold={selected.cusum_threshold:.3f}")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    raise SystemExit(main())
