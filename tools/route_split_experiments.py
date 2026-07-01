#!/usr/bin/env python3
"""Route-held-out experiment runner for EA-SGLRT and optional ML baselines."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import sys

import adaptive_sequential_detector as detector
import ml_baseline
import run_experiment_matrix as matrix


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run train-route tuning and test-route evaluation for GNSS spoofing detection.")
    parser.add_argument(
        "--route",
        action="append",
        default=[],
        help="Route spec as name=/path/to/*_detection.csv. May be repeated.",
    )
    parser.add_argument(
        "--route-dir",
        action="append",
        default=[],
        help="Directory containing a *_detection.csv file. Route name is the directory name.",
    )
    parser.add_argument("--train-routes", default="", help="Comma-separated train route names. Default: first route.")
    parser.add_argument("--test-routes", default="", help="Comma-separated test route names. Default: routes not in train, or train routes if only one route exists.")
    parser.add_argument("--output-dir", default="build/paper_platform/route_split_experiments")
    parser.add_argument("--strengths-m", default="1,2,5,10")
    parser.add_argument("--ramps-s", default="1,5,20,60")
    parser.add_argument("--attack-types", default=",".join(matrix.ATTACK_TYPES))
    parser.add_argument("--attack-window", default="+20:+260")
    parser.add_argument("--adaptive-gains", default="0.75,1.35,2.0")
    parser.add_argument("--cusum-thresholds", default="0.35,0.5,0.75,1.0")
    parser.add_argument("--include-ml-baseline", action="store_true", default=True)
    parser.add_argument("--ml-max-train-rows", type=int, default=12000)
    parser.add_argument("--ml-trees", type=int, default=32)
    parser.add_argument("--ml-depth", type=int, default=4)
    return parser.parse_args()


def clean_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


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


def route_csv_from_dir(path: Path) -> Path:
    candidates = sorted(path.glob("*_detection.csv"))
    if not candidates:
        raise SystemExit(f"No *_detection.csv found in route dir: {path}")
    return candidates[0]


def parse_routes(args: argparse.Namespace) -> dict[str, Path]:
    routes: dict[str, Path] = {}
    for spec in args.route:
        if "=" not in spec:
            raise SystemExit("--route must be name=/path/to/detection.csv")
        name, value = spec.split("=", 1)
        routes[name.strip()] = clean_path(value.strip())
    for value in args.route_dir:
        directory = clean_path(value)
        routes[directory.name] = route_csv_from_dir(directory)
    if not routes:
        default_csv = clean_path("build/paper_platform/full_data_clean/full_data_clean_detection.csv")
        if default_csv.exists():
            routes["full_data"] = default_csv
    if not routes:
        raise SystemExit("Provide at least one --route or --route-dir, or build the default paper dataset first.")
    missing = [str(path) for path in routes.values() if not path.exists()]
    if missing:
        raise SystemExit(f"Missing route CSV(s): {', '.join(missing)}")
    return routes


def parse_name_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def choose_splits(route_names: list[str], args: argparse.Namespace) -> tuple[list[str], list[str]]:
    train = parse_name_list(args.train_routes)
    test = parse_name_list(args.test_routes)
    if not train:
        train = [route_names[0]]
    if not test:
        test = [name for name in route_names if name not in train]
        if not test:
            test = train[:]
    unknown = sorted((set(train) | set(test)) - set(route_names))
    if unknown:
        raise SystemExit(f"Unknown route(s) in split: {', '.join(unknown)}")
    return train, test


def route_scenarios(
    route_name: str,
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
        meta = {**meta, "route": route_name, "route_scenario": f"{route_name}:{meta['scenario']}"}
        scenarios.append((meta, rows))
    for attack_type in attack_types:
        for strength in strengths:
            for ramp in ramps:
                rows = matrix.attack_rows(base_rows, attack_type, strength, ramp, window)
                meta = matrix.scenario_metadata(rows[0]["scenario"], "synthetic_spoofing", rows, attack_type, strength, ramp)
                meta = {**meta, "route": route_name, "route_scenario": f"{route_name}:{meta['scenario']}"}
                scenarios.append((meta, rows))
    return scenarios


def build_all_scenarios(
    route_rows: dict[str, list[dict[str, str]]],
    args: argparse.Namespace,
) -> dict[str, list[tuple[dict[str, object], list[dict[str, str]]]]]:
    strengths = matrix.parse_list_float(args.strengths_m)
    ramps = matrix.parse_list_float(args.ramps_s)
    attack_types = matrix.parse_list_str(args.attack_types)
    window = matrix.parse_window(args.attack_window)
    return {
        name: route_scenarios(name, rows, strengths, ramps, attack_types, window)
        for name, rows in route_rows.items()
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def tune_config(
    scenarios_by_route: dict[str, list[tuple[dict[str, object], list[dict[str, str]]]]],
    train_routes: list[str],
    args: argparse.Namespace,
) -> tuple[detector.DetectorConfig, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    best_rank = (-1.0, -1.0)
    best_config = detector.DetectorConfig()
    for gain in matrix.parse_list_float(args.adaptive_gains):
        for cusum_threshold in matrix.parse_list_float(args.cusum_thresholds):
            config = detector.DetectorConfig(adaptive_gain=gain, cusum_threshold=cusum_threshold)
            metric_rows = []
            for route in train_routes:
                for meta, scenario_rows in scenarios_by_route[route]:
                    output = detector.run_detector(scenario_rows, "adaptive_seq_full", config, scenario=str(meta["route_scenario"]))
                    metric_rows.append(matrix.metric_row(meta, output))
            attack_items = [row for row in metric_rows if row["scenario_type"] == "synthetic_spoofing"]
            non_attack = [row for row in metric_rows if row["scenario_type"] != "synthetic_spoofing"]
            attack_f1 = mean([float(row["f1"]) for row in attack_items])
            false_alarm = mean([float(row["false_alarm_per_min"]) for row in non_attack])
            latency_values = [float(row["latency_mean_s"]) for row in attack_items if row["latency_mean_s"] != ""]
            item = {
                "adaptive_gain": gain,
                "cusum_threshold": cusum_threshold,
                "train_attack_f1_mean": attack_f1,
                "train_false_alarm_per_min": false_alarm,
                "train_latency_mean_s": mean(latency_values),
                "objective": attack_f1 - 0.02 * false_alarm,
            }
            rows.append(item)
            rank = (float(item["objective"]), attack_f1)
            if rank > best_rank:
                best_rank = rank
                best_config = config
    for row in rows:
        row["is_selected_config"] = int(
            abs(float(row["adaptive_gain"]) - best_config.adaptive_gain) < 1e-9
            and abs(float(row["cusum_threshold"]) - best_config.cusum_threshold) < 1e-9
        )
    rows.sort(key=lambda row: (float(row["objective"]), float(row["train_attack_f1_mean"])), reverse=True)
    return best_config, rows


def sample_ml_rows(rows: list[dict[str, str]], max_rows: int, seed: int = 20260701) -> list[dict[str, str]]:
    if max_rows <= 0 or len(rows) <= max_rows:
        return rows
    positives = [row for row in rows if ml_baseline.label(row) == 1]
    negatives = [row for row in rows if ml_baseline.label(row) == 0]
    rng = random.Random(seed)
    half = max_rows // 2
    sampled = []
    sampled.extend(rng.sample(positives, min(len(positives), half)))
    sampled.extend(rng.sample(negatives, min(len(negatives), max_rows - len(sampled))))
    remaining = max_rows - len(sampled)
    if remaining > 0:
        pool = [row for row in rows if row not in sampled]
        sampled.extend(rng.sample(pool, min(len(pool), remaining)))
    rng.shuffle(sampled)
    return sampled


def train_ml(
    scenarios_by_route: dict[str, list[tuple[dict[str, object], list[dict[str, str]]]]],
    train_routes: list[str],
    args: argparse.Namespace,
) -> ml_baseline.TreeEnsembleModel | None:
    if not args.include_ml_baseline:
        return None
    rows: list[dict[str, str]] = []
    for route in train_routes:
        for _meta, scenario_rows in scenarios_by_route[route]:
            rows.extend(scenario_rows)
    train_rows = sample_ml_rows(rows, args.ml_max_train_rows)
    if not any(ml_baseline.label(row) for row in train_rows):
        return None
    return ml_baseline.fit(train_rows, n_trees=args.ml_trees, max_depth=args.ml_depth)


def evaluate_split(
    scenarios_by_route: dict[str, list[tuple[dict[str, object], list[dict[str, str]]]]],
    routes: list[str],
    config: detector.DetectorConfig,
    ml_model: ml_baseline.TreeEnsembleModel | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    detectors = [
        "raim_only",
        "pseudorange_glrt_only",
        "lio_residual_only",
        "fixed_fused",
        "adaptive_fused",
        "adaptive_seq_full",
    ]
    for route in routes:
        for meta, scenario_rows in scenarios_by_route[route]:
            outputs = detector.run_detectors(scenario_rows, detectors, config, scenario=str(meta["route_scenario"]))
            for output in outputs:
                rows.append(matrix.metric_row(meta, output))
            if ml_model is not None:
                ml_rows = ml_baseline.detector_rows(ml_model, scenario_rows, scenario=str(meta["route_scenario"]))
                rows.append(matrix.metric_row(meta, detector.DetectorOutput("ml_tree_ensemble", ml_rows, detector.evaluate_rows(ml_rows))))
    return rows


def aggregate(rows: list[dict[str, object]], split_name: str) -> list[dict[str, object]]:
    output = []
    for detector_name in sorted({str(row["detector"]) for row in rows}):
        items = [row for row in rows if row["detector"] == detector_name]
        attacks = [row for row in items if row["scenario_type"] == "synthetic_spoofing"]
        non_attack = [row for row in items if row["scenario_type"] != "synthetic_spoofing"]
        output.append(
            {
                "split": split_name,
                "detector": detector_name,
                "route_count": len({row["route"] for row in items}),
                "scenario_count": len(items),
                "attack_scenario_count": len(attacks),
                "attack_precision_mean": mean([float(row["precision"]) for row in attacks]),
                "attack_recall_mean": mean([float(row["recall"]) for row in attacks]),
                "attack_f1_mean": mean([float(row["f1"]) for row in attacks]),
                "false_alarm_per_min_mean": mean([float(row["false_alarm_per_min"]) for row in non_attack]),
                "latency_mean_s": mean([float(row["latency_mean_s"]) for row in attacks if row["latency_mean_s"] != ""]),
            }
        )
    output.sort(key=lambda row: (row["split"], float(row["attack_f1_mean"])), reverse=True)
    return output


def write_markdown(path: Path, summary_rows: list[dict[str, object]], selected: detector.DetectorConfig, train_routes: list[str], test_routes: list[str]) -> None:
    lines = [
        "# Route Split Experiments",
        "",
        f"- Train routes: {', '.join(train_routes)}",
        f"- Test routes: {', '.join(test_routes)}",
        f"- Selected adaptive_gain: {selected.adaptive_gain:.3f}",
        f"- Selected cusum_threshold: {selected.cusum_threshold:.3f}",
        "",
        "| Split | Detector | Attack F1 | Precision | Recall | FA/min | Latency (s) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['split']} | {row['detector']} | {float(row['attack_f1_mean']):.3f} | "
            f"{float(row['attack_precision_mean']):.3f} | {float(row['attack_recall_mean']):.3f} | "
            f"{float(row['false_alarm_per_min_mean']):.3f} | {float(row['latency_mean_s']):.3f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    route_paths = parse_routes(args)
    route_rows = {name: read_csv(path) for name, path in route_paths.items()}
    route_names = sorted(route_rows)
    train_routes, test_routes = choose_splits(route_names, args)
    output_dir = clean_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios_by_route = build_all_scenarios(route_rows, args)
    selected_config, tuning_rows = tune_config(scenarios_by_route, train_routes, args)
    ml_model = train_ml(scenarios_by_route, train_routes, args)
    train_results = evaluate_split(scenarios_by_route, train_routes, selected_config, ml_model)
    test_results = evaluate_split(scenarios_by_route, test_routes, selected_config, ml_model)
    train_summary = aggregate(train_results, "train")
    test_summary = aggregate(test_results, "test")
    summary_rows = train_summary + test_summary

    result_columns = [
        "route",
        "route_scenario",
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
        "route_count",
        "scenario_count",
        "attack_scenario_count",
        "attack_precision_mean",
        "attack_recall_mean",
        "attack_f1_mean",
        "false_alarm_per_min_mean",
        "latency_mean_s",
    ]
    tuning_columns = [
        "adaptive_gain",
        "cusum_threshold",
        "train_attack_f1_mean",
        "train_false_alarm_per_min",
        "train_latency_mean_s",
        "objective",
        "is_selected_config",
    ]
    write_csv(output_dir / "train_results.csv", result_columns, train_results)
    write_csv(output_dir / "test_results.csv", result_columns, test_results)
    write_csv(output_dir / "detector_summary.csv", summary_columns, summary_rows)
    write_csv(output_dir / "tuning_summary.csv", tuning_columns, tuning_rows)
    payload = {
        "routes": {name: str(path) for name, path in route_paths.items()},
        "train_routes": train_routes,
        "test_routes": test_routes,
        "selected_config": selected_config.__dict__,
        "ml_baseline": {
            "enabled": ml_model is not None,
            "feature_columns": ml_model.feature_columns if ml_model is not None else [],
            "threshold": ml_model.threshold if ml_model is not None else None,
            "tree_count": len(ml_model.trees) if ml_model is not None else 0,
        },
        "outputs": {
            "train_results_csv": str(output_dir / "train_results.csv"),
            "test_results_csv": str(output_dir / "test_results.csv"),
            "detector_summary_csv": str(output_dir / "detector_summary.csv"),
            "tuning_summary_csv": str(output_dir / "tuning_summary.csv"),
        },
    }
    write_json(output_dir / "route_split_summary.json", payload)
    write_markdown(output_dir / "route_split_summary.md", summary_rows, selected_config, train_routes, test_routes)

    print("Route split experiments complete")
    print(f"  routes: {len(route_names)}")
    print(f"  train routes: {', '.join(train_routes)}")
    print(f"  test routes: {', '.join(test_routes)}")
    print(f"  selected adaptive_gain={selected_config.adaptive_gain:.3f}, cusum_threshold={selected_config.cusum_threshold:.3f}")
    print(f"  output: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    raise SystemExit(main())
