#!/usr/bin/env python3
"""Evaluate binary GNSS spoof-detection outputs from a detection dataset CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate spoof-detection labels, detections, and scores.")
    parser.add_argument("input", help="Detection dataset CSV.")
    parser.add_argument("--label-column", default="attack_label")
    parser.add_argument("--det-column", default="detected")
    parser.add_argument("--score-column", default="spoof_score")
    parser.add_argument("--time-column", default="time_s")
    parser.add_argument("--output-json", help="JSON metrics path.")
    parser.add_argument("--output-md", help="Markdown report path.")
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, "")
        if value == "" or value.lower() == "nan":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(row: dict[str, str], key: str) -> int:
    return 1 if to_float(row, key) >= 0.5 else 0


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


def score_percentiles(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {}
    ordered = sorted(scores)

    def at(q: float) -> float:
        idx = int(round(q * (len(ordered) - 1)))
        return ordered[max(0, min(len(ordered) - 1, idx))]

    return {
        "min": ordered[0],
        "p50": at(0.50),
        "p75": at(0.75),
        "p90": at(0.90),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


def binary_metrics(labels: list[int], detections: list[int]) -> dict[str, float | int]:
    tp = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 1)
    tn = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 0)
    fp = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 1)
    fn = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
    }


def threshold_sweep(labels: list[int], scores: list[float]) -> dict[str, object]:
    if not scores:
        return {}
    candidate_thresholds = sorted(set([0.0, *scores, max(scores) + 1e-9]))
    has_pos = any(label == 1 for label in labels)
    has_neg = any(label == 0 for label in labels)
    if not (has_pos and has_neg):
        fixed = {}
        for threshold in [0.5, 1.0, 1.5, 2.0, 3.0]:
            detections = [1 if score >= threshold else 0 for score in scores]
            fixed[f"{threshold:.1f}"] = binary_metrics(labels, detections)
        return {
            "score_percentiles": score_percentiles(scores),
            "fixed_thresholds": fixed,
        }

    best_f1: dict[str, object] | None = None
    best_youden: dict[str, object] | None = None
    best_recall95: dict[str, object] | None = None
    for threshold in candidate_thresholds:
        detections = [1 if score >= threshold else 0 for score in scores]
        metrics = binary_metrics(labels, detections)
        item: dict[str, object] = {"threshold": threshold, **metrics}
        if best_f1 is None or float(item["f1"]) > float(best_f1["f1"]):
            best_f1 = item
        youden = float(item["recall"]) + float(item["specificity"]) - 1.0
        item_with_youden = {**item, "youden_j": youden}
        if best_youden is None or youden > float(best_youden["youden_j"]):
            best_youden = item_with_youden
        if float(item["recall"]) >= 0.95:
            if best_recall95 is None or int(item["false_positive"]) < int(best_recall95["false_positive"]):
                best_recall95 = item
    return {
        "score_percentiles": score_percentiles(scores),
        "best_f1": best_f1,
        "best_youden": best_youden,
        "best_recall_at_least_0_95": best_recall95,
    }


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


def median_dt(times: list[float]) -> float:
    if len(times) < 2:
        return 0.0
    deltas = sorted(max(0.0, b - a) for a, b in zip(times, times[1:]))
    return deltas[len(deltas) // 2]


def evaluate(rows: list[dict[str, str]], args: argparse.Namespace) -> dict[str, object]:
    labels = [to_int(row, args.label_column) for row in rows]
    detections = [to_int(row, args.det_column) for row in rows]
    scores = [to_float(row, args.score_column) for row in rows]
    times = [to_float(row, args.time_column, float(idx)) for idx, row in enumerate(rows)]

    base = binary_metrics(labels, detections)
    tp = int(base["true_positive"])
    fp = int(base["false_positive"])
    fn = int(base["false_negative"])

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
        **base,
        "roc_auc": auc,
        "false_alarm_per_min": false_alarm_per_min,
        "median_dt_s": dt,
        "threshold_sweep": threshold_sweep(labels, scores),
        "detection_latency_s": {
            "count": len(latencies),
            "mean": sum(latencies) / len(latencies) if latencies else None,
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
    }


def write_markdown(path: Path, metrics: dict[str, object], input_path: Path) -> None:
    latency = metrics["detection_latency_s"]
    assert isinstance(latency, dict)
    auc = metrics["roc_auc"]
    lines = [
        "# GNSS Spoof Detection Evaluation",
        "",
        f"- Input: `{input_path}`",
        f"- Rows: {metrics['rows']}",
        f"- Positive rows: {metrics['positive_rows']}",
        f"- Detected rows: {metrics['detected_rows']}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| True positive | {metrics['true_positive']} |",
        f"| False positive | {metrics['false_positive']} |",
        f"| True negative | {metrics['true_negative']} |",
        f"| False negative | {metrics['false_negative']} |",
        f"| Precision | {metrics['precision']:.6f} |",
        f"| Recall | {metrics['recall']:.6f} |",
        f"| Specificity | {metrics['specificity']:.6f} |",
        f"| F1 | {metrics['f1']:.6f} |",
        f"| ROC AUC | {auc:.6f} |" if isinstance(auc, float) else "| ROC AUC | n/a |",
        f"| False alarms / min | {metrics['false_alarm_per_min']:.6f} |",
        f"| Median dt (s) | {metrics['median_dt_s']:.6f} |",
    ]
    if latency["count"]:
        lines.extend(
            [
                f"| Detection latency mean (s) | {latency['mean']:.6f} |",
                f"| Detection latency min (s) | {latency['min']:.6f} |",
                f"| Detection latency max (s) | {latency['max']:.6f} |",
            ]
        )
    else:
        lines.append("| Detection latency | n/a |")

    sweep = metrics.get("threshold_sweep", {})
    if isinstance(sweep, dict) and sweep:
        lines.extend(["", "## Score Calibration", ""])
        percentiles = sweep.get("score_percentiles", {})
        if isinstance(percentiles, dict) and percentiles:
            lines.extend(["| Percentile | Score |", "| --- | ---: |"])
            for key in ["min", "p50", "p75", "p90", "p95", "p99", "max"]:
                if key in percentiles:
                    lines.append(f"| {key} | {percentiles[key]:.6f} |")
            lines.append("")
        for label, title in [
            ("best_f1", "Best F1"),
            ("best_youden", "Best Youden J"),
            ("best_recall_at_least_0_95", "Best Recall >= 0.95"),
        ]:
            item = sweep.get(label)
            if isinstance(item, dict):
                lines.append(
                    f"- {title}: threshold={item['threshold']:.6f}, "
                    f"precision={item['precision']:.6f}, recall={item['recall']:.6f}, "
                    f"F1={item['f1']:.6f}, FP={item['false_positive']}"
                )
        fixed = sweep.get("fixed_thresholds")
        if isinstance(fixed, dict):
            lines.extend(["", "| Fixed Threshold | FP | Detected |", "| --- | ---: | ---: |"])
            for threshold, item in fixed.items():
                if isinstance(item, dict):
                    detected = int(item["true_positive"]) + int(item["false_positive"])
                    lines.append(f"| {threshold} | {item['false_positive']} | {detected} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    rows = read_rows(input_path)
    if not rows:
        raise SystemExit(f"No rows found in {input_path}")
    metrics = evaluate(rows, args)

    output_json = Path(args.output_json).expanduser() if args.output_json else input_path.with_suffix(".metrics.json")
    output_md = Path(args.output_md).expanduser() if args.output_md else input_path.with_suffix(".metrics.md")
    if not output_json.is_absolute():
        output_json = PROJECT_ROOT / output_json
    if not output_md.is_absolute():
        output_md = PROJECT_ROOT / output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_markdown(output_md, metrics, input_path)

    print("Detection evaluation complete")
    print(f"  rows: {metrics['rows']}")
    print(f"  precision: {metrics['precision']:.3f}")
    print(f"  recall: {metrics['recall']:.3f}")
    print(f"  f1: {metrics['f1']:.3f}")
    print(f"  metrics: {output_json}")
    print(f"  report: {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
