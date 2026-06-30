#!/usr/bin/env python3
"""Inject reproducible observation-level pseudorange attacks into satellite CSVs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AttackWindow:
    start_s: float
    end_s: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject controlled pseudorange biases into per-satellite RINEX feature CSVs.")
    parser.add_argument("--satellite-features", required=True, help="CSV from tools/extract_rinex_features.py.")
    parser.add_argument("--name", default="attacked_observations")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "build" / "paper_platform" / "observation_attack"))
    parser.add_argument("--relative-origin-csv", help="CSV whose first stamp defines +relative attack-window time.")
    parser.add_argument("--relative-origin-stamp", type=float, default=None, help="Explicit Unix stamp used for +relative attack-window time.")
    parser.add_argument("--attack-window", action="append", default=[], help="Window start:end or +start:+end.")
    parser.add_argument("--attack-ramp-s", type=float, default=2.0)
    parser.add_argument("--common-delay-m", type=float, default=0.0, help="Bias applied to attacked satellites.")
    parser.add_argument("--per-satellite-bias-m", type=float, default=0.0, help="Additional deterministic PRN-dependent bias.")
    parser.add_argument("--drift-rate-mps", type=float, default=0.0, help="Bias drift after attack ramp start.")
    parser.add_argument("--satellite-mode", choices=["all", "alternating", "list"], default="all")
    parser.add_argument("--satellites", default="", help="Comma-separated satellite IDs for --satellite-mode=list.")
    parser.add_argument("--systems", default="G", help="Comma-separated systems to attack. Empty means all systems.")
    return parser.parse_args()


def clean_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "" or value.lower() == "nan":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def fmt(value: float | int | str | None, precision: int = 9) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        return ""
    return f"{value:.{precision}f}"


def parse_windows(values: list[str]) -> list[AttackWindow]:
    windows: list[AttackWindow] = []
    for value in values:
        if ":" not in value:
            raise SystemExit("--attack-window must be start:end")
        left, right = value.split(":", 1)
        start = float(left.lstrip("+")) if left.startswith("+") else float(left)
        end = float(right.lstrip("+")) if right.startswith("+") else float(right)
        if end <= start:
            raise SystemExit("--attack-window end must be greater than start")
        windows.append(AttackWindow(start, end))
    return windows


def window_scale(stamp: float, relative_t: float, windows: list[AttackWindow], ramp_s: float) -> tuple[float, float]:
    best_scale = 0.0
    best_attack_t = 0.0
    for window in windows:
        is_relative = window.start_s < 1.0e8 and window.end_s < 1.0e8
        t = relative_t if is_relative else stamp
        if t < window.start_s or t > window.end_s:
            continue
        scale = 1.0
        if ramp_s > 1e-9:
            scale = min(scale, max(0.0, (t - window.start_s) / ramp_s))
            scale = min(scale, max(0.0, (window.end_s - t) / ramp_s))
        if scale > best_scale:
            best_scale = scale
            best_attack_t = max(0.0, t - window.start_s)
    return best_scale, best_attack_t


def should_attack_satellite(sat_id: str, system: str, mode: str, satellites: set[str], systems: set[str]) -> bool:
    if systems and system not in systems:
        return False
    if mode == "all":
        return True
    if mode == "list":
        return sat_id in satellites
    try:
        prn = int(sat_id[1:])
    except ValueError:
        return False
    return prn % 2 == 0


def prn_sign(sat_id: str) -> float:
    try:
        prn = int(sat_id[1:])
    except ValueError:
        return 1.0
    return 1.0 if prn % 4 in (0, 1) else -1.0


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def first_csv_stamp(path: Path) -> float:
    with path.open(newline="", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            if row.get("stamp"):
                return parse_float(row["stamp"])
    raise SystemExit(f"No stamp column rows found in {path}")


def main() -> int:
    args = parse_args()
    input_path = clean_path(args.satellite_features)
    output_dir = clean_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / f"{args.name}_satellite_features.csv"
    summary_json = output_dir / f"{args.name}_attack_summary.json"

    rows, fieldnames = read_rows(input_path)
    if not rows:
        raise SystemExit(f"No rows found in {input_path}")
    windows = parse_windows(args.attack_window)
    first_stamp = min(parse_float(row.get("stamp")) for row in rows)
    relative_origin_stamp = first_stamp
    if args.relative_origin_stamp is not None:
        relative_origin_stamp = args.relative_origin_stamp
    elif args.relative_origin_csv:
        relative_origin_stamp = first_csv_stamp(clean_path(args.relative_origin_csv))
    systems = {item.strip() for item in args.systems.split(",") if item.strip()}
    satellites = {item.strip() for item in args.satellites.split(",") if item.strip()}

    extra_fields = [
        "clean_primary_code_m",
        "attack_label",
        "attack_scale",
        "injected_pseudorange_bias_m",
        "attack_common_delay_m",
        "attack_per_satellite_bias_m",
        "attack_drift_m",
    ]
    output_fields = fieldnames[:]
    for field in extra_fields:
        if field not in output_fields:
            output_fields.append(field)

    attacked_rows = 0
    attacked_epochs: set[str] = set()
    max_bias = 0.0
    with output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            stamp = parse_float(row.get("stamp"))
            relative_t = stamp - relative_origin_stamp
            scale, attack_t = window_scale(stamp, relative_t, windows, args.attack_ramp_s)
            sat_id = row.get("sat_id", "")
            system = row.get("system", sat_id[:1])
            clean_code = parse_float(row.get("primary_code_m"), default=float("nan"))
            can_attack = (
                scale > 0.0
                and not math.isnan(clean_code)
                and should_attack_satellite(sat_id, system, args.satellite_mode, satellites, systems)
            )
            common = args.common_delay_m if can_attack else 0.0
            per_satellite = args.per_satellite_bias_m * prn_sign(sat_id) if can_attack else 0.0
            drift = args.drift_rate_mps * attack_t if can_attack else 0.0
            bias = scale * (common + per_satellite + drift)
            if can_attack:
                attacked_rows += 1
                attacked_epochs.add(row.get("epoch_index", ""))
                max_bias = max(max_bias, abs(bias))
                row["primary_code_m"] = fmt(clean_code + bias)
            row["clean_primary_code_m"] = fmt(clean_code)
            row["attack_label"] = "1" if can_attack and abs(bias) > 1e-9 else "0"
            row["attack_scale"] = fmt(scale if can_attack else 0.0)
            row["injected_pseudorange_bias_m"] = fmt(bias)
            row["attack_common_delay_m"] = fmt(scale * common)
            row["attack_per_satellite_bias_m"] = fmt(scale * per_satellite)
            row["attack_drift_m"] = fmt(scale * drift)
            writer.writerow({field: row.get(field, "") for field in output_fields})

    summary = {
        "input": str(input_path),
        "output": str(output_csv),
        "rows": len(rows),
        "attacked_rows": attacked_rows,
        "attacked_epochs": len(attacked_epochs),
        "max_abs_bias_m": max_bias,
        "windows": [window.__dict__ for window in windows],
        "relative_origin_stamp": relative_origin_stamp,
        "common_delay_m": args.common_delay_m,
        "per_satellite_bias_m": args.per_satellite_bias_m,
        "drift_rate_mps": args.drift_rate_mps,
        "satellite_mode": args.satellite_mode,
        "systems": sorted(systems),
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("Observation-level attack injected")
    print(f"  rows: {len(rows)}")
    print(f"  attacked rows: {attacked_rows}")
    print(f"  output: {output_csv}")
    print(f"  summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
