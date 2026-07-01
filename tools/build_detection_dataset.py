#!/usr/bin/env python3
"""Build a time-aligned GNSS spoof-detection dataset from RTKLIB and FAST_GLIO logs."""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Iterable


WGS84_A_M = 6378137.0
WGS84_E2 = 6.69437999014e-3
GPS_EPOCH_UNIX_S = 315964800.0
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class IndexedRows:
    rows: list[dict[str, str]]
    stamps: list[float]


@dataclass
class AttackWindow:
    start_s: float
    end_s: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge RTKLIB, FAST_GLIO loose/raw/tight logs into a paper-ready detection CSV.",
    )
    parser.add_argument("--rtklib-pos", help="Optional RTKLIB .pos file.")
    parser.add_argument("--dop", help="Optional RTKLIB dop.txt file.")
    parser.add_argument("--loose", help="FAST_GLIO Log/gnss_loose_diag.csv.")
    parser.add_argument("--raw", help="FAST_GLIO Log/gnss_raw_update_log.csv.")
    parser.add_argument("--tight", help="FAST_GLIO Log/gnss_tight_pose.csv.")
    parser.add_argument("--rinex-summary", help="Optional epoch summary CSV from tools/extract_rinex_features.py.")
    parser.add_argument("--raw-residual-summary", help="Optional raw GPS residual/RAIM epoch CSV from tools/compute_raw_gnss_residuals.py.")
    parser.add_argument("--name", default="paper_dataset", help="Output prefix.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "build" / "paper_platform"),
        help="Directory for generated dataset/report files.",
    )
    parser.add_argument(
        "--gps-utc-leap-seconds",
        type=float,
        default=18.0,
        help="GPST-UTC offset used to convert GPS week/TOW and DOP timestamps to Unix time.",
    )
    parser.add_argument("--origin", choices=["first", "first-fixed"], default="first-fixed")
    parser.add_argument("--max-delta-s", type=float, default=0.65, help="Nearest-neighbor log sync tolerance.")
    parser.add_argument(
        "--base-timeline",
        choices=["auto", "loose", "raw", "tight", "rtk", "dop", "rinex", "raw-residual"],
        default="auto",
        help=(
            "Timeline used for output rows. 'auto' preserves the historical order "
            "loose/raw/tight/rtk; choose 'rtk' for full RTKLIB-route visualization."
        ),
    )
    parser.add_argument(
        "--max-loose-residual-m",
        type=float,
        default=1000.0,
        help="Drop matched FAST_GLIO loose rows with residual components/norm above this magnitude.",
    )
    parser.add_argument(
        "--max-loose-maha",
        type=float,
        default=1.0e6,
        help="Drop matched FAST_GLIO loose rows with Mahalanobis distance above this value.",
    )
    parser.add_argument(
        "--disable-loose-sanity-filter",
        action="store_true",
        help="Keep all matched FAST_GLIO loose rows, including non-finite or obviously overflowed values.",
    )
    parser.add_argument(
        "--attack-window",
        action="append",
        default=[],
        help="Synthetic attack window. Use Unix seconds start:end or relative seconds +start:+end.",
    )
    parser.add_argument("--attack-offset", default="6.0,0.0,0.0", help="Synthetic residual offset x,y,z in meters.")
    parser.add_argument("--pseudorange-delay", type=float, default=12.0, help="Synthetic pseudorange delay in meters.")
    parser.add_argument("--attack-ramp", type=float, default=2.0, help="Ramp duration for synthetic attacks.")
    parser.add_argument("--threshold", type=float, default=1.0, help="Spoof score threshold.")
    parser.add_argument("--consecutive", type=int, default=2, help="Consecutive triggered samples required.")
    parser.add_argument("--residual-scale", type=float, default=6.0, help="Meters mapped to residual score 1.")
    parser.add_argument("--pr-rms-scale", type=float, default=12.0, help="Meters mapped to pseudorange RMS score 1.")
    parser.add_argument("--pr-abs-scale", type=float, default=24.0, help="Meters mapped to pseudorange max score 1.")
    parser.add_argument("--doppler-scale", type=float, default=0.35, help="m/s mapped to Doppler score 1.")
    parser.add_argument("--raim-scale", type=float, default=1.0, help="RAIM chi-square/threshold score mapped to 1.")
    parser.add_argument("--reference-residual-scale", type=float, default=18.0, help="Meters mapped to raw reference residual score 1.")
    return parser.parse_args()


def clean_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_float(row: dict[str, str] | None, key: str, default: float = 0.0) -> float:
    if row is None:
        return default
    value = row.get(key, "")
    if value is None or value == "" or value.lower() == "nan":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def parse_int(row: dict[str, str] | None, key: str, default: int = 0) -> int:
    return int(round(parse_float(row, key, float(default))))


