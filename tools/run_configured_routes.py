#!/usr/bin/env python3
"""Run route-split experiments from datasets/routes.yaml without extra deps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run configured route-split GNSS spoofing experiments.")
    parser.add_argument("--config", default="datasets/routes.yaml")
    parser.add_argument("--output-dir", default="build/paper_platform/configured_route_experiments")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def clean_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def scalar(value: str) -> object:
    text = value.strip()
    if text == "":
        return ""
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if any(ch in text for ch in [".", "e", "E"]):
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_list_item(text: str) -> object:
    if ":" not in text:
        return scalar(text)
    key, value = text.split(":", 1)
    return {key.strip(): scalar(value)}


def parse_simple_yaml(path: Path) -> dict[str, object]:
    root: dict[str, object] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    section: str | None = None
    subsection: str | None = None
    current_item: dict[str, object] | None = None

    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if indent == 0 and text.endswith(":"):
            section = text[:-1]
            subsection = None
            current_item = None
            root[section] = [] if section == "routes" else {}
            continue
        if section is None:
            raise SystemExit(f"Invalid config line before section: {raw}")

        if section == "routes":
            routes = root.setdefault("routes", [])
            assert isinstance(routes, list)
            if indent == 2 and text.startswith("- "):
                parsed = parse_list_item(text[2:].strip())
                current_item = parsed if isinstance(parsed, dict) else {"name": parsed}
                routes.append(current_item)
                continue
            if indent >= 4 and current_item is not None and ":" in text:
                key, value = text.split(":", 1)
                current_item[key.strip()] = scalar(value)
                continue
            raise SystemExit(f"Unsupported routes config line: {raw}")

        section_obj = root.setdefault(section, {})
        assert isinstance(section_obj, dict)
        if indent == 2 and text.endswith(":"):
            subsection = text[:-1]
            section_obj[subsection] = []
            continue
        if indent == 2 and ":" in text:
            key, value = text.split(":", 1)
            section_obj[key.strip()] = scalar(value)
            subsection = None
            continue
        if indent == 4 and text.startswith("- ") and subsection:
            values = section_obj.setdefault(subsection, [])
            assert isinstance(values, list)
            values.append(scalar(text[2:].strip()))
            continue
        raise SystemExit(f"Unsupported config line: {raw}")
    return root


def as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def join_values(values: object) -> str:
    return ",".join(str(value) for value in as_list(values))


def validate_routes(config: dict[str, object]) -> list[dict[str, object]]:
    routes = config.get("routes", [])
    if not isinstance(routes, list) or not routes:
        raise SystemExit("Config must contain at least one route under `routes:`")
    output = []
    for item in routes:
        if not isinstance(item, dict):
            raise SystemExit(f"Route item must be a mapping: {item}")
        name = str(item.get("name", "")).strip()
        detection_csv = str(item.get("detection_csv", "")).strip()
        if not name or not detection_csv:
            raise SystemExit(f"Route must include name and detection_csv: {item}")
        path = clean_path(detection_csv)
        if not path.exists():
            raise SystemExit(f"Detection CSV for route `{name}` does not exist: {path}")
        output.append({**item, "name": name, "detection_csv_abs": str(path)})
    return output


def build_command(config: dict[str, object], routes: list[dict[str, object]], output_dir: Path) -> list[str]:
    splits = config.get("splits", {})
    experiment = config.get("experiment", {})
    if not isinstance(splits, dict):
        splits = {}
    if not isinstance(experiment, dict):
        experiment = {}

    train = join_values(splits.get("train", [routes[0]["name"]]))
    test = join_values(splits.get("test", [route["name"] for route in routes if route["name"] not in set(train.split(","))] or [routes[0]["name"]]))

    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "route_split_experiments.py"),
        "--train-routes",
        train,
        "--test-routes",
        test,
        "--output-dir",
        str(output_dir),
        "--strengths-m",
        join_values(experiment.get("strengths_m", [1, 2, 5, 10])),
        "--ramps-s",
        join_values(experiment.get("ramps_s", [1, 5, 20, 60])),
        "--attack-types",
        join_values(experiment.get("attack_types", ["position_bias", "coordinated_spoof"])),
        "--adaptive-gains",
        join_values(experiment.get("adaptive_gains", [0.75, 1.35, 2.0])),
        "--cusum-thresholds",
        join_values(experiment.get("cusum_thresholds", [0.35, 0.5, 0.75])),
        "--ml-max-train-rows",
        str(experiment.get("ml_max_train_rows", 12000)),
        "--ml-trees",
        str(experiment.get("ml_trees", 32)),
        "--ml-depth",
        str(experiment.get("ml_depth", 4)),
    ]
    for route in routes:
        command.extend(["--route", f"{route['name']}={route['detection_csv_abs']}"])
    return command


def write_manifest(output_dir: Path, config_path: Path, config: dict[str, object], command: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "config": str(config_path),
        "command": command,
        "config_content": config,
    }
    (output_dir / "configured_routes_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = clean_path(args.config)
    output_dir = clean_path(args.output_dir)
    config = parse_simple_yaml(config_path)
    routes = validate_routes(config)
    command = build_command(config, routes, output_dir)
    write_manifest(output_dir, config_path, config, command)
    print("Configured route experiment command:")
    print(" ".join(command))
    if args.dry_run:
        return 0
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
