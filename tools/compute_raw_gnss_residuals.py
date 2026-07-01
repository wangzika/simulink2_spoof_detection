#!/usr/bin/env python3
"""Compute raw GNSS pseudorange residuals and a transparent RAIM baseline.

The broadcast-orbit implementation currently supports GPS ephemerides, while
the observation pipeline is multi-constellation aware and records unsupported
systems for later Galileo/BDS extension. It decodes pseudorange, Doppler, and
carrier observations from RINEX observation files or a precomputed
satellite-feature CSV, solves a weighted least-squares GNSS-only position/clock
estimate, and reports post-fit RAIM, reference-position residuals, Doppler
range-rate residuals, and TDCP residuals against RTK/known ECEF.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from statistics import NormalDist
from typing import Iterable

from extract_rinex_features import iter_epochs, values_by_prefix, wavelength_m


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GPS_EPOCH_UNIX_S = 315964800.0
SPEED_OF_LIGHT_MPS = 299792458.0
GPS_MU_M3PS2 = 3.986005e14
EARTH_ROTATION_RADPS = 7.2921151467e-5
GPS_RELATIVISTIC_F = -4.442807633e-10
WGS84_A_M = 6378137.0
WGS84_E2 = 6.69437999014e-3


@dataclass
class Ephemeris:
    sat_id: str
    toc_week: int
    toc_tow_s: float
    af0_s: float
    af1_sps: float
    af2_sps2: float
    iode: float
    crs_m: float
    delta_n_radps: float
    m0_rad: float
    cuc_rad: float
    eccentricity: float
    cus_rad: float
    sqrt_a_m12: float
    toe_s: float
    cic_rad: float
    omega0_rad: float
    cis_rad: float
    i0_rad: float
    crc_m: float
    omega_rad: float
    omega_dot_radps: float
    idot_radps: float
    gps_week: int
    tgd_s: float
    health: float


@dataclass
class ReceiverPosition:
    stamp: float
    x_m: float
    y_m: float
    z_m: float
    quality: int = 0


@dataclass
class Observation:
    stamp: float
    time_s: float
    epoch_index: int
    sat_id: str
    code_type: str
    pseudorange_m: float
    cn0_dbhz: float | None
    lli_count: int
    attack_label: int = 0
    attack_scale: float = 0.0
    injected_pseudorange_bias_m: float = 0.0
    clean_pseudorange_m: float | None = None
    doppler_range_rate_mps: float | None = None
    carrier_phase_m: float | None = None


@dataclass
class PreparedObservation:
    obs: Observation
    observed_pseudorange_m: float
    sat_x_m: float
    sat_y_m: float
    sat_z_m: float
    sat_clock_s: float
    reference_range_m: float
    elevation_deg: float
    azimuth_deg: float
    sigma_m: float
    weight: float
    direct_attack_bias_m: float
    attack_scale: float
    doppler_range_rate_mps: float | None
    carrier_phase_m: float | None


@dataclass
class WlsSolution:
    valid: bool
    x_m: float
    y_m: float
    z_m: float
    clock_bias_m: float
    iterations: int
    residuals_m: list[float]


@dataclass
class AttackWindow:
    start_s: float
    end_s: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute broadcast-ephemeris raw pseudorange residuals and RAIM statistics.")
    parser.add_argument("--obs", help="RINEX observation file. Used when --satellite-features is not provided.")
    parser.add_argument("--satellite-features", help="CSV from extract_rinex_features.py or inject_observation_attack.py.")
    parser.add_argument("--nav", required=True, help="RINEX broadcast navigation file.")
    parser.add_argument("--rtklib-pos", help="RTKLIB .pos file used as reference/initial position.")
    parser.add_argument("--receiver-ecef", default="", help="Fallback receiver ECEF x,y,z in meters.")
    parser.add_argument("--name", default="raw_gnss", help="Output file prefix.")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "build" / "paper_platform" / "raw_gnss"))
    parser.add_argument("--systems", default="G", help="Comma-separated systems to read, e.g. G,E,C. Broadcast residuals currently support GPS/G.")
    parser.add_argument("--gps-utc-leap-seconds", type=float, default=18.0)
    parser.add_argument("--max-delta-s", type=float, default=1.5, help="Reference-position sync tolerance.")
    parser.add_argument("--elevation-mask-deg", type=float, default=10.0)
    parser.add_argument("--min-satellites", type=int, default=5)
    parser.add_argument("--measurement-sigma-m", type=float, default=4.0)
    parser.add_argument("--cn0-reference-dbhz", type=float, default=45.0)
    parser.add_argument("--raim-pfa", type=float, default=1.0e-3)
    parser.add_argument("--outlier-sigma", type=float, default=4.0)
    parser.add_argument("--outlier-abs-m", type=float, default=25.0)
    parser.add_argument("--max-epochs", type=int, default=0)
    parser.add_argument("--attack-window", action="append", default=[], help="Optional direct observation attack window, start:end or +start:+end.")
    parser.add_argument("--attack-ramp-s", type=float, default=2.0)
    parser.add_argument("--attack-common-delay-m", type=float, default=0.0)
    parser.add_argument("--attack-offset-enu-m", default="0,0,0", help="Direct attack as spoofed receiver ENU offset, e,n,u meters.")
    parser.add_argument("--attack-satellite-mode", choices=["all", "alternating", "list"], default="all")
    parser.add_argument("--attack-satellites", default="", help="Comma-separated satellite IDs used when --attack-satellite-mode=list.")
    return parser.parse_args()


def clean_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return float(text.replace("D", "E").replace("d", "E"))
    except ValueError:
        return None


def parse_int(value: str | None, default: int = 0) -> int:
    parsed = parse_float(value)
    if parsed is None:
        return default
    return int(round(parsed))


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


def gps_week_tow_to_unix(week: int, tow_s: float, leap_seconds: float) -> float:
    return GPS_EPOCH_UNIX_S + week * 604800.0 + tow_s - leap_seconds


def unix_to_gps_week_tow(stamp: float, leap_seconds: float) -> tuple[int, float]:
    gps_seconds = stamp + leap_seconds - GPS_EPOCH_UNIX_S
    week = int(math.floor(gps_seconds / 604800.0))
    tow_s = gps_seconds - week * 604800.0
    return week, tow_s


def nav_datetime_to_gps_week_tow(year: int, month: int, day: int, hour: int, minute: int, second: float) -> tuple[int, float]:
    whole_second = int(math.floor(second))
    microsecond = int(round((second - whole_second) * 1_000_000.0))
    if microsecond >= 1_000_000:
        whole_second += 1
        microsecond -= 1_000_000
    # RINEX navigation epochs are expressed in the navigation-system time scale.
    # Treating the label as a GPS-time count gives the correct GPS week/TOW.
    dt = datetime(year, month, day, hour, minute, whole_second, microsecond, tzinfo=timezone.utc)
    gps_seconds = dt.timestamp() - GPS_EPOCH_UNIX_S
    week = int(math.floor(gps_seconds / 604800.0))
    return week, gps_seconds - week * 604800.0


def check_gps_time(dt_s: float) -> float:
    half_week = 302400.0
    if dt_s > half_week:
        dt_s -= 604800.0
    elif dt_s < -half_week:
        dt_s += 604800.0
    return dt_s


def parse_nav_values(line: str, start: int = 4, count: int = 4) -> list[float]:
    values: list[float] = []
    for index in range(count):
        item = parse_float(line[start + index * 19 : start + (index + 1) * 19])
        if item is not None:
            values.append(item)
    if len(values) < count:
        split_values = [parse_float(part) for part in line[start:].split()]
        values = [value for value in split_values if value is not None]
    while len(values) < count:
        values.append(0.0)
    return values[:count]


def is_nav_record_start(line: str) -> bool:
    sat = line[:3].strip()
    return len(sat) == 3 and sat[0].isalpha() and sat[1:].isdigit()


def parse_gps_ephemeris(record: list[str]) -> Ephemeris | None:
    if len(record) < 8:
        return None
    first = record[0]
    sat_id = first[:3].strip()
    if not sat_id.startswith("G"):
        return None
    match = re.match(
        r"^([A-Z]\d{2})\s+(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s*(\d{1,2}(?:\.\d*)?)(.*)$",
        first.rstrip("\n"),
    )
    if match is None:
        return None
    try:
        year = int(match.group(2))
        month = int(match.group(3))
        day = int(match.group(4))
        hour = int(match.group(5))
        minute = int(match.group(6))
        second = float(match.group(7))
    except ValueError:
        return None
    toc_week_from_label, toc_tow_s = nav_datetime_to_gps_week_tow(year, month, day, hour, minute, second)
    af0_s, af1_sps, af2_sps2 = parse_nav_values(match.group(8), start=0, count=3)

    line1 = parse_nav_values(record[1])
    line2 = parse_nav_values(record[2])
    line3 = parse_nav_values(record[3])
    line4 = parse_nav_values(record[4])
    line5 = parse_nav_values(record[5])
    line6 = parse_nav_values(record[6])

    gps_week = int(round(line5[2])) if line5[2] > 0 else toc_week_from_label
    return Ephemeris(
        sat_id=sat_id,
        toc_week=gps_week,
        toc_tow_s=toc_tow_s,
        af0_s=af0_s,
        af1_sps=af1_sps,
        af2_sps2=af2_sps2,
        iode=line1[0],
        crs_m=line1[1],
        delta_n_radps=line1[2],
        m0_rad=line1[3],
        cuc_rad=line2[0],
        eccentricity=line2[1],
        cus_rad=line2[2],
        sqrt_a_m12=line2[3],
        toe_s=line3[0],
        cic_rad=line3[1],
        omega0_rad=line3[2],
        cis_rad=line3[3],
        i0_rad=line4[0],
        crc_m=line4[1],
        omega_rad=line4[2],
        omega_dot_radps=line4[3],
        idot_radps=line5[0],
        gps_week=gps_week,
        tgd_s=line6[2],
        health=line6[1],
    )


def parse_navigation_file(path: Path) -> dict[str, list[Ephemeris]]:
    with path.open(errors="ignore") as handle:
        for line in handle:
            label = line[60:].strip() if len(line) >= 60 else ""
            if label == "END OF HEADER":
                break
        lines = list(handle)

    by_satellite: dict[str, list[Ephemeris]] = {}
    index = 0
    while index < len(lines):
        if not is_nav_record_start(lines[index]):
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines) and not is_nav_record_start(lines[index]):
            index += 1
        ephemeris = parse_gps_ephemeris(lines[start:index])
        if ephemeris is not None:
            by_satellite.setdefault(ephemeris.sat_id, []).append(ephemeris)

    for items in by_satellite.values():
        items.sort(key=lambda eph: eph.gps_week * 604800.0 + eph.toe_s)
    return by_satellite


def select_ephemeris(ephemerides: dict[str, list[Ephemeris]], sat_id: str, gps_week: int, tow_s: float) -> Ephemeris | None:
    items = ephemerides.get(sat_id, [])
    if not items:
        return None
    target = gps_week * 604800.0 + tow_s
    return min(items, key=lambda eph: abs(target - (eph.gps_week * 604800.0 + eph.toe_s)))


def solve_kepler(mean_anomaly: float, eccentricity: float) -> float:
    eccentric_anomaly = mean_anomaly
    for _ in range(20):
        delta = (eccentric_anomaly - eccentricity * math.sin(eccentric_anomaly) - mean_anomaly) / max(
            1.0 - eccentricity * math.cos(eccentric_anomaly),
            1e-14,
        )
        eccentric_anomaly -= delta
        if abs(delta) < 1e-13:
            break
    return eccentric_anomaly


def satellite_position_clock(eph: Ephemeris, gps_week: int, transmit_tow_s: float) -> tuple[float, float, float, float]:
    tk = check_gps_time((gps_week - eph.gps_week) * 604800.0 + transmit_tow_s - eph.toe_s)
    semi_major_axis_m = eph.sqrt_a_m12 * eph.sqrt_a_m12
    mean_motion = math.sqrt(GPS_MU_M3PS2 / (semi_major_axis_m**3)) + eph.delta_n_radps
    mean_anomaly = eph.m0_rad + mean_motion * tk
    eccentric_anomaly = solve_kepler(mean_anomaly, eph.eccentricity)
    sin_e = math.sin(eccentric_anomaly)
    cos_e = math.cos(eccentric_anomaly)
    true_anomaly = math.atan2(math.sqrt(1.0 - eph.eccentricity * eph.eccentricity) * sin_e, cos_e - eph.eccentricity)
    argument_latitude = true_anomaly + eph.omega_rad
    sin_2u = math.sin(2.0 * argument_latitude)
    cos_2u = math.cos(2.0 * argument_latitude)
    corrected_latitude = argument_latitude + eph.cus_rad * sin_2u + eph.cuc_rad * cos_2u
    radius_m = semi_major_axis_m * (1.0 - eph.eccentricity * cos_e) + eph.crs_m * sin_2u + eph.crc_m * cos_2u
    inclination_rad = eph.i0_rad + eph.idot_radps * tk + eph.cis_rad * sin_2u + eph.cic_rad * cos_2u
    x_orb_m = radius_m * math.cos(corrected_latitude)
    y_orb_m = radius_m * math.sin(corrected_latitude)
    omega_rad = eph.omega0_rad + (eph.omega_dot_radps - EARTH_ROTATION_RADPS) * tk - EARTH_ROTATION_RADPS * eph.toe_s

    cos_omega = math.cos(omega_rad)
    sin_omega = math.sin(omega_rad)
    cos_i = math.cos(inclination_rad)
    sin_i = math.sin(inclination_rad)
    x_m = x_orb_m * cos_omega - y_orb_m * cos_i * sin_omega
    y_m = x_orb_m * sin_omega + y_orb_m * cos_i * cos_omega
    z_m = y_orb_m * sin_i

    clock_dt_s = check_gps_time((gps_week - eph.toc_week) * 604800.0 + transmit_tow_s - eph.toc_tow_s)
    relativistic_s = GPS_RELATIVISTIC_F * eph.eccentricity * eph.sqrt_a_m12 * sin_e
    clock_s = eph.af0_s + eph.af1_sps * clock_dt_s + eph.af2_sps2 * clock_dt_s * clock_dt_s + relativistic_s - eph.tgd_s
    return x_m, y_m, z_m, clock_s


def rotate_satellite_for_earth_rotation(x_m: float, y_m: float, z_m: float, travel_time_s: float) -> tuple[float, float, float]:
    angle = EARTH_ROTATION_RADPS * travel_time_s
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return cos_a * x_m + sin_a * y_m, -sin_a * x_m + cos_a * y_m, z_m


def norm3(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


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


def ecef_to_enu_vector(dx_m: float, dy_m: float, dz_m: float, lat_rad: float, lon_rad: float) -> tuple[float, float, float]:
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    east = -sin_lon * dx_m + cos_lon * dy_m
    north = -sin_lat * cos_lon * dx_m - sin_lat * sin_lon * dy_m + cos_lat * dz_m
    up = cos_lat * cos_lon * dx_m + cos_lat * sin_lon * dy_m + sin_lat * dz_m
    return east, north, up


def enu_to_ecef_vector(east_m: float, north_m: float, up_m: float, lat_rad: float, lon_rad: float) -> tuple[float, float, float]:
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    dx = -sin_lon * east_m - sin_lat * cos_lon * north_m + cos_lat * cos_lon * up_m
    dy = cos_lon * east_m - sin_lat * sin_lon * north_m + cos_lat * sin_lon * up_m
    dz = cos_lat * north_m + sin_lat * up_m
    return dx, dy, dz


def elevation_azimuth(receiver: ReceiverPosition, sat_xyz: tuple[float, float, float]) -> tuple[float, float]:
    lat, lon, _ = ecef_to_geodetic(receiver.x_m, receiver.y_m, receiver.z_m)
    east, north, up = ecef_to_enu_vector(
        sat_xyz[0] - receiver.x_m,
        sat_xyz[1] - receiver.y_m,
        sat_xyz[2] - receiver.z_m,
        lat,
        lon,
    )
    horizontal = math.hypot(east, north)
    elevation = math.degrees(math.atan2(up, horizontal))
    azimuth = math.degrees(math.atan2(east, north))
    if azimuth < 0.0:
        azimuth += 360.0
    return elevation, azimuth


def read_rtklib_pos(path: Path | None, leap_seconds: float) -> list[ReceiverPosition]:
    if path is None or not path.exists():
        return []
    positions: list[ReceiverPosition] = []
    with path.open(errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            fields = line.split()
            if len(fields) < 7:
                continue
            try:
                week = int(fields[0])
                tow_s = float(fields[1])
                positions.append(
                    ReceiverPosition(
                        stamp=gps_week_tow_to_unix(week, tow_s, leap_seconds),
                        x_m=float(fields[2]),
                        y_m=float(fields[3]),
                        z_m=float(fields[4]),
                        quality=int(float(fields[5])),
                    )
                )
            except ValueError:
                continue
    positions.sort(key=lambda item: item.stamp)
    return positions


def parse_receiver_ecef(value: str) -> ReceiverPosition | None:
    if not value:
        return None
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 3:
        raise SystemExit("--receiver-ecef must be x,y,z")
    return ReceiverPosition(0.0, float(parts[0]), float(parts[1]), float(parts[2]), 0)


def nearest_position(positions: list[ReceiverPosition], stamp: float, max_delta_s: float, fallback: ReceiverPosition | None) -> ReceiverPosition | None:
    if not positions:
        return fallback
    stamps = [item.stamp for item in positions]
    pos = bisect.bisect_left(stamps, stamp)
    candidates = []
    if pos < len(stamps):
        candidates.append(pos)
    if pos > 0:
        candidates.append(pos - 1)
    best = min(candidates, key=lambda index: abs(stamps[index] - stamp))
    if abs(stamps[best] - stamp) <= max_delta_s:
        return positions[best]
    return fallback


def preferred_code(values) -> tuple[str, float] | None:
    code_values = [item for item in values_by_prefix(values, "C") if item.value is not None]
    if not code_values:
        return None
    priority = ["C1C", "C1W", "C1X", "C1P", "C2W", "C2X", "C5X"]
    by_type = {item.obs_type: item.value for item in code_values if item.value is not None}
    for obs_type in priority:
        if obs_type in by_type:
            return obs_type, float(by_type[obs_type])
    first = code_values[0]
    return first.obs_type, float(first.value)


def preferred_carrier_phase_m(system: str, values) -> float | None:
    carrier_values = [item for item in values_by_prefix(values, "L") if item.value is not None]
    if not carrier_values:
        return None
    priority = ["L1C", "L1W", "L1X", "L1P", "L2W", "L2X", "L5X"]
    by_type = {item.obs_type: item.value for item in carrier_values if item.value is not None}
    ordered = [obs_type for obs_type in priority if obs_type in by_type]
    if not ordered:
        ordered = [carrier_values[0].obs_type]
    wav = wavelength_m(system, ordered[0])
    if wav is None:
        return None
    return float(by_type[ordered[0]]) * wav


def preferred_doppler_range_rate_mps(system: str, values) -> float | None:
    doppler_values = [item for item in values_by_prefix(values, "D") if item.value is not None]
    if not doppler_values:
        return None
    priority = ["D1C", "D1W", "D1X", "D1P", "D2W", "D2X", "D5X"]
    by_type = {item.obs_type: item.value for item in doppler_values if item.value is not None}
    ordered = [obs_type for obs_type in priority if obs_type in by_type]
    if not ordered:
        ordered = [doppler_values[0].obs_type]
    wav = wavelength_m(system, ordered[0])
    if wav is None:
        return None
    return -float(by_type[ordered[0]]) * wav


def primary_cn0(values) -> float | None:
    cn0_values = [item.value for item in values_by_prefix(values, "S") if item.value is not None]
    if not cn0_values:
        return None
    return float(cn0_values[0])


def load_observations_from_rinex(path: Path, leap_seconds: float, systems: set[str], max_epochs: int) -> list[Observation]:
    epochs, _metadata = iter_epochs(path, leap_seconds=leap_seconds, systems=systems, max_epochs=max_epochs)
    observations: list[Observation] = []
    for epoch_index, epoch in enumerate(epochs):
        for sat in epoch.satellites:
            if sat.sat_id[0] not in systems:
                continue
            code = preferred_code(sat.values)
            if code is None:
                continue
            code_type, pseudorange_m = code
            observations.append(
                Observation(
                    stamp=epoch.stamp,
                    time_s=epoch.time_s,
                    epoch_index=epoch_index,
                    sat_id=sat.sat_id,
                    code_type=code_type,
                    pseudorange_m=pseudorange_m,
                    cn0_dbhz=primary_cn0(sat.values),
                    lli_count=sum(1 for item in sat.values if item.lli is not None and item.lli != 0),
                    doppler_range_rate_mps=preferred_doppler_range_rate_mps(sat.sat_id[0], sat.values),
                    carrier_phase_m=preferred_carrier_phase_m(sat.sat_id[0], sat.values),
                )
            )
    return observations


def load_observations_from_satellite_features(path: Path, systems: set[str], max_epochs: int) -> list[Observation]:
    observations: list[Observation] = []
    kept_epochs: set[int] = set()
    with path.open(newline="", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            sat_id = row.get("sat_id", "")
            if len(sat_id) < 2 or sat_id[0] not in systems:
                continue
            epoch_index = parse_int(row.get("epoch_index"), len(kept_epochs))
            if max_epochs > 0 and epoch_index not in kept_epochs and len(kept_epochs) >= max_epochs:
                continue
            kept_epochs.add(epoch_index)
            pseudorange_m = parse_float(row.get("primary_code_m"))
            if pseudorange_m is None:
                continue
            observations.append(
                Observation(
                    stamp=float(row["stamp"]),
                    time_s=float(row.get("time_s", "0") or 0.0),
                    epoch_index=epoch_index,
                    sat_id=sat_id,
                    code_type=row.get("primary_code_type", ""),
                    pseudorange_m=pseudorange_m,
                    cn0_dbhz=parse_float(row.get("primary_cn0_dbhz")) or parse_float(row.get("mean_cn0_dbhz")),
                    lli_count=parse_int(row.get("lli_count")),
                    attack_label=parse_int(row.get("attack_label")),
                    attack_scale=parse_float(row.get("attack_scale")) or 0.0,
                    injected_pseudorange_bias_m=parse_float(row.get("injected_pseudorange_bias_m")) or 0.0,
                    clean_pseudorange_m=parse_float(row.get("clean_primary_code_m")),
                    doppler_range_rate_mps=parse_float(row.get("doppler_range_rate_mps")),
                    carrier_phase_m=parse_float(row.get("primary_carrier_phase_m")),
                )
            )
    return observations


def parse_systems(value: str) -> set[str]:
    systems = {item.strip() for item in value.split(",") if item.strip()}
    return systems or {"G"}


def parse_windows(values: list[str]) -> list[AttackWindow]:
    windows: list[AttackWindow] = []
    for value in values:
        if ":" not in value:
            raise SystemExit("--attack-window must be start:end")
        start_text, end_text = value.split(":", 1)
        start = float(start_text.lstrip("+")) if start_text.startswith("+") else float(start_text)
        end = float(end_text.lstrip("+")) if end_text.startswith("+") else float(end_text)
        if end <= start:
            raise SystemExit("--attack-window end must be greater than start")
        windows.append(AttackWindow(start, end))
    return windows


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


def parse_vec3(value: str, name: str) -> tuple[float, float, float]:
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 3:
        raise SystemExit(f"{name} must be x,y,z")
    return float(parts[0]), float(parts[1]), float(parts[2])


def should_attack_satellite(sat_id: str, mode: str, selected: set[str]) -> bool:
    if mode == "all":
        return True
    if mode == "list":
        return sat_id in selected
    try:
        prn = int(sat_id[1:])
    except ValueError:
        return False
    return prn % 2 == 0


def measurement_sigma(cn0_dbhz: float | None, elevation_deg: float, base_sigma_m: float, cn0_reference_dbhz: float) -> float:
    cn0_factor = 1.0
    if cn0_dbhz is not None and cn0_dbhz > 0.0:
        cn0_factor = max(0.45, min(4.0, 10.0 ** ((cn0_reference_dbhz - cn0_dbhz) / 20.0)))
    sin_el = max(0.20, math.sin(math.radians(max(-5.0, elevation_deg))))
    elevation_factor = 1.0 / sin_el
    return max(0.5, min(50.0, base_sigma_m * cn0_factor * elevation_factor))


def prepare_observation(
    obs: Observation,
    reference: ReceiverPosition,
    ephemerides: dict[str, list[Ephemeris]],
    args: argparse.Namespace,
    windows: list[AttackWindow],
    first_stamp: float,
    selected_attack_sats: set[str],
) -> PreparedObservation | None:
    week, tow_s = unix_to_gps_week_tow(obs.stamp, args.gps_utc_leap_seconds)
    observed_pseudorange_m = obs.pseudorange_m
    eph = select_ephemeris(ephemerides, obs.sat_id, week, tow_s)
    if eph is None:
        return None

    transmit_tow_s = tow_s - observed_pseudorange_m / SPEED_OF_LIGHT_MPS
    sat_x, sat_y, sat_z, sat_clock_s = satellite_position_clock(eph, week, transmit_tow_s)
    sat_x, sat_y, sat_z = rotate_satellite_for_earth_rotation(
        sat_x,
        sat_y,
        sat_z,
        observed_pseudorange_m / SPEED_OF_LIGHT_MPS,
    )

    dx = sat_x - reference.x_m
    dy = sat_y - reference.y_m
    dz = sat_z - reference.z_m
    reference_range_m = norm3(dx, dy, dz)
    if reference_range_m <= 1.0:
        return None
    elevation_deg, azimuth_deg = elevation_azimuth(reference, (sat_x, sat_y, sat_z))

    direct_scale = attack_scale(obs.stamp, obs.stamp - first_stamp, windows, args.attack_ramp_s)
    direct_bias_m = 0.0
    if direct_scale > 0.0 and should_attack_satellite(obs.sat_id, args.attack_satellite_mode, selected_attack_sats):
        east_m, north_m, up_m = parse_vec3(args.attack_offset_enu_m, "--attack-offset-enu-m")
        lat, lon, _ = ecef_to_geodetic(reference.x_m, reference.y_m, reference.z_m)
        offset_x, offset_y, offset_z = enu_to_ecef_vector(east_m, north_m, up_m, lat, lon)
        line_of_sight = (dx / reference_range_m, dy / reference_range_m, dz / reference_range_m)
        position_attack_m = -(
            line_of_sight[0] * offset_x + line_of_sight[1] * offset_y + line_of_sight[2] * offset_z
        )
        direct_bias_m = direct_scale * (args.attack_common_delay_m + position_attack_m)
        observed_pseudorange_m += direct_bias_m

    sigma_m = measurement_sigma(obs.cn0_dbhz, elevation_deg, args.measurement_sigma_m, args.cn0_reference_dbhz)
    return PreparedObservation(
        obs=obs,
        observed_pseudorange_m=observed_pseudorange_m,
        sat_x_m=sat_x,
        sat_y_m=sat_y,
        sat_z_m=sat_z,
        sat_clock_s=sat_clock_s,
        reference_range_m=reference_range_m,
        elevation_deg=elevation_deg,
        azimuth_deg=azimuth_deg,
        sigma_m=sigma_m,
        weight=1.0 / max(1e-9, sigma_m * sigma_m),
        direct_attack_bias_m=direct_bias_m,
        attack_scale=max(obs.attack_scale, direct_scale),
        doppler_range_rate_mps=obs.doppler_range_rate_mps,
        carrier_phase_m=obs.carrier_phase_m,
    )


def solve_linear_system(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    augmented = [row[:] + [b[index]] for index, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        for j in range(col, n + 1):
            augmented[col][j] /= divisor
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if abs(factor) < 1e-18:
                continue
            for j in range(col, n + 1):
                augmented[row][j] -= factor * augmented[col][j]
    return [augmented[row][n] for row in range(n)]


def solve_wls(observations: list[PreparedObservation], reference: ReceiverPosition) -> WlsSolution:
    if len(observations) < 4:
        return WlsSolution(False, reference.x_m, reference.y_m, reference.z_m, 0.0, 0, [])

    x_m, y_m, z_m = reference.x_m, reference.y_m, reference.z_m
    initial_preclock = []
    for item in observations:
        rho_m = norm3(item.sat_x_m - x_m, item.sat_y_m - y_m, item.sat_z_m - z_m)
        initial_preclock.append(item.observed_pseudorange_m - (rho_m - SPEED_OF_LIGHT_MPS * item.sat_clock_s))
    clock_bias_m = median(initial_preclock) if initial_preclock else 0.0
    iterations = 0

    for iteration in range(8):
        normal = [[0.0 for _ in range(4)] for _ in range(4)]
        rhs = [0.0 for _ in range(4)]
        for item in observations:
            dx = item.sat_x_m - x_m
            dy = item.sat_y_m - y_m
            dz = item.sat_z_m - z_m
            rho_m = max(1.0, norm3(dx, dy, dz))
            predicted_m = rho_m + clock_bias_m - SPEED_OF_LIGHT_MPS * item.sat_clock_s
            residual_m = item.observed_pseudorange_m - predicted_m
            h = [(x_m - item.sat_x_m) / rho_m, (y_m - item.sat_y_m) / rho_m, (z_m - item.sat_z_m) / rho_m, 1.0]
            for row in range(4):
                rhs[row] += item.weight * h[row] * residual_m
                for col in range(4):
                    normal[row][col] += item.weight * h[row] * h[col]
        delta = solve_linear_system(normal, rhs)
        if delta is None:
            return WlsSolution(False, x_m, y_m, z_m, clock_bias_m, iteration, [])
        x_m += delta[0]
        y_m += delta[1]
        z_m += delta[2]
        clock_bias_m += delta[3]
        iterations = iteration + 1
        if norm3(delta[0], delta[1], delta[2]) < 1e-4 and abs(delta[3]) < 1e-4:
            break

    residuals = []
    for item in observations:
        rho_m = norm3(item.sat_x_m - x_m, item.sat_y_m - y_m, item.sat_z_m - z_m)
        predicted_m = rho_m + clock_bias_m - SPEED_OF_LIGHT_MPS * item.sat_clock_s
        residuals.append(item.observed_pseudorange_m - predicted_m)
    return WlsSolution(True, x_m, y_m, z_m, clock_bias_m, iterations, residuals)


def median(values: Iterable[float]) -> float:
    vals = sorted(values)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def weighted_mean(values: list[float], weights: list[float]) -> float:
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return sum(values) / len(values) if values else 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def rms(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return math.sqrt(sum(value * value for value in vals) / len(vals))


def chi_square_threshold(dof: int, pfa: float) -> float:
    if dof <= 0:
        return 0.0
    probability = max(1e-9, min(1.0 - 1e-9, 1.0 - pfa))
    z = NormalDist().inv_cdf(probability)
    # Wilson-Hilferty approximation. It is accurate enough for transparent
    # baseline calibration and avoids a SciPy dependency.
    return dof * (1.0 - 2.0 / (9.0 * dof) + z * math.sqrt(2.0 / (9.0 * dof))) ** 3


def residual_stats(residuals: list[float], sigmas: list[float], dof: int, pfa: float, outlier_sigma: float, outlier_abs_m: float) -> dict[str, float | int]:
    if not residuals:
        threshold = chi_square_threshold(dof, pfa)
        return {
            "degrees_of_freedom": dof,
            "chi_square": 0.0,
            "threshold": threshold,
            "score": 0.0,
            "detected": 0,
            "residual_rms_m": 0.0,
            "weighted_rms": 0.0,
            "max_abs_m": 0.0,
            "abs_mean_m": 0.0,
            "outlier_count": 0,
        }
    normalized = [residual / max(1e-9, sigma) for residual, sigma in zip(residuals, sigmas)]
    chi_square = sum(value * value for value in normalized)
    threshold = chi_square_threshold(dof, pfa)
    score = chi_square / threshold if threshold > 0.0 else 0.0
    return {
        "degrees_of_freedom": dof,
        "chi_square": chi_square,
        "threshold": threshold,
        "score": score,
        "detected": 1 if threshold > 0.0 and chi_square >= threshold else 0,
        "residual_rms_m": rms(residuals),
        "weighted_rms": rms(normalized),
        "max_abs_m": max(abs(value) for value in residuals),
        "abs_mean_m": sum(abs(value) for value in residuals) / len(residuals),
        "outlier_count": sum(1 for residual, sigma in zip(residuals, sigmas) if abs(residual) >= max(outlier_abs_m, outlier_sigma * sigma)),
    }


def rate_stats(residuals: list[float]) -> dict[str, float | int]:
    if not residuals:
        return {
            "count": 0,
            "rms": 0.0,
            "abs_mean": 0.0,
            "max_abs": 0.0,
        }
    return {
        "count": len(residuals),
        "rms": rms(residuals),
        "abs_mean": sum(abs(value) for value in residuals) / len(residuals),
        "max_abs": max(abs(value) for value in residuals),
    }


def group_by_epoch(observations: list[Observation]) -> dict[tuple[float, int], list[Observation]]:
    grouped: dict[tuple[float, int], list[Observation]] = {}
    for obs in observations:
        grouped.setdefault((obs.stamp, obs.epoch_index), []).append(obs)
    return grouped


def process_epochs(
    observations: list[Observation],
    ephemerides: dict[str, list[Ephemeris]],
    positions: list[ReceiverPosition],
    fallback_position: ReceiverPosition | None,
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    grouped = group_by_epoch(observations)
    if not grouped:
        raise SystemExit("No pseudorange observations found.")
    first_stamp = min(stamp for stamp, _epoch in grouped)
    windows = parse_windows(args.attack_window)
    selected_attack_sats = {item.strip() for item in args.attack_satellites.split(",") if item.strip()}

    satellite_rows: list[dict[str, object]] = []
    epoch_rows: list[dict[str, object]] = []
    skipped_epochs = 0
    no_reference_epochs = 0
    supported_systems = {"G"}
    unsupported_system_counts: dict[str, int] = {}
    previous_satellite_state: dict[str, dict[str, float]] = {}

    for (stamp, epoch_index) in sorted(grouped):
        epoch_observations = grouped[(stamp, epoch_index)]
        for obs in epoch_observations:
            if obs.sat_id[:1] not in supported_systems:
                unsupported_system_counts[obs.sat_id[:1]] = unsupported_system_counts.get(obs.sat_id[:1], 0) + 1
        reference = nearest_position(positions, stamp, args.max_delta_s, fallback_position)
        if reference is None:
            no_reference_epochs += 1
            continue

        prepared_all = [
            prepare_observation(
                obs,
                reference,
                ephemerides,
                args,
                windows,
                first_stamp,
                selected_attack_sats,
            )
            for obs in epoch_observations
        ]
        prepared_all = [item for item in prepared_all if item is not None]
        prepared = [item for item in prepared_all if item.elevation_deg >= args.elevation_mask_deg]
        if len(prepared) < args.min_satellites:
            skipped_epochs += 1
            continue

        sigmas = [item.sigma_m for item in prepared]
        preclock_residuals = [
            item.observed_pseudorange_m - (item.reference_range_m - SPEED_OF_LIGHT_MPS * item.sat_clock_s)
            for item in prepared
        ]
        reference_clock_bias_m = weighted_mean(preclock_residuals, [item.weight for item in prepared])
        reference_residuals = [value - reference_clock_bias_m for value in preclock_residuals]
        reference_stats = residual_stats(
            reference_residuals,
            sigmas,
            max(1, len(reference_residuals) - 1),
            args.raim_pfa,
            args.outlier_sigma,
            args.outlier_abs_m,
        )

        wls = solve_wls(prepared, reference)
        raim_stats = residual_stats(
            wls.residuals_m,
            sigmas,
            max(1, len(wls.residuals_m) - 4),
            args.raim_pfa,
            args.outlier_sigma,
            args.outlier_abs_m,
        )
        lat, lon, _ = ecef_to_geodetic(reference.x_m, reference.y_m, reference.z_m)
        wls_de = wls_dn = wls_du = wls_norm = 0.0
        if wls.valid:
            wls_de, wls_dn, wls_du = ecef_to_enu_vector(wls.x_m - reference.x_m, wls.y_m - reference.y_m, wls.z_m - reference.z_m, lat, lon)
            wls_norm = norm3(wls_de, wls_dn, wls_du)

        doppler_residuals: list[float] = []
        tdcp_residuals: list[float] = []
        rate_by_sat: dict[str, dict[str, float]] = {}
        for item in prepared:
            previous = previous_satellite_state.get(item.obs.sat_id)
            predicted_range_rate_mps = None
            tdcp_range_rate_mps = None
            doppler_residual_mps = None
            tdcp_residual_mps = None
            if previous is not None:
                dt = stamp - previous["stamp"]
                if dt > 1e-6:
                    predicted_range_rate_mps = (item.reference_range_m - previous["reference_range_m"]) / dt
                    if item.doppler_range_rate_mps is not None:
                        doppler_residual_mps = item.doppler_range_rate_mps - predicted_range_rate_mps
                        doppler_residuals.append(doppler_residual_mps)
                    if item.carrier_phase_m is not None and "carrier_phase_m" in previous:
                        tdcp_range_rate_mps = (item.carrier_phase_m - previous["carrier_phase_m"]) / dt
                        tdcp_residual_mps = tdcp_range_rate_mps - predicted_range_rate_mps
                        tdcp_residuals.append(tdcp_residual_mps)
            state = {"stamp": stamp, "reference_range_m": item.reference_range_m}
            if item.carrier_phase_m is not None:
                state["carrier_phase_m"] = item.carrier_phase_m
            previous_satellite_state[item.obs.sat_id] = state
            rate_by_sat[item.obs.sat_id] = {
                "predicted_range_rate_mps": predicted_range_rate_mps,
                "doppler_range_rate_mps": item.doppler_range_rate_mps,
                "doppler_residual_mps": doppler_residual_mps,
                "tdcp_range_rate_mps": tdcp_range_rate_mps,
                "tdcp_residual_mps": tdcp_residual_mps,
            }
        doppler_stats = rate_stats(doppler_residuals)
        tdcp_stats = rate_stats(tdcp_residuals)

        attack_label = 1 if any(item.obs.attack_label or item.attack_scale > 1e-9 for item in prepared) else 0
        attacked_count = sum(
            1
            for item in prepared
            if item.obs.attack_label or abs(item.obs.injected_pseudorange_bias_m + item.direct_attack_bias_m) > 1e-9
        )
        row_by_sat = {item.obs.sat_id: idx for idx, item in enumerate(prepared)}
        used_systems = sorted({item.obs.sat_id[:1] for item in prepared})
        for item in prepared:
            sat_index = row_by_sat[item.obs.sat_id]
            rate_row = rate_by_sat.get(item.obs.sat_id, {})
            satellite_rows.append(
                {
                    "stamp": stamp,
                    "time_s": stamp - first_stamp,
                    "epoch_index": epoch_index,
                    "sat_id": item.obs.sat_id,
                    "code_type": item.obs.code_type,
                    "observed_pseudorange_m": item.observed_pseudorange_m,
                    "clean_pseudorange_m": item.obs.clean_pseudorange_m,
                    "injected_pseudorange_bias_m": item.obs.injected_pseudorange_bias_m + item.direct_attack_bias_m,
                    "attack_label": 1 if item.obs.attack_label or item.attack_scale > 1e-9 else 0,
                    "attack_scale": item.attack_scale,
                    "sat_x_m": item.sat_x_m,
                    "sat_y_m": item.sat_y_m,
                    "sat_z_m": item.sat_z_m,
                    "sat_clock_s": item.sat_clock_s,
                    "receiver_x_m": reference.x_m,
                    "receiver_y_m": reference.y_m,
                    "receiver_z_m": reference.z_m,
                    "reference_range_m": item.reference_range_m,
                    "elevation_deg": item.elevation_deg,
                    "azimuth_deg": item.azimuth_deg,
                    "cn0_dbhz": item.obs.cn0_dbhz,
                    "sigma_m": item.sigma_m,
                    "weight": item.weight,
                    "doppler_range_rate_mps": rate_row.get("doppler_range_rate_mps"),
                    "predicted_range_rate_mps": rate_row.get("predicted_range_rate_mps"),
                    "doppler_residual_mps": rate_row.get("doppler_residual_mps"),
                    "carrier_phase_m": item.carrier_phase_m,
                    "tdcp_range_rate_mps": rate_row.get("tdcp_range_rate_mps"),
                    "tdcp_residual_mps": rate_row.get("tdcp_residual_mps"),
                    "reference_clock_bias_m": reference_clock_bias_m,
                    "reference_residual_m": reference_residuals[sat_index],
                    "wls_residual_m": wls.residuals_m[sat_index] if wls.valid else None,
                }
            )

        epoch_rows.append(
            {
                "stamp": stamp,
                "time_s": stamp - first_stamp,
                "epoch_index": epoch_index,
                "gps_satellite_count": len(prepared_all),
                "used_systems": ",".join(used_systems),
                "used_system_count": len(used_systems),
                "used_satellite_count": len(prepared),
                "reference_quality": reference.quality,
                "mean_cn0_dbhz": sum(item.obs.cn0_dbhz for item in prepared if item.obs.cn0_dbhz is not None)
                / max(1, sum(1 for item in prepared if item.obs.cn0_dbhz is not None)),
                "min_elevation_deg": min(item.elevation_deg for item in prepared),
                "max_elevation_deg": max(item.elevation_deg for item in prepared),
                "attack_label": attack_label,
                "attack_scale": max(item.attack_scale for item in prepared),
                "attacked_satellite_count": attacked_count,
                "wls_valid": 1 if wls.valid else 0,
                "wls_ecef_x_m": wls.x_m,
                "wls_ecef_y_m": wls.y_m,
                "wls_ecef_z_m": wls.z_m,
                "wls_clock_bias_m": wls.clock_bias_m,
                "wls_iterations": wls.iterations,
                "wls_delta_e_m": wls_de,
                "wls_delta_n_m": wls_dn,
                "wls_delta_u_m": wls_du,
                "wls_delta_norm_m": wls_norm,
                "raim_degrees_of_freedom": raim_stats["degrees_of_freedom"],
                "raim_chi_square": raim_stats["chi_square"],
                "raim_threshold": raim_stats["threshold"],
                "raim_score": raim_stats["score"],
                "raim_detected": raim_stats["detected"],
                "raim_residual_rms_m": raim_stats["residual_rms_m"],
                "raim_weighted_rms": raim_stats["weighted_rms"],
                "raim_abs_mean_m": raim_stats["abs_mean_m"],
                "raim_max_abs_m": raim_stats["max_abs_m"],
                "raim_outlier_count": raim_stats["outlier_count"],
                "doppler_used_count": doppler_stats["count"],
                "doppler_rms": doppler_stats["rms"],
                "doppler_abs_mean": doppler_stats["abs_mean"],
                "doppler_max_abs": doppler_stats["max_abs"],
                "tdcp_valid_count": tdcp_stats["count"],
                "tdcp_rms": tdcp_stats["rms"],
                "tdcp_abs_mean": tdcp_stats["abs_mean"],
                "tdcp_max_abs": tdcp_stats["max_abs"],
                "reference_clock_bias_m": reference_clock_bias_m,
                "reference_degrees_of_freedom": reference_stats["degrees_of_freedom"],
                "reference_chi_square": reference_stats["chi_square"],
                "reference_threshold": reference_stats["threshold"],
                "reference_score": reference_stats["score"],
                "reference_detected": reference_stats["detected"],
                "reference_residual_rms_m": reference_stats["residual_rms_m"],
                "reference_weighted_rms": reference_stats["weighted_rms"],
                "reference_abs_mean_m": reference_stats["abs_mean_m"],
                "reference_max_abs_m": reference_stats["max_abs_m"],
                "reference_outlier_count": reference_stats["outlier_count"],
            }
        )

    summary = {
        "epochs_with_input": len(grouped),
        "epochs_written": len(epoch_rows),
        "satellite_rows_written": len(satellite_rows),
        "skipped_epochs": skipped_epochs,
        "no_reference_epochs": no_reference_epochs,
        "systems": sorted({obs.sat_id[0] for obs in observations}),
        "requested_systems": sorted(parse_systems(args.systems)),
        "supported_broadcast_systems": sorted(supported_systems),
        "unsupported_system_counts": unsupported_system_counts,
        "gps_ephemeris_satellites": len(ephemerides),
        "raim_pfa": args.raim_pfa,
        "elevation_mask_deg": args.elevation_mask_deg,
        "min_satellites": args.min_satellites,
    }
    return satellite_rows, epoch_rows, summary


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: fmt(row.get(column)) for column in columns})


def write_outputs(output_dir: Path, name: str, satellite_rows: list[dict[str, object]], epoch_rows: list[dict[str, object]], summary: dict[str, object]) -> tuple[Path, Path, Path]:
    satellite_csv = output_dir / f"{name}_raw_satellite_residuals.csv"
    epoch_csv = output_dir / f"{name}_raw_epoch_residuals.csv"
    summary_json = output_dir / f"{name}_raw_residual_summary.json"
    satellite_columns = [
        "stamp",
        "time_s",
        "epoch_index",
        "sat_id",
        "code_type",
        "observed_pseudorange_m",
        "clean_pseudorange_m",
        "injected_pseudorange_bias_m",
        "attack_label",
        "attack_scale",
        "sat_x_m",
        "sat_y_m",
        "sat_z_m",
        "sat_clock_s",
        "receiver_x_m",
        "receiver_y_m",
        "receiver_z_m",
        "reference_range_m",
        "elevation_deg",
        "azimuth_deg",
        "cn0_dbhz",
        "sigma_m",
        "weight",
        "doppler_range_rate_mps",
        "predicted_range_rate_mps",
        "doppler_residual_mps",
        "carrier_phase_m",
        "tdcp_range_rate_mps",
        "tdcp_residual_mps",
        "reference_clock_bias_m",
        "reference_residual_m",
        "wls_residual_m",
    ]
    epoch_columns = [
        "stamp",
        "time_s",
        "epoch_index",
        "gps_satellite_count",
        "used_systems",
        "used_system_count",
        "used_satellite_count",
        "reference_quality",
        "mean_cn0_dbhz",
        "min_elevation_deg",
        "max_elevation_deg",
        "attack_label",
        "attack_scale",
        "attacked_satellite_count",
        "wls_valid",
        "wls_ecef_x_m",
        "wls_ecef_y_m",
        "wls_ecef_z_m",
        "wls_clock_bias_m",
        "wls_iterations",
        "wls_delta_e_m",
        "wls_delta_n_m",
        "wls_delta_u_m",
        "wls_delta_norm_m",
        "raim_degrees_of_freedom",
        "raim_chi_square",
        "raim_threshold",
        "raim_score",
        "raim_detected",
        "raim_residual_rms_m",
        "raim_weighted_rms",
        "raim_abs_mean_m",
        "raim_max_abs_m",
        "raim_outlier_count",
        "doppler_used_count",
        "doppler_rms",
        "doppler_abs_mean",
        "doppler_max_abs",
        "tdcp_valid_count",
        "tdcp_rms",
        "tdcp_abs_mean",
        "tdcp_max_abs",
        "reference_clock_bias_m",
        "reference_degrees_of_freedom",
        "reference_chi_square",
        "reference_threshold",
        "reference_score",
        "reference_detected",
        "reference_residual_rms_m",
        "reference_weighted_rms",
        "reference_abs_mean_m",
        "reference_max_abs_m",
        "reference_outlier_count",
    ]
    write_csv(satellite_csv, satellite_rows, satellite_columns)
    write_csv(epoch_csv, epoch_rows, epoch_columns)
    summary = {
        **summary,
        "outputs": {
            "satellite_residuals_csv": str(satellite_csv),
            "epoch_residuals_csv": str(epoch_csv),
            "summary_json": str(summary_json),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return satellite_csv, epoch_csv, summary_json


def main() -> int:
    args = parse_args()
    systems = parse_systems(args.systems)
    if systems - {"G"}:
        print("warning: broadcast residuals currently support GPS/G; non-G observations are tracked as unsupported framework inputs.")
    nav_path = clean_path(args.nav)
    assert nav_path is not None
    output_dir = clean_path(args.output_dir)
    assert output_dir is not None
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.satellite_features:
        observations = load_observations_from_satellite_features(clean_path(args.satellite_features), systems, args.max_epochs)
    elif args.obs:
        observations = load_observations_from_rinex(clean_path(args.obs), args.gps_utc_leap_seconds, systems, args.max_epochs)
    else:
        raise SystemExit("Provide --obs or --satellite-features.")

    ephemerides = parse_navigation_file(nav_path)
    positions = read_rtklib_pos(clean_path(args.rtklib_pos), args.gps_utc_leap_seconds)
    fallback_position = parse_receiver_ecef(args.receiver_ecef)
    satellite_rows, epoch_rows, summary = process_epochs(observations, ephemerides, positions, fallback_position, args)
    satellite_csv, epoch_csv, summary_json = write_outputs(output_dir, args.name, satellite_rows, epoch_rows, summary)

    print("Raw GNSS residuals computed")
    print(f"  epochs: {summary['epochs_written']} / {summary['epochs_with_input']}")
    print(f"  satellite rows: {summary['satellite_rows_written']}")
    print(f"  satellite residuals: {satellite_csv}")
    print(f"  epoch residuals: {epoch_csv}")
    print(f"  summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
