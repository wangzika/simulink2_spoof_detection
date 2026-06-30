#!/usr/bin/env python3
"""Environment-adaptive sequential GLRT detectors and baseline comparison."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class DetectorConfig:
    residual_scale_m: float = 6.0
    pr_rms_scale_m: float = 12.0
    pr_abs_scale_m: float = 24.0
    reference_residual_scale_m: float = 18.0
    doppler_scale_mps: float = 0.35
    base_threshold: float = 1.0
    adaptive_gain: float = 1.35
    cusum_threshold: float = 0.50
    cusum_drift: float = 0.10
    reset_leak: float = 0.035
    confidence_slope: float = 2.6


@dataclass
class DetectorOutput:
    detector: str
    rows: list[dict[str, str]]
    metrics: dict[str, object]


DETECTORS = [
    "raim_only",
    "pseudorange_glrt_only",
    "lio_residual_only",
    "fixed_fused",
    "adaptive_fused",
    "adaptive_seq_full",
    "adaptive_seq_no_raw",
    "adaptive_seq_no_lio",
    "adaptive_seq_no_env",
    "adaptive_seq_no_cusum",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run environment-adaptive sequential GLRT and baseline detectors.")
    parser.add_argument("input", help="Detection CSV from build_detection_dataset.py or run_experiment_matrix.py.")
    parser.add_argument("--output-csv", help="Long-format detector output CSV.")
    parser.add_argument("--metrics-json", help="Detector metrics JSON.")
    parser.add_argument("--metrics-md", help="Markdown metrics report.")
    parser.add_argument("--detectors", default=",".join(DETECTORS), help="Comma-separated detector names.")
    parser.add_argument("--scenario", default="", help="Optional scenario name stored in outputs.")
    parser.add_argument("--residual-scale-m", type=float, default=DetectorConfig.residual_scale_m)
    parser.add_argument("--pr-rms-scale-m", type=float, default=DetectorConfig.pr_rms_scale_m)
    parser.add_argument("--pr-abs-scale-m", type=float, default=DetectorConfig.pr_abs_scale_m)
    parser.add_argument("--reference-residual-scale-m", type=float, default=DetectorConfig.reference_residual_scale_m)
    parser.add_argument("--doppler-scale-mps", type=float, default=DetectorConfig.doppler_scale_mps)
    parser.add_argument("--base-threshold", type=float, default=DetectorConfig.base_threshold)
    parser.add_argument("--adaptive-gain", type=float, default=DetectorConfig.adaptive_gain)
    parser.add_argument("--cusum-threshold", type=float, default=DetectorConfig.cusum_threshold)
    parser.add_argument("--cusum-drift", type=float, default=DetectorConfig.cusum_drift)
    parser.add_argument("--reset-leak", type=float, default=DetectorConfig.reset_leak)
    return parser.parse_args()


def clean_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value is None or value == "" or str(value).lower() == "nan":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def to_int(row: dict[str, str], key: str, default: int = 0) -> int:
    return int(round(to_float(row, key, float(default))))


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def safe_ratio(value: float, scale: float) -> float:
    return value / max(1e-9, scale)


def sigmoid(value: float) -> float:
    if value >= 40.0:
        return 1.0
    if value <= -40.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def finite(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return value


def median_dt(times: list[float]) -> float:
    if len(times) < 2:
        return 1.0
    deltas = sorted(max(0.0, b - a) for a, b in zip(times, times[1:]) if b >= a)
    if not deltas:
        return 1.0
    return deltas[len(deltas) // 2]


def attack_segments(times: list[float], labels: list[int]) -> list[tuple[float, float, int, int]]:
    segments: list[tuple[float, float, int, int]] = []
    start_idx: int | None = None
    for idx, label in enumerate(labels):
        if label and start_idx is None:
            start_idx = idx
        if start_idx is not None and (not label or idx == len(labels) - 1):
            end_idx = idx if label and idx == len(labels) - 1 else idx - 1
            segments.append((times[start_idx], times[end_idx], start_idx, end_idx))
            start_idx = None
    return segments


def roc_auc(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for ps in positives:
        for ns in negatives:
            if ps > ns:
                wins += 1.0
            elif ps == ns:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def evaluate_rows(rows: list[dict[str, str]], score_key: str = "detector_score") -> dict[str, object]:
    labels = [1 if to_float(row, "attack_label") >= 0.5 else 0 for row in rows]
    detections = [1 if to_float(row, "detected") >= 0.5 else 0 for row in rows]
    scores = [to_float(row, score_key) for row in rows]
    times = [to_float(row, "time_s", float(idx)) for idx, row in enumerate(rows)]

    tp = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 1)
    tn = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 0)
    fp = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 1)
    fn = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    dt = median_dt(times)
    negative_minutes = max(1e-9, sum(1 for label in labels if label == 0) * dt / 60.0)
    false_alarm_per_min = fp / negative_minutes if any(label == 0 for label in labels) else 0.0

    latencies: list[float] = []
    for start_t, _end_t, start_idx, end_idx in attack_segments(times, labels):
        first_detection = None
        for idx in range(start_idx, end_idx + 1):
            if detections[idx]:
                first_detection = times[idx]
                break
        if first_detection is not None:
            latencies.append(max(0.0, first_detection - start_t))

    auc = roc_auc(labels, scores)
    return {
        "rows": len(rows),
        "positive_rows": sum(labels),
        "detected_rows": sum(detections),
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "roc_auc": auc,
        "false_alarm_per_min": false_alarm_per_min,
        "median_dt_s": dt,
        "detection_latency_s": {
            "count": len(latencies),
            "mean": sum(latencies) / len(latencies) if latencies else None,
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
    }


def environment_degradation(row: dict[str, str]) -> dict[str, float]:
    cn0_values = [
        to_float(row, "rinex_mean_cn0_dbhz", 0.0),
        to_float(row, "raw_raim_mean_cn0_dbhz", 0.0),
    ]
    cn0_values = [value for value in cn0_values if value > 0.0]
    cn0 = sum(cn0_values) / len(cn0_values) if cn0_values else 42.0
    pdop = to_float(row, "dop_pdop", 1.8)
    hdop = to_float(row, "dop_hdop", 1.0)
    satellites = max(
        to_float(row, "rtk_satellites", 0.0),
        to_float(row, "rinex_satellite_count", 0.0),
        to_float(row, "raw_raim_used_satellite_count", 0.0),
    )
    if satellites <= 0.0:
        satellites = 14.0
    ratio = to_float(row, "rtk_ratio", 4.0)
    raw_healthy = to_float(row, "raw_healthy_pr_count", satellites)
    low_cn0 = to_float(row, "rinex_low_cn0_satellite_count", 0.0)
    raw_outliers = to_float(row, "raw_pr_outlier_reject_count", 0.0)
    rtk_quality = to_float(row, "rtk_quality", 1.0)
    aligned = to_float(row, "loose_aligned", 1.0)
    raw_raim_coverage = 1.0 if to_float(row, "raw_raim_used_satellite_count", 0.0) > 0.0 else 0.0

    cn0_penalty = clamp((38.0 - cn0) / 12.0, 0.0, 1.0)
    dop_penalty = 0.5 * clamp((pdop - 2.0) / 4.0, 0.0, 1.0) + 0.5 * clamp((hdop - 1.2) / 3.0, 0.0, 1.0)
    sat_penalty = clamp((12.0 - satellites) / 8.0, 0.0, 1.0)
    ratio_penalty = clamp((3.0 - ratio) / 3.0, 0.0, 1.0) if ratio > 0.0 else 0.35
    quality_penalty = 0.0
    if rtk_quality > 0.0 and rtk_quality != 1.0:
        quality_penalty += 0.45
    if aligned < 0.5:
        quality_penalty += 0.35
    healthy_penalty = clamp((8.0 - raw_healthy) / 8.0, 0.0, 1.0)
    low_cn0_penalty = clamp(low_cn0 / max(1.0, satellites), 0.0, 1.0)
    outlier_penalty = clamp(raw_outliers / 4.0, 0.0, 1.0)

    degradation = (
        0.22 * cn0_penalty
        + 0.18 * dop_penalty
        + 0.16 * sat_penalty
        + 0.13 * ratio_penalty
        + 0.13 * quality_penalty
        + 0.08 * healthy_penalty
        + 0.06 * low_cn0_penalty
        + 0.04 * outlier_penalty
    )
    return {
        "environment_degradation": clamp(degradation, 0.0, 1.25),
        "cn0_penalty": cn0_penalty,
        "dop_penalty": dop_penalty,
        "satellite_penalty": sat_penalty,
        "ratio_penalty": ratio_penalty,
        "quality_penalty": quality_penalty,
        "raw_raim_coverage": raw_raim_coverage,
    }


def score_components(row: dict[str, str], config: DetectorConfig, use_raw: bool = True, use_lio: bool = True) -> dict[str, float]:
    gate = max(1e-9, to_float(row, "loose_gate_chi2", 16.27))
    maha = math.sqrt(max(0.0, to_float(row, "effective_maha", to_float(row, "loose_maha"))) / gate)
    residual = safe_ratio(to_float(row, "effective_residual_norm_m", to_float(row, "loose_residual_norm_m")), config.residual_scale_m)
    lio = max(residual, maha) if use_lio else 0.0

    pr_rms = safe_ratio(to_float(row, "effective_pr_rms_m", to_float(row, "raw_pr_rms_m")), config.pr_rms_scale_m)
    pr_abs = safe_ratio(to_float(row, "effective_pr_abs_max_m", to_float(row, "raw_pr_abs_max_m")), config.pr_abs_scale_m)
    pseudorange = max(pr_rms, pr_abs)

    raim_score = to_float(row, "raw_raim_score", 0.0)
    reference = safe_ratio(to_float(row, "raw_reference_residual_rms_m", 0.0), config.reference_residual_scale_m)
    raw = max(raim_score, reference) if use_raw else 0.0

    doppler = safe_ratio(to_float(row, "raw_doppler_rms_mps", 0.0), config.doppler_scale_mps)
    quality = 0.0
    rtk_quality = to_float(row, "rtk_quality", 1.0)
    if rtk_quality > 0.0 and rtk_quality != 1.0:
        quality += 0.25
    rtk_ratio = to_float(row, "rtk_ratio", 4.0)
    if rtk_ratio > 0.0:
        quality += clamp((3.0 - rtk_ratio) / 12.0, 0.0, 0.25)

    raw_available = to_float(row, "raw_raim_used_satellite_count", 0.0) > 0.0
    if use_raw and raw_available:
        fused = 0.32 * lio + 0.25 * pseudorange + 0.23 * raw + 0.08 * doppler + 0.12 * quality
    else:
        # Missing raw geometry should reduce confidence in LIO-only excursions.
        fused = 0.24 * lio + 0.18 * pseudorange + 0.08 * doppler + 0.10 * quality
    return {
        "score_lio": finite(lio),
        "score_residual": finite(residual),
        "score_maha": finite(maha),
        "score_pseudorange": finite(pseudorange),
        "score_pr_rms": finite(pr_rms),
        "score_pr_abs": finite(pr_abs),
        "score_raw": finite(raw),
        "score_raim": finite(raim_score),
        "score_reference": finite(reference),
        "score_doppler": finite(doppler),
        "score_quality": finite(quality),
        "score_fused": finite(fused),
    }


def adaptive_threshold(row: dict[str, str], config: DetectorConfig, use_env: bool = True) -> tuple[float, dict[str, float]]:
    env = environment_degradation(row)
    if not use_env:
        return config.base_threshold, env
    missing_raw_penalty = 0.35 if env["raw_raim_coverage"] < 0.5 else 0.0
    threshold = config.base_threshold * (1.0 + config.adaptive_gain * env["environment_degradation"] + missing_raw_penalty)
    return threshold, env


def classify_attack(components: dict[str, float], env: dict[str, float], detected: int) -> str:
    if not detected:
        if env["environment_degradation"] >= 0.45:
            return "degradation"
        return "normal"
    raw = components["score_raw"]
    lio = components["score_lio"]
    pr = components["score_pseudorange"]
    if raw >= max(lio, pr) * 1.15 and raw >= 0.9:
        return "raw_observation_outlier"
    if pr >= max(raw, lio) * 1.15 and pr >= 0.9:
        return "pseudorange_bias"
    if lio >= max(raw, pr) * 1.15 and lio >= 0.9:
        return "lio_gnss_inconsistency"
    if raw >= 0.65 and lio >= 0.65:
        return "coordinated_spoofing"
    return "multi_cue_anomaly"


def run_detector(rows: list[dict[str, str]], detector: str, config: DetectorConfig, scenario: str = "") -> DetectorOutput:
    out_rows: list[dict[str, str]] = []
    cusum = 0.0
    for idx, row in enumerate(rows):
        use_raw = detector != "adaptive_seq_no_raw"
        use_lio = detector != "adaptive_seq_no_lio"
        components = score_components(row, config, use_raw=use_raw, use_lio=use_lio)
        threshold, env = adaptive_threshold(row, config, use_env=detector != "adaptive_seq_no_env")

        if detector == "raim_only":
            score = components["score_raim"]
            threshold = 1.0
            detected = 1 if score >= threshold else 0
            increment = max(0.0, score - threshold)
            confidence = sigmoid((score - threshold) * config.confidence_slope)
            cusum = 0.0
        elif detector == "pseudorange_glrt_only":
            score = components["score_pseudorange"]
            threshold = 1.0
            detected = 1 if score >= threshold else 0
            increment = max(0.0, score - threshold)
            confidence = sigmoid((score - threshold) * config.confidence_slope)
            cusum = 0.0
        elif detector == "lio_residual_only":
            score = components["score_lio"]
            threshold = 1.0
            detected = 1 if score >= threshold else 0
            increment = max(0.0, score - threshold)
            confidence = sigmoid((score - threshold) * config.confidence_slope)
            cusum = 0.0
        elif detector == "fixed_fused":
            score = components["score_fused"]
            threshold = config.base_threshold
            detected = 1 if score >= threshold else 0
            increment = max(0.0, score - threshold)
            confidence = sigmoid((score - threshold) * config.confidence_slope)
            cusum = 0.0
        elif detector in {"adaptive_fused", "adaptive_seq_no_cusum"}:
            score = components["score_fused"]
            detected = 1 if score >= threshold else 0
            increment = max(0.0, score / max(1e-9, threshold) - 1.0)
            confidence = sigmoid((score / max(1e-9, threshold) - 1.0) * config.confidence_slope)
            cusum = 0.0
        elif detector.startswith("adaptive_seq"):
            score = components["score_fused"]
            normalized = score / max(1e-9, threshold)
            raw_increment = max(0.0, normalized - 0.72)
            env_relief = 0.35 * env["environment_degradation"] if detector != "adaptive_seq_no_env" else 0.0
            increment = max(0.0, raw_increment - config.cusum_drift - env_relief)
            if increment > 0.0:
                cusum = max(0.0, cusum + increment)
            else:
                cusum = max(0.0, cusum - config.reset_leak * (1.0 + env["environment_degradation"]))
            detected = 1 if cusum >= config.cusum_threshold else 0
            confidence = sigmoid((cusum / max(1e-9, config.cusum_threshold) - 0.72) * config.confidence_slope)
        else:
            raise ValueError(f"Unknown detector: {detector}")

        attack_type = classify_attack(components, env, detected)
        out_rows.append(
            {
                "scenario": scenario or row.get("scenario", ""),
                "detector": detector,
                "sample_index": str(idx),
                "stamp": row.get("stamp", ""),
                "time_s": row.get("time_s", str(idx)),
                "attack_label": "1" if to_float(row, "attack_label") >= 0.5 else "0",
                "attack_scale": f"{to_float(row, 'attack_scale'):.9f}",
                "detected": str(detected),
                "detector_score": f"{score:.9f}",
                "adaptive_threshold": f"{threshold:.9f}",
                "glrt_increment": f"{increment:.9f}",
                "cusum": f"{cusum:.9f}",
                "confidence": f"{confidence:.9f}",
                "attack_type": attack_type,
                "environment_degradation": f"{env['environment_degradation']:.9f}",
                "score_lio": f"{components['score_lio']:.9f}",
                "score_pseudorange": f"{components['score_pseudorange']:.9f}",
                "score_raw": f"{components['score_raw']:.9f}",
                "score_raim": f"{components['score_raim']:.9f}",
                "score_reference": f"{components['score_reference']:.9f}",
                "score_doppler": f"{components['score_doppler']:.9f}",
                "score_quality": f"{components['score_quality']:.9f}",
            }
        )
    metrics = evaluate_rows(out_rows)
    return DetectorOutput(detector=detector, rows=out_rows, metrics=metrics)


def run_detectors(rows: list[dict[str, str]], detectors: Iterable[str], config: DetectorConfig, scenario: str = "") -> list[DetectorOutput]:
    return [run_detector(rows, detector, config, scenario=scenario) for detector in detectors]


def write_long_csv(path: Path, outputs: list[DetectorOutput]) -> None:
    columns = [
        "scenario",
        "detector",
        "sample_index",
        "stamp",
        "time_s",
        "attack_label",
        "attack_scale",
        "detected",
        "detector_score",
        "adaptive_threshold",
        "glrt_increment",
        "cusum",
        "confidence",
        "attack_type",
        "environment_degradation",
        "score_lio",
        "score_pseudorange",
        "score_raw",
        "score_raim",
        "score_reference",
        "score_doppler",
        "score_quality",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for output in outputs:
            writer.writerows(output.rows)


def write_markdown(path: Path, metrics: dict[str, object], input_path: Path) -> None:
    lines = [
        "# Adaptive Sequential Detector Metrics",
        "",
        f"- Input: `{input_path}`",
        "",
        "| Detector | Precision | Recall | F1 | ROC AUC | False alarms/min | Latency mean (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for detector, item in metrics["detectors"].items():
        assert isinstance(item, dict)
        latency = item.get("detection_latency_s", {})
        latency_mean = latency.get("mean") if isinstance(latency, dict) else None
        auc = item.get("roc_auc")
        lines.append(
            f"| {detector} | {item['precision']:.3f} | {item['recall']:.3f} | "
            f"{item['f1']:.3f} | {auc:.3f} | {item['false_alarm_per_min']:.3f} | "
            f"{latency_mean:.3f} |"
            if isinstance(auc, float) and isinstance(latency_mean, float)
            else f"| {detector} | {item['precision']:.3f} | {item['recall']:.3f} | "
            f"{item['f1']:.3f} | n/a | {item['false_alarm_per_min']:.3f} | n/a |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def config_from_args(args: argparse.Namespace) -> DetectorConfig:
    return DetectorConfig(
        residual_scale_m=args.residual_scale_m,
        pr_rms_scale_m=args.pr_rms_scale_m,
        pr_abs_scale_m=args.pr_abs_scale_m,
        reference_residual_scale_m=args.reference_residual_scale_m,
        doppler_scale_mps=args.doppler_scale_mps,
        base_threshold=args.base_threshold,
        adaptive_gain=args.adaptive_gain,
        cusum_threshold=args.cusum_threshold,
        cusum_drift=args.cusum_drift,
        reset_leak=args.reset_leak,
    )


def parse_detector_list(value: str) -> list[str]:
    detectors = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in detectors if item not in DETECTORS]
    if unknown:
        raise SystemExit(f"Unknown detectors: {', '.join(unknown)}")
    return detectors


def main() -> int:
    args = parse_args()
    input_path = clean_path(args.input)
    assert input_path is not None
    rows = read_rows(input_path)
    if not rows:
        raise SystemExit(f"No rows found in {input_path}")

    config = config_from_args(args)
    outputs = run_detectors(rows, parse_detector_list(args.detectors), config, scenario=args.scenario)
    metrics = {
        "input": str(input_path),
        "scenario": args.scenario,
        "rows": len(rows),
        "detectors": {output.detector: output.metrics for output in outputs},
        "config": config.__dict__,
    }
    if args.output_csv:
        write_long_csv(clean_path(args.output_csv), outputs)
    if args.metrics_json:
        path = clean_path(args.metrics_json)
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if args.metrics_md:
        path = clean_path(args.metrics_md)
        assert path is not None
        write_markdown(path, metrics, input_path)

    best = max(outputs, key=lambda output: float(output.metrics["f1"]))
    print("Adaptive detector evaluation complete")
    print(f"  rows: {len(rows)}")
    print(f"  detectors: {len(outputs)}")
    print(f"  best F1: {best.detector} = {best.metrics['f1']:.3f}")
    if args.metrics_json:
        print(f"  metrics: {clean_path(args.metrics_json)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
