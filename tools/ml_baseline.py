#!/usr/bin/env python3
"""Dependency-light tree-ensemble baseline for observation-level spoofing detection."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable


FEATURE_COLUMNS = [
    "effective_residual_norm_m",
    "effective_maha",
    "effective_pr_rms_m",
    "effective_pr_abs_max_m",
    "raw_raim_score",
    "raw_reference_residual_rms_m",
    "raw_doppler_rms_mps",
    "dop_pdop",
    "dop_hdop",
    "rtk_ratio",
    "rtk_quality",
    "rtk_satellites",
    "rinex_satellite_count",
    "rinex_mean_cn0_dbhz",
    "rinex_low_cn0_satellite_count",
    "raw_healthy_pr_count",
    "raw_pr_outlier_reject_count",
    "raw_raim_used_satellite_count",
]


@dataclass
class TreeNode:
    probability: float
    feature_index: int = -1
    threshold: float = 0.0
    left: "TreeNode | None" = None
    right: "TreeNode | None" = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None or self.right is None or self.feature_index < 0


@dataclass
class TreeEnsembleModel:
    feature_columns: list[str]
    trees: list[TreeNode]
    threshold: float


def to_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value is None or value == "" or str(value).lower() == "nan":
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def extract_features(row: dict[str, str], feature_columns: list[str] = FEATURE_COLUMNS) -> list[float]:
    return [to_float(row, column) for column in feature_columns]


def label(row: dict[str, str]) -> int:
    return 1 if to_float(row, "attack_label") >= 0.5 else 0


def gini(labels: list[int]) -> float:
    if not labels:
        return 0.0
    p = sum(labels) / len(labels)
    return 1.0 - p * p - (1.0 - p) * (1.0 - p)


def candidate_thresholds(values: list[float]) -> list[float]:
    unique = sorted(set(values))
    if len(unique) <= 1:
        return []
    if len(unique) <= 10:
        return [(a + b) * 0.5 for a, b in zip(unique, unique[1:])]
    thresholds = []
    for q in (0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90):
        idx = min(len(unique) - 1, max(0, int(q * (len(unique) - 1))))
        thresholds.append(unique[idx])
    return sorted(set(thresholds))


def leaf_probability(labels: list[int]) -> float:
    # Laplace smoothing keeps pure leaves from becoming overconfident.
    return (sum(labels) + 1.0) / (len(labels) + 2.0) if labels else 0.5


def build_tree(
    x: list[list[float]],
    y: list[int],
    indices: list[int],
    rng: random.Random,
    max_depth: int,
    min_leaf: int,
    depth: int = 0,
) -> TreeNode:
    labels = [y[index] for index in indices]
    node = TreeNode(probability=leaf_probability(labels))
    if depth >= max_depth or len(indices) < 2 * min_leaf or gini(labels) <= 1e-9:
        return node

    feature_count = len(x[0]) if x else 0
    if feature_count <= 0:
        return node
    subset_size = max(1, int(math.sqrt(feature_count)))
    feature_indices = rng.sample(range(feature_count), k=min(feature_count, subset_size))
    parent_impurity = gini(labels)
    best_gain = 0.0
    best_feature = -1
    best_threshold = 0.0
    best_left: list[int] = []
    best_right: list[int] = []

    for feature_index in feature_indices:
        values = [x[index][feature_index] for index in indices]
        for threshold in candidate_thresholds(values):
            left = [index for index in indices if x[index][feature_index] <= threshold]
            right = [index for index in indices if x[index][feature_index] > threshold]
            if len(left) < min_leaf or len(right) < min_leaf:
                continue
            left_labels = [y[index] for index in left]
            right_labels = [y[index] for index in right]
            weighted = (len(left) * gini(left_labels) + len(right) * gini(right_labels)) / len(indices)
            gain = parent_impurity - weighted
            if gain > best_gain:
                best_gain = gain
                best_feature = feature_index
                best_threshold = threshold
                best_left = left
                best_right = right

    if best_feature < 0:
        return node
    node.feature_index = best_feature
    node.threshold = best_threshold
    node.left = build_tree(x, y, best_left, rng, max_depth, min_leaf, depth + 1)
    node.right = build_tree(x, y, best_right, rng, max_depth, min_leaf, depth + 1)
    return node


def balanced_bootstrap(y: list[int], rng: random.Random, sample_count: int) -> list[int]:
    positives = [idx for idx, value in enumerate(y) if value == 1]
    negatives = [idx for idx, value in enumerate(y) if value == 0]
    if not positives or not negatives:
        return [rng.randrange(len(y)) for _ in range(sample_count)]
    half = max(1, sample_count // 2)
    return [rng.choice(positives) for _ in range(half)] + [rng.choice(negatives) for _ in range(sample_count - half)]


def fit(
    rows: list[dict[str, str]],
    feature_columns: list[str] = FEATURE_COLUMNS,
    n_trees: int = 48,
    max_depth: int = 4,
    min_leaf: int = 8,
    sample_ratio: float = 0.85,
    seed: int = 20260701,
) -> TreeEnsembleModel:
    if not rows:
        raise ValueError("Cannot fit ML baseline without rows")
    x = [extract_features(row, feature_columns) for row in rows]
    y = [label(row) for row in rows]
    rng = random.Random(seed)
    sample_count = max(2, int(len(rows) * sample_ratio))
    trees = [
        build_tree(x, y, balanced_bootstrap(y, rng, sample_count), rng, max_depth=max_depth, min_leaf=min_leaf)
        for _ in range(n_trees)
    ]
    model = TreeEnsembleModel(feature_columns=feature_columns, trees=trees, threshold=0.5)
    model.threshold = calibrate_threshold(model, rows)
    return model


def predict_tree(node: TreeNode, features: list[float]) -> float:
    while not node.is_leaf:
        assert node.left is not None and node.right is not None
        node = node.left if features[node.feature_index] <= node.threshold else node.right
    return node.probability


def predict_proba(model: TreeEnsembleModel, row: dict[str, str]) -> float:
    features = extract_features(row, model.feature_columns)
    return sum(predict_tree(tree, features) for tree in model.trees) / max(1, len(model.trees))


def binary_counts(labels: list[int], detections: list[int]) -> dict[str, float | int]:
    tp = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 1)
    tn = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 0)
    fp = sum(1 for y, d in zip(labels, detections) if y == 0 and d == 1)
    fn = sum(1 for y, d in zip(labels, detections) if y == 1 and d == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def calibrate_threshold(model: TreeEnsembleModel, rows: list[dict[str, str]]) -> float:
    labels = [label(row) for row in rows]
    scores = [predict_proba(model, row) for row in rows]
    candidates = sorted(set(scores + [0.20, 0.35, 0.50, 0.65, 0.80]))
    best_threshold = 0.5
    best = (-1.0, -1.0, 0.0)
    for threshold in candidates:
        detections = [1 if score >= threshold else 0 for score in scores]
        metrics = binary_counts(labels, detections)
        # Prefer higher F1, then higher precision, then lower threshold for faster detection.
        rank = (float(metrics["f1"]), float(metrics["precision"]), -threshold)
        if rank > best:
            best = rank
            best_threshold = threshold
    return best_threshold


def detector_rows(
    model: TreeEnsembleModel,
    rows: Iterable[dict[str, str]],
    scenario: str = "",
    threshold: float | None = None,
) -> list[dict[str, str]]:
    threshold_value = model.threshold if threshold is None else threshold
    output = []
    for idx, row in enumerate(rows):
        score = predict_proba(model, row)
        output.append(
            {
                "scenario": scenario or row.get("scenario", ""),
                "detector": "ml_tree_ensemble",
                "sample_index": str(idx),
                "stamp": row.get("stamp", ""),
                "time_s": row.get("time_s", str(idx)),
                "attack_label": "1" if label(row) else "0",
                "attack_scale": f"{to_float(row, 'attack_scale'):.9f}",
                "detected": "1" if score >= threshold_value else "0",
                "detector_score": f"{score:.9f}",
                "adaptive_threshold": f"{threshold_value:.9f}",
                "glrt_increment": "0.000000000",
                "cusum": "0.000000000",
                "confidence": f"{score:.9f}",
                "attack_type": "ml_probability",
                "environment_degradation": "0.000000000",
                "score_lio": "0.000000000",
                "score_pseudorange": "0.000000000",
                "score_raw": "0.000000000",
                "score_raim": "0.000000000",
                "score_reference": "0.000000000",
                "score_doppler": "0.000000000",
                "score_quality": "0.000000000",
            }
        )
    return output