def parse_boolish(row: dict[str, str] | None, key: str, default: int = 0) -> int:
    if row is None:
        return default
    value = row.get(key, "")
    if value in ("1", "true", "True", "yes", "accepted", "accepted_pr_only", "accepted_with_doppler"):
        return 1
    if value in ("0", "false", "False", "no", "wait_alignment", "rejected"):
        return 0
    return default


def read_indexed_csv(path: Path | None, stamp_column: str = "stamp") -> IndexedRows:
    if path is None or not path.exists():
        return IndexedRows([], [])
    rows: list[dict[str, str]] = []
    with path.open(newline="", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            try:
                stamp = float(row[stamp_column])
            except (KeyError, TypeError, ValueError):
                continue
            row["_stamp"] = f"{stamp:.9f}"
            rows.append(row)
    rows.sort(key=lambda item: float(item["_stamp"]))
    return IndexedRows(rows, [float(row["_stamp"]) for row in rows])


def nearest(indexed: IndexedRows, stamp: float, max_delta_s: float) -> dict[str, str] | None:
    if not indexed.rows:
        return None
    pos = bisect.bisect_left(indexed.stamps, stamp)
    candidates = []
    if pos < len(indexed.stamps):
        candidates.append(pos)
    if pos > 0:
        candidates.append(pos - 1)
    best = min(candidates, key=lambda idx: abs(indexed.stamps[idx] - stamp))
    if abs(indexed.stamps[best] - stamp) <= max_delta_s:
        return indexed.rows[best]
    return None


def gps_week_tow_to_unix(week: int, tow_s: float, leap_seconds: float) -> float:
    return GPS_EPOCH_UNIX_S + week * 604800.0 + tow_s - leap_seconds


def ecef_to_geodetic(x_m: float, y_m: float, z_m: float) -> tuple[float, float, float]:
    lon = math.atan2(y_m, x_m)
    p = math.hypot(x_m, y_m)
    lat = math.atan2(z_m, p * (1.0 - WGS84_E2))
    h = 0.0
    for _ in range(10):
        sin_lat = math.sin(lat)
        n = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        h = p / max(math.cos(lat), 1e-12) - n
        lat = math.atan2(z_m, p * (1.0 - WGS84_E2 * n / (n + h)))
    return lat, lon, h


def ecef_to_enu(
    x_m: float,
    y_m: float,
    z_m: float,
    origin_ecef: tuple[float, float, float],
    origin_llh: tuple[float, float, float],
) -> tuple[float, float, float]:
    x0, y0, z0 = origin_ecef
    lat, lon, _ = origin_llh
    dx = x_m - x0
    dy = y_m - y0
    dz = z_m - z0
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    return east, north, up


def read_rtklib_pos(path: Path | None, leap_seconds: float, origin_mode: str) -> tuple[IndexedRows, dict[str, float]]:
    if path is None or not path.exists():
        return IndexedRows([], []), {}
    raw_rows: list[dict[str, float]] = []
    with path.open(errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            fields = line.split()
            if len(fields) < 15:
                continue
            try:
                week = int(fields[0])
                tow_s = float(fields[1])
                raw_rows.append(
                    {
                        "stamp": gps_week_tow_to_unix(week, tow_s, leap_seconds),
                        "gps_week": float(week),
                        "tow_s": tow_s,
                        "ecef_x_m": float(fields[2]),
                        "ecef_y_m": float(fields[3]),
                        "ecef_z_m": float(fields[4]),
                        "quality": float(fields[5]),
                        "satellites": float(fields[6]),
                        "sdx_m": float(fields[7]),
                        "sdy_m": float(fields[8]),
                        "sdz_m": float(fields[9]),
                        "ratio": float(fields[14]),
                    }
                )
            except ValueError:
                continue
    if not raw_rows:
        return IndexedRows([], []), {}

    origin = raw_rows[0]
    if origin_mode == "first-fixed":
        origin = next((row for row in raw_rows if int(row["quality"]) == 1), raw_rows[0])
    origin_ecef = (origin["ecef_x_m"], origin["ecef_y_m"], origin["ecef_z_m"])
    origin_llh = ecef_to_geodetic(*origin_ecef)

    rows: list[dict[str, str]] = []
    for item in raw_rows:
        east, north, up = ecef_to_enu(item["ecef_x_m"], item["ecef_y_m"], item["ecef_z_m"], origin_ecef, origin_llh)
        rows.append(
            {
                "_stamp": f"{item['stamp']:.9f}",
                "stamp": f"{item['stamp']:.9f}",
                "rtk_gps_week": f"{item['gps_week']:.0f}",
                "rtk_tow_s": f"{item['tow_s']:.3f}",
                "rtk_enu_e_m": f"{east:.6f}",
                "rtk_enu_n_m": f"{north:.6f}",
                "rtk_enu_u_m": f"{up:.6f}",
                "rtk_quality": f"{item['quality']:.0f}",
                "rtk_satellites": f"{item['satellites']:.0f}",
                "rtk_ratio": f"{item['ratio']:.6f}",
                "rtk_sdx_m": f"{item['sdx_m']:.6f}",
                "rtk_sdy_m": f"{item['sdy_m']:.6f}",
                "rtk_sdz_m": f"{item['sdz_m']:.6f}",
            }
        )

    origin_summary = {
        "origin_ecef_x_m": origin_ecef[0],
        "origin_ecef_y_m": origin_ecef[1],
        "origin_ecef_z_m": origin_ecef[2],
        "origin_lat_deg": math.degrees(origin_llh[0]),
        "origin_lon_deg": math.degrees(origin_llh[1]),
        "origin_alt_m": origin_llh[2],
    }
    return IndexedRows(rows, [float(row["_stamp"]) for row in rows]), origin_summary


def parse_gpstdatetime(date_text: str, time_text: str, leap_seconds: float) -> float | None:
    try:
        dt = datetime.strptime(f"{date_text} {time_text}", "%Y/%m/%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.strptime(f"{date_text} {time_text}", "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return dt.timestamp() - leap_seconds


def read_dop(path: Path | None, leap_seconds: float) -> IndexedRows:
    if path is None or not path.exists():
        return IndexedRows([], [])
    rows: list[dict[str, str]] = []
    with path.open(errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            fields = line.split()
            if len(fields) < 10:
                continue
            stamp = parse_gpstdatetime(fields[0], fields[1], leap_seconds)
            if stamp is None:
                continue
            rows.append(
                {
                    "_stamp": f"{stamp:.9f}",
                    "dop_nsat": fields[2],
                    "dop_gdop": fields[-4],
                    "dop_pdop": fields[-3],
                    "dop_hdop": fields[-2],
                    "dop_vdop": fields[-1],
                }
            )
    rows.sort(key=lambda item: float(item["_stamp"]))
    return IndexedRows(rows, [float(row["_stamp"]) for row in rows])


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


def parse_vec3(value: str) -> tuple[float, float, float]:
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 3:
        raise SystemExit("--attack-offset must be x,y,z")
    return float(parts[0]), float(parts[1]), float(parts[2])


def attack_scale(stamp: float, relative_t: float, windows: list[AttackWindow], ramp_s: float) -> float:
    best = 0.0
    for window in windows:
        is_relative = window.start_s < 1.0e8 and window.end_s < 1.0e8
        t = relative_t if is_relative else stamp
        if t < window.start_s or t > window.end_s:
            continue
        scale = 1.0
        if ramp_s > 1e-9:
            scale = min(scale, max(0.0, (t - window.start_s) / ramp_s))
            scale = min(scale, max(0.0, (window.end_s - t) / ramp_s))
        best = max(best, scale)
    return best


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def safe_norm(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


def score_row(row: dict[str, float], args: argparse.Namespace) -> tuple[float, dict[str, float]]:
    gate = max(1e-9, row["loose_gate_chi2"])
    maha_score = math.sqrt(max(0.0, row["effective_maha"]) / gate) if row["effective_maha"] > 0.0 else 0.0
    residual_score = row["effective_residual_norm_m"] / max(1e-9, args.residual_scale)
    pr_rms_score = row["effective_pr_rms_m"] / max(1e-9, args.pr_rms_scale)
    pr_abs_score = row["effective_pr_abs_max_m"] / max(1e-9, args.pr_abs_scale)
    doppler_score = row["raw_doppler_rms_mps"] / max(1e-9, args.doppler_scale)
    raim_score = row["effective_raim_score"] / max(1e-9, args.raim_scale)
    reference_score = row["effective_reference_residual_rms_m"] / max(1e-9, args.reference_residual_scale)
    rtk_quality_score = 0.0
    if row["rtk_quality"] > 0.0 and row["rtk_quality"] != 1.0:
        rtk_quality_score += 0.25
    if row["raw_healthy_pr_count"] > 0.0:
        rtk_quality_score += max(0.0, 8.0 - row["raw_healthy_pr_count"]) / 16.0
    if row["rtk_ratio"] > 0.0:
        rtk_quality_score += max(0.0, 3.0 - row["rtk_ratio"]) / 12.0
    components = {
        "score_maha": maha_score,
        "score_residual": residual_score,
        "score_pr_rms": pr_rms_score,
        "score_pr_abs": pr_abs_score,
        "score_doppler": doppler_score,
        "score_raw_raim": raim_score,
        "score_reference_residual": reference_score,
        "score_rtk_quality": rtk_quality_score,
    }
    combined = (
        0.24 * residual_score
        + 0.21 * maha_score
        + 0.16 * pr_rms_score
        + 0.12 * pr_abs_score
        + 0.12 * raim_score
        + 0.06 * reference_score
        + 0.05 * doppler_score
        + 0.04 * rtk_quality_score
    )
    return combined, components


def status_id(status_name: str) -> int:
    names = {
        "wait_alignment": 1,
        "accepted": 4,
        "accepted_pr_only": 5,
        "accepted_with_doppler": 6,
        "rejected": 9,
    }
    return names.get(status_name, 0)


def base_stamps(*indexes: IndexedRows) -> list[float]:
    for indexed in indexes:
        if indexed.rows:
            return indexed.stamps
    return []


def select_base_timeline(choice: str, indexes: dict[str, IndexedRows]) -> tuple[str, list[float]]:
    order = ["loose", "raw", "tight", "rtk", "dop", "rinex", "raw-residual"]
    if choice != "auto":
        indexed = indexes.get(choice)
        if indexed is not None and indexed.rows:
            return choice, indexed.stamps
        available = ", ".join(name for name in order if indexes.get(name) and indexes[name].rows) or "none"
        raise SystemExit(f"--base-timeline {choice} has no rows. Available timelines: {available}")

    for name in order:
        indexed = indexes.get(name)
        if indexed is not None and indexed.rows:
            return name, indexed.stamps
    return "none", []


def is_finite(value: float) -> bool:
    return not math.isnan(value) and not math.isinf(value)


def loose_row_is_valid(row: dict[str, str] | None, args: argparse.Namespace) -> bool:
    if row is None or args.disable_loose_sanity_filter:
        return row is not None
    max_residual = max(0.0, float(args.max_loose_residual_m))
    max_maha = max(0.0, float(args.max_loose_maha))
    residual_x = parse_float(row, "residual_x", 0.0)
    residual_y = parse_float(row, "residual_y", 0.0)
    residual_z = parse_float(row, "residual_z", 0.0)
    residual_norm = parse_float(row, "residual_norm", safe_norm(residual_x, residual_y, residual_z))
    maha = parse_float(row, "maha", 0.0)
    values = [residual_x, residual_y, residual_z, residual_norm, maha]
    if any(not is_finite(value) for value in values):
        return False
    if max(abs(residual_x), abs(residual_y), abs(residual_z), abs(residual_norm)) > max_residual:
        return False
    if abs(maha) > max_maha:
        return False
    return True


def fmt(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        return ""
    return f"{value:.9f}"


def build_dataset(args: argparse.Namespace) -> tuple[Path, Path, dict[str, object]]:
    output_dir = clean_path(args.output_dir)
    assert output_dir is not None
    output_dir.mkdir(parents=True, exist_ok=True)

    loose = read_indexed_csv(clean_path(args.loose))
    raw = read_indexed_csv(clean_path(args.raw))
    tight = read_indexed_csv(clean_path(args.tight))
    rtk, origin_summary = read_rtklib_pos(clean_path(args.rtklib_pos), args.gps_utc_leap_seconds, args.origin)
    dop = read_dop(clean_path(args.dop), args.gps_utc_leap_seconds)
    rinex = read_indexed_csv(clean_path(args.rinex_summary))
    raw_residual = read_indexed_csv(clean_path(args.raw_residual_summary))

    base_name, stamps = select_base_timeline(
        args.base_timeline,
        {
            "loose": loose,
            "raw": raw,
            "tight": tight,
            "rtk": rtk,
            "dop": dop,
            "rinex": rinex,
            "raw-residual": raw_residual,
        },
    )
    if not stamps:
        raise SystemExit("No input rows found. Provide at least one of --loose, --raw, --tight, --rtklib-pos, --rinex-summary, or --raw-residual-summary.")

    first_stamp = stamps[0]
    windows = parse_windows(args.attack_window)
    ox, oy, oz = parse_vec3(args.attack_offset)

    output_csv = output_dir / f"{args.name}_detection.csv"
    summary_json = output_dir / f"{args.name}_detection_summary.json"
    columns = [
        "stamp",
        "time_s",
        "base_timeline",
        "attack_label",
        "attack_scale",
        "detected",
        "triggered",
        "spoof_score",
        "score_threshold",
        "score_maha",
        "score_residual",
        "score_pr_rms",
        "score_pr_abs",
        "score_doppler",
        "score_raw_raim",
        "score_reference_residual",
        "score_rtk_quality",
        "loose_status_id",
        "loose_status_name",
        "loose_aligned",
        "loose_valid",
        "loose_maha",
        "loose_gate_chi2",
        "loose_residual_x_m",
        "loose_residual_y_m",
        "loose_residual_z_m",
        "loose_residual_norm_m",
        "loose_correction_norm_m",
        "raw_status",
        "raw_pr_count",
        "raw_healthy_pr_count",
        "raw_pr_outlier_reject_count",
        "raw_pr_rms_m",
        "raw_pr_abs_mean_m",
        "raw_pr_abs_max_m",
        "raw_lambda_ratio",
        "raw_doppler_rms_mps",
        "raw_doppler_used_count",
        "raw_tdcp_valid_count",
        "tight_lio_x_m",
        "tight_lio_y_m",
        "tight_lio_z_m",
        "tight_gnss_enu_x_m",
        "tight_gnss_enu_y_m",
        "tight_gnss_enu_z_m",
        "tight_lio_gnss_norm_m",
        "rtk_enu_e_m",
        "rtk_enu_n_m",
        "rtk_enu_u_m",
        "rtk_quality",
        "rtk_satellites",
        "rtk_ratio",
        "rtk_sdx_m",
        "rtk_sdy_m",
        "rtk_sdz_m",
        "dop_gdop",
        "dop_pdop",
        "dop_hdop",
        "dop_vdop",
        "rinex_satellite_count",
        "rinex_system_count",
        "rinex_systems",
        "rinex_code_obs_count",
        "rinex_carrier_obs_count",
        "rinex_doppler_obs_count",
        "rinex_cn0_obs_count",
        "rinex_mean_cn0_dbhz",
        "rinex_min_cn0_dbhz",
        "rinex_max_cn0_dbhz",
        "rinex_low_cn0_satellite_count",
        "rinex_code_delta_rms_m",
        "rinex_doppler_consistency_rms_mps",
        "rinex_lli_satellite_count",
        "raw_raim_used_satellite_count",
        "raw_raim_reference_quality",
        "raw_raim_mean_cn0_dbhz",
        "raw_raim_min_elevation_deg",
        "raw_raim_attack_label",
        "raw_raim_attacked_satellite_count",
        "raw_raim_wls_valid",
        "raw_raim_wls_delta_e_m",
        "raw_raim_wls_delta_n_m",
        "raw_raim_wls_delta_u_m",
        "raw_raim_wls_delta_norm_m",
        "raw_raim_clock_bias_m",
        "raw_raim_chi_square",
        "raw_raim_threshold",
        "raw_raim_score",
        "raw_raim_detected",
        "raw_raim_residual_rms_m",
        "raw_raim_weighted_rms",
        "raw_raim_max_abs_m",
        "raw_raim_outlier_count",
        "raw_reference_clock_bias_m",
        "raw_reference_chi_square",
        "raw_reference_threshold",
        "raw_reference_score",
        "raw_reference_detected",
        "raw_reference_residual_rms_m",
        "raw_reference_weighted_rms",
        "raw_reference_max_abs_m",
        "raw_reference_outlier_count",
        "synthetic_offset_x_m",
        "synthetic_offset_y_m",
        "synthetic_offset_z_m",
        "synthetic_pseudorange_delay_m",
        "effective_residual_x_m",
        "effective_residual_y_m",
        "effective_residual_z_m",
        "effective_residual_norm_m",
        "effective_maha",
        "effective_pr_rms_m",
        "effective_pr_abs_mean_m",
        "effective_pr_abs_max_m",
    ]

    rows_written = 0
    positive_rows = 0
    triggered_rows = 0
    detected_rows = 0
    consecutive = 0
    invalid_loose_rows = 0
    matched_loose_rows = 0

    with output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for stamp in stamps:
            loose_row = nearest(loose, stamp, args.max_delta_s)
            if loose_row is not None:
                matched_loose_rows += 1
                if not loose_row_is_valid(loose_row, args):
                    invalid_loose_rows += 1
                    loose_row = None
            raw_row = nearest(raw, stamp, args.max_delta_s)
            tight_row = nearest(tight, stamp, args.max_delta_s)
            rtk_row = nearest(rtk, stamp, args.max_delta_s)
            dop_row = nearest(dop, stamp, args.max_delta_s)
            rinex_row = nearest(rinex, stamp, args.max_delta_s)
            raw_residual_row = nearest(raw_residual, stamp, args.max_delta_s)

            rel_t = stamp - first_stamp
            scale = attack_scale(stamp, rel_t, windows, args.attack_ramp)
            sx, sy, sz = ox * scale, oy * scale, oz * scale
            delay = args.pseudorange_delay * scale
            attack_label = 1 if scale > 1e-9 else 0

            residual_x = parse_float(loose_row, "residual_x")
            residual_y = parse_float(loose_row, "residual_y")
            residual_z = parse_float(loose_row, "residual_z")
            residual_norm = parse_float(loose_row, "residual_norm", safe_norm(residual_x, residual_y, residual_z))
            maha = parse_float(loose_row, "maha")
            effective_x = residual_x + sx
            effective_y = residual_y + sy
            effective_z = residual_z + sz
            effective_norm = safe_norm(effective_x, effective_y, effective_z)
            if residual_norm <= 0.0 and effective_norm <= 0.0:
                effective_norm = safe_norm(sx, sy, sz)
            effective_maha = maha + (max(0.0, effective_norm * effective_norm - residual_norm * residual_norm) / 9.0)

            pr_rms = parse_float(raw_row, "pr_rms")
            pr_abs_mean = parse_float(raw_row, "pr_abs_mean")
            pr_abs_max = parse_float(raw_row, "pr_abs_max")
            raw_raim_score = parse_float(raw_residual_row, "raim_score")
            raw_reference_rms = parse_float(raw_residual_row, "reference_residual_rms_m")
            row_values = {
                "loose_gate_chi2": parse_float(loose_row, "gate_chi2", 16.27),
                "effective_maha": effective_maha,
                "effective_residual_norm_m": effective_norm,
                "effective_pr_rms_m": math.sqrt(pr_rms * pr_rms + delay * delay),
                "effective_pr_abs_max_m": pr_abs_max + delay,
                "raw_doppler_rms_mps": parse_float(raw_row, "doppler_rms"),
                "effective_raim_score": max(raw_raim_score, float(parse_int(raw_residual_row, "raim_detected"))),
                "effective_reference_residual_rms_m": math.sqrt(raw_reference_rms * raw_reference_rms + delay * delay),
                "rtk_quality": parse_float(rtk_row, "rtk_quality", parse_float(loose_row, "raw_rtk_stat")),
                "rtk_ratio": parse_float(rtk_row, "rtk_ratio", parse_float(loose_row, "raw_rtk_ratio")),
                "raw_healthy_pr_count": parse_float(raw_row, "healthy_pr_count"),
            }
            spoof_score, components = score_row(row_values, args)
            triggered = 1 if spoof_score >= args.threshold else 0
            consecutive = consecutive + 1 if triggered else 0
            detected = 1 if consecutive >= max(1, args.consecutive) else 0

            lio_dx = parse_float(tight_row, "enu_x") - parse_float(tight_row, "lio_x")
            lio_dy = parse_float(tight_row, "enu_y") - parse_float(tight_row, "lio_y")
            lio_dz = parse_float(tight_row, "enu_z") - parse_float(tight_row, "lio_z")
            loose_status_name = (loose_row or {}).get("status_name", "")
            raw_status = (raw_row or {}).get("status", "")

            output = {
                "stamp": fmt(stamp),
                "time_s": fmt(rel_t),
                "base_timeline": base_name,
                "attack_label": str(attack_label),
                "attack_scale": fmt(scale),
                "detected": str(detected),
                "triggered": str(triggered),
                "spoof_score": fmt(spoof_score),
                "score_threshold": fmt(args.threshold),
                "score_maha": fmt(components["score_maha"]),
                "score_residual": fmt(components["score_residual"]),
                "score_pr_rms": fmt(components["score_pr_rms"]),
                "score_pr_abs": fmt(components["score_pr_abs"]),
                "score_doppler": fmt(components["score_doppler"]),
                "score_raw_raim": fmt(components["score_raw_raim"]),
                "score_reference_residual": fmt(components["score_reference_residual"]),
                "score_rtk_quality": fmt(components["score_rtk_quality"]),
                "loose_status_id": str(status_id(loose_status_name or (loose_row or {}).get("status", ""))),
                "loose_status_name": loose_status_name,
                "loose_aligned": str(parse_boolish(loose_row, "aligned")),
                "loose_valid": "1" if loose_row is not None else "0",
                "loose_maha": fmt(maha),
                "loose_gate_chi2": fmt(row_values["loose_gate_chi2"]),
                "loose_residual_x_m": fmt(residual_x),
                "loose_residual_y_m": fmt(residual_y),
                "loose_residual_z_m": fmt(residual_z),
                "loose_residual_norm_m": fmt(residual_norm),
                "loose_correction_norm_m": fmt(parse_float(loose_row, "correction_norm")),
                "raw_status": raw_status,
                "raw_pr_count": str(parse_int(raw_row, "raw_pr_count")),
                "raw_healthy_pr_count": str(parse_int(raw_row, "healthy_pr_count")),
                "raw_pr_outlier_reject_count": str(parse_int(raw_row, "pr_outlier_reject_count")),
                "raw_pr_rms_m": fmt(pr_rms),
                "raw_pr_abs_mean_m": fmt(pr_abs_mean),
                "raw_pr_abs_max_m": fmt(pr_abs_max),
                "raw_lambda_ratio": fmt(parse_float(raw_row, "lambda_ratio")),
                "raw_doppler_rms_mps": fmt(row_values["raw_doppler_rms_mps"]),
                "raw_doppler_used_count": str(parse_int(raw_row, "doppler_used_count")),
                "raw_tdcp_valid_count": str(parse_int(raw_row, "tdcp_valid_count")),
                "tight_lio_x_m": fmt(parse_float(tight_row, "lio_x")),
                "tight_lio_y_m": fmt(parse_float(tight_row, "lio_y")),
                "tight_lio_z_m": fmt(parse_float(tight_row, "lio_z")),
                "tight_gnss_enu_x_m": fmt(parse_float(tight_row, "enu_x")),
                "tight_gnss_enu_y_m": fmt(parse_float(tight_row, "enu_y")),
                "tight_gnss_enu_z_m": fmt(parse_float(tight_row, "enu_z")),
                "tight_lio_gnss_norm_m": fmt(safe_norm(lio_dx, lio_dy, lio_dz) if tight_row else 0.0),
                "rtk_enu_e_m": fmt(parse_float(rtk_row, "rtk_enu_e_m")),
                "rtk_enu_n_m": fmt(parse_float(rtk_row, "rtk_enu_n_m")),
                "rtk_enu_u_m": fmt(parse_float(rtk_row, "rtk_enu_u_m")),
                "rtk_quality": fmt(row_values["rtk_quality"]),
                "rtk_satellites": str(parse_int(rtk_row, "rtk_satellites", parse_int(loose_row, "raw_rtk_ns"))),
                "rtk_ratio": fmt(row_values["rtk_ratio"]),
                "rtk_sdx_m": fmt(parse_float(rtk_row, "rtk_sdx_m")),
                "rtk_sdy_m": fmt(parse_float(rtk_row, "rtk_sdy_m")),
                "rtk_sdz_m": fmt(parse_float(rtk_row, "rtk_sdz_m")),
                "dop_gdop": fmt(parse_float(dop_row, "dop_gdop", parse_float(loose_row, "raw_rtk_dop_gdop"))),
                "dop_pdop": fmt(parse_float(dop_row, "dop_pdop", parse_float(loose_row, "raw_rtk_dop_pdop"))),
                "dop_hdop": fmt(parse_float(dop_row, "dop_hdop", parse_float(loose_row, "raw_rtk_dop_hdop"))),
                "dop_vdop": fmt(parse_float(dop_row, "dop_vdop", parse_float(loose_row, "raw_rtk_dop_vdop"))),
                "rinex_satellite_count": str(parse_int(rinex_row, "satellite_count")),
                "rinex_system_count": str(parse_int(rinex_row, "system_count")),
                "rinex_systems": (rinex_row or {}).get("systems", ""),
                "rinex_code_obs_count": str(parse_int(rinex_row, "code_obs_count")),
                "rinex_carrier_obs_count": str(parse_int(rinex_row, "carrier_obs_count")),
                "rinex_doppler_obs_count": str(parse_int(rinex_row, "doppler_obs_count")),
                "rinex_cn0_obs_count": str(parse_int(rinex_row, "cn0_obs_count")),
                "rinex_mean_cn0_dbhz": fmt(parse_float(rinex_row, "mean_cn0_dbhz")),
                "rinex_min_cn0_dbhz": fmt(parse_float(rinex_row, "min_cn0_dbhz")),
                "rinex_max_cn0_dbhz": fmt(parse_float(rinex_row, "max_cn0_dbhz")),
                "rinex_low_cn0_satellite_count": str(parse_int(rinex_row, "low_cn0_satellite_count")),
                "rinex_code_delta_rms_m": fmt(parse_float(rinex_row, "code_delta_rms_m")),
                "rinex_doppler_consistency_rms_mps": fmt(parse_float(rinex_row, "doppler_consistency_rms_mps")),
                "rinex_lli_satellite_count": str(parse_int(rinex_row, "lli_satellite_count")),
                "raw_raim_used_satellite_count": str(parse_int(raw_residual_row, "used_satellite_count")),
                "raw_raim_reference_quality": str(parse_int(raw_residual_row, "reference_quality")),
                "raw_raim_mean_cn0_dbhz": fmt(parse_float(raw_residual_row, "mean_cn0_dbhz")),
                "raw_raim_min_elevation_deg": fmt(parse_float(raw_residual_row, "min_elevation_deg")),
                "raw_raim_attack_label": str(parse_int(raw_residual_row, "attack_label")),
                "raw_raim_attacked_satellite_count": str(parse_int(raw_residual_row, "attacked_satellite_count")),
                "raw_raim_wls_valid": str(parse_int(raw_residual_row, "wls_valid")),
                "raw_raim_wls_delta_e_m": fmt(parse_float(raw_residual_row, "wls_delta_e_m")),
                "raw_raim_wls_delta_n_m": fmt(parse_float(raw_residual_row, "wls_delta_n_m")),
                "raw_raim_wls_delta_u_m": fmt(parse_float(raw_residual_row, "wls_delta_u_m")),
                "raw_raim_wls_delta_norm_m": fmt(parse_float(raw_residual_row, "wls_delta_norm_m")),
                "raw_raim_clock_bias_m": fmt(parse_float(raw_residual_row, "wls_clock_bias_m")),
                "raw_raim_chi_square": fmt(parse_float(raw_residual_row, "raim_chi_square")),
                "raw_raim_threshold": fmt(parse_float(raw_residual_row, "raim_threshold")),
                "raw_raim_score": fmt(raw_raim_score),
                "raw_raim_detected": str(parse_int(raw_residual_row, "raim_detected")),
                "raw_raim_residual_rms_m": fmt(parse_float(raw_residual_row, "raim_residual_rms_m")),
                "raw_raim_weighted_rms": fmt(parse_float(raw_residual_row, "raim_weighted_rms")),
                "raw_raim_max_abs_m": fmt(parse_float(raw_residual_row, "raim_max_abs_m")),
                "raw_raim_outlier_count": str(parse_int(raw_residual_row, "raim_outlier_count")),
                "raw_reference_clock_bias_m": fmt(parse_float(raw_residual_row, "reference_clock_bias_m")),
                "raw_reference_chi_square": fmt(parse_float(raw_residual_row, "reference_chi_square")),
                "raw_reference_threshold": fmt(parse_float(raw_residual_row, "reference_threshold")),
                "raw_reference_score": fmt(parse_float(raw_residual_row, "reference_score")),
                "raw_reference_detected": str(parse_int(raw_residual_row, "reference_detected")),
                "raw_reference_residual_rms_m": fmt(raw_reference_rms),
                "raw_reference_weighted_rms": fmt(parse_float(raw_residual_row, "reference_weighted_rms")),
                "raw_reference_max_abs_m": fmt(parse_float(raw_residual_row, "reference_max_abs_m")),
                "raw_reference_outlier_count": str(parse_int(raw_residual_row, "reference_outlier_count")),
                "synthetic_offset_x_m": fmt(sx),
                "synthetic_offset_y_m": fmt(sy),
                "synthetic_offset_z_m": fmt(sz),
                "synthetic_pseudorange_delay_m": fmt(delay),
                "effective_residual_x_m": fmt(effective_x),
                "effective_residual_y_m": fmt(effective_y),
                "effective_residual_z_m": fmt(effective_z),
                "effective_residual_norm_m": fmt(effective_norm),
                "effective_maha": fmt(effective_maha),
                "effective_pr_rms_m": fmt(row_values["effective_pr_rms_m"]),
                "effective_pr_abs_mean_m": fmt(pr_abs_mean + delay),
                "effective_pr_abs_max_m": fmt(row_values["effective_pr_abs_max_m"]),
            }
            writer.writerow(output)
            rows_written += 1
            positive_rows += attack_label
            triggered_rows += triggered
            detected_rows += detected

    summary = {
        "name": args.name,
        "rows": rows_written,
        "duration_s": stamps[-1] - stamps[0] if len(stamps) > 1 else 0.0,
        "positive_rows": positive_rows,
        "triggered_rows": triggered_rows,
        "detected_rows": detected_rows,
        "threshold": args.threshold,
        "consecutive": args.consecutive,
        "max_delta_s": args.max_delta_s,
        "base_timeline": base_name,
        "selected_base_rows": len(stamps),
        "matched_loose_rows": matched_loose_rows,
        "invalid_loose_rows": invalid_loose_rows,
        "loose_sanity_filter": {
            "enabled": not args.disable_loose_sanity_filter,
            "max_loose_residual_m": args.max_loose_residual_m,
            "max_loose_maha": args.max_loose_maha,
        },
        "inputs": {
            "loose_rows": len(loose.rows),
            "raw_rows": len(raw.rows),
            "tight_rows": len(tight.rows),
            "rtk_rows": len(rtk.rows),
            "dop_rows": len(dop.rows),
            "rinex_epoch_rows": len(rinex.rows),
            "raw_residual_epoch_rows": len(raw_residual.rows),
        },
        "origin": origin_summary,
        "outputs": {
            "detection_csv": str(output_csv),
            "summary_json": str(summary_json),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return output_csv, summary_json, summary


def main() -> int:
    args = parse_args()
    output_csv, summary_json, summary = build_dataset(args)
    print("Detection dataset built")
    print(f"  rows: {summary['rows']}")
    print(f"  positives: {summary['positive_rows']}")
    print(f"  detected rows: {summary['detected_rows']}")
    print(f"  output: {output_csv}")
    print(f"  summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
