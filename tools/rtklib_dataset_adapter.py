#!/usr/bin/env python3
"""Convert RTKLIB position results into flight-sim scenario/replay files."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable


WGS84_A_M = 6378137.0
WGS84_E2 = 6.69437999014e-3
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RtkPosition:
    gps_week: int
    tow_s: float
    ecef_x_m: float
    ecef_y_m: float
    ecef_z_m: float
    quality: int
    satellites: int
    sdx_m: float
    sdy_m: float
    sdz_m: float
    ratio: float


@dataclass
class DopSample:
    tow_s: float
    nsat: int
    gdop: float
    pdop: float
    hdop: float
    vdop: float


@dataclass
class EnuSample:
    time_s: float
    east_m: float
    north_m: float
    up_m: float
    sim_z_m: float
    yaw_rad: float
    quality: int
    satellites: int
    ratio: float
    sdx_m: float
    sdy_m: float
    sdz_m: float
    gdop: float
    pdop: float
    hdop: float
    vdop: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adapt a RTKLIB .pos dataset to f7_sim waypoint/scenario/replay files.",
    )
    parser.add_argument("--pos", required=True, help="RTKLIB .pos file.")
    parser.add_argument("--dop", help="Optional dop.txt file.")
    parser.add_argument("--name", default="rtklib_dataset", help="Output file prefix.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "build" / "datasets" / "rtklib_dataset"),
        help="Directory for generated files.",
    )
    parser.add_argument("--waypoint-stride", type=int, default=5, help="Use every Nth RTK sample as a waypoint.")
    parser.add_argument("--dt", type=float, default=0.01, help="Simulation dt written to the generated scenario.")
    parser.add_argument(
        "--takeoff-duration",
        type=float,
        default=4.0,
        help="Seconds inserted before the RTK route so the simulated vehicle can climb from ground.",
    )
    parser.add_argument(
        "--flight-altitude",
        type=float,
        default=1.8,
        help="Constant altitude used for the simulated vehicle route.",
    )
    parser.add_argument(
        "--preserve-altitude",
        action="store_true",
        help="Use RTK local up as the simulated z coordinate instead of a constant flight altitude.",
    )
    parser.add_argument(
        "--origin",
        choices=["first", "first-fixed"],
        default="first-fixed",
        help="ENU origin selection.",
    )
    parser.add_argument("--attack-start", type=float, help="Optional synthetic GPS attack start time for scenario.")
    parser.add_argument("--attack-end", type=float, help="Optional synthetic GPS attack end time for scenario.")
    parser.add_argument("--attack-offset", default="3.0,-1.5,0.6", help="Synthetic attack offset x,y,z in meters.")
    parser.add_argument("--pseudorange-delay", type=float, default=6.0, help="Synthetic pseudorange delay in meters.")
    parser.add_argument("--attack-ramp", type=float, default=1.5, help="Synthetic attack ramp duration in seconds.")
    return parser.parse_args()


def parse_rtklib_pos(path: Path) -> list[RtkPosition]:
    rows: list[RtkPosition] = []
    with path.open(errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            fields = line.split()
            if len(fields) < 15:
                continue
            rows.append(
                RtkPosition(
                    gps_week=int(fields[0]),
                    tow_s=float(fields[1]),
                    ecef_x_m=float(fields[2]),
                    ecef_y_m=float(fields[3]),
                    ecef_z_m=float(fields[4]),
                    quality=int(fields[5]),
                    satellites=int(fields[6]),
                    sdx_m=float(fields[7]),
                    sdy_m=float(fields[8]),
                    sdz_m=float(fields[9]),
                    ratio=float(fields[14]),
                )
            )
    if not rows:
        raise SystemExit(f"No RTKLIB position rows found in {path}")
    return rows


def parse_dop(path: Path | None, first_tow_s: float) -> dict[int, DopSample]:
    if path is None or not path.exists():
        return {}

    samples: dict[int, DopSample] = {}
    with path.open(errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            fields = line.split()
            if len(fields) < 10:
                continue
            try:
                hour, minute, sec_text = fields[1].split(":")
                sec = float(sec_text)
                day_s = int(hour) * 3600 + int(minute) * 60 + sec
                first_day_s = first_tow_s % 86400.0
                tow_s = first_tow_s + (day_s - first_day_s)
                samples[int(round(tow_s))] = DopSample(
                    tow_s=tow_s,
                    nsat=int(fields[2]),
                    gdop=float(fields[-4]),
                    pdop=float(fields[-3]),
                    hdop=float(fields[-2]),
                    vdop=float(fields[-1]),
                )
            except (ValueError, IndexError):
                continue
    return samples


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


def select_origin(rows: list[RtkPosition], mode: str) -> RtkPosition:
    if mode == "first-fixed":
        for row in rows:
            if row.quality == 1:
                return row
    return rows[0]


def parse_attack_offset(value: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise SystemExit("--attack-offset must be x,y,z")
    return float(parts[0]), float(parts[1]), float(parts[2])


def compute_yaws(points: list[tuple[float, float]]) -> list[float]:
    yaws: list[float] = []
    last_yaw = 0.0
    for i, (east, north) in enumerate(points):
        if i + 1 < len(points):
            ne, nn = points[i + 1]
            de = ne - east
            dn = nn - north
        elif i > 0:
            pe, pn = points[i - 1]
            de = east - pe
            dn = north - pn
        else:
            de = 0.0
            dn = 0.0
        if math.hypot(de, dn) > 0.05:
            last_yaw = math.atan2(dn, de)
        yaws.append(last_yaw)
    return yaws


def make_enu_samples(
    rows: list[RtkPosition],
    dop: dict[int, DopSample],
    *,
    origin_mode: str,
    flight_altitude_m: float,
    preserve_altitude: bool,
) -> tuple[list[EnuSample], dict[str, float]]:
    origin = select_origin(rows, origin_mode)
    origin_ecef = (origin.ecef_x_m, origin.ecef_y_m, origin.ecef_z_m)
    origin_llh = ecef_to_geodetic(*origin_ecef)
    first_tow = rows[0].tow_s

    enu_xyz: list[tuple[float, float, float]] = [
        ecef_to_enu(row.ecef_x_m, row.ecef_y_m, row.ecef_z_m, origin_ecef, origin_llh)
        for row in rows
    ]
    yaws = compute_yaws([(east, north) for east, north, _ in enu_xyz])

    samples: list[EnuSample] = []
    for row, (east, north, up), yaw in zip(rows, enu_xyz, yaws):
        dop_sample = dop.get(int(round(row.tow_s)))
        samples.append(
            EnuSample(
                time_s=row.tow_s - first_tow,
                east_m=east,
                north_m=north,
                up_m=up,
                sim_z_m=up if preserve_altitude else flight_altitude_m,
                yaw_rad=yaw,
                quality=row.quality,
                satellites=row.satellites,
                ratio=row.ratio,
                sdx_m=row.sdx_m,
                sdy_m=row.sdy_m,
                sdz_m=row.sdz_m,
                gdop=dop_sample.gdop if dop_sample else 0.0,
                pdop=dop_sample.pdop if dop_sample else 0.0,
                hdop=dop_sample.hdop if dop_sample else 0.0,
                vdop=dop_sample.vdop if dop_sample else 0.0,
            )
        )

    origin_summary = {
        "origin_ecef_x_m": origin.ecef_x_m,
        "origin_ecef_y_m": origin.ecef_y_m,
        "origin_ecef_z_m": origin.ecef_z_m,
        "origin_lat_deg": math.degrees(origin_llh[0]),
        "origin_lon_deg": math.degrees(origin_llh[1]),
        "origin_alt_m": origin_llh[2],
    }
    return samples, origin_summary


def write_waypoints(path: Path, samples: list[EnuSample], stride: int, takeoff_duration_s: float) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    stride = max(1, stride)
    selected = samples[::stride]
    if selected[-1].time_s != samples[-1].time_s:
        selected.append(samples[-1])

    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s", "x", "y", "z", "yaw_rad"])
        if takeoff_duration_s > 1e-6:
            first = samples[0]
            writer.writerow(
                [
                    "0.000",
                    f"{first.east_m:.6f}",
                    f"{first.north_m:.6f}",
                    "0.000000",
                    f"{first.yaw_rad:.9f}",
                ]
            )
            writer.writerow(
                [
                    f"{takeoff_duration_s:.3f}",
                    f"{first.east_m:.6f}",
                    f"{first.north_m:.6f}",
                    f"{first.sim_z_m:.6f}",
                    f"{first.yaw_rad:.9f}",
                ]
            )
        route_samples = selected[1:] if takeoff_duration_s > 1e-6 and len(selected) > 1 else selected
        for sample in route_samples:
            t = sample.time_s + max(0.0, takeoff_duration_s)
            writer.writerow(
                [
                    f"{t:.3f}",
                    f"{sample.east_m:.6f}",
                    f"{sample.north_m:.6f}",
                    f"{sample.sim_z_m:.6f}",
                    f"{sample.yaw_rad:.9f}",
                ]
            )
    skipped = 1 if takeoff_duration_s > 1e-6 and len(selected) > 1 else 0
    return len(selected) - skipped + (2 if takeoff_duration_s > 1e-6 else 0)


def velocity_between(samples: list[EnuSample], index: int) -> tuple[float, float, float]:
    if len(samples) == 1:
        return 0.0, 0.0, 0.0
    if index == 0:
        a = samples[0]
        b = samples[1]
    elif index == len(samples) - 1:
        a = samples[-2]
        b = samples[-1]
    else:
        a = samples[index - 1]
        b = samples[index + 1]
    dt = max(1e-6, b.time_s - a.time_s)
    return (b.east_m - a.east_m) / dt, (b.north_m - a.north_m) / dt, (b.sim_z_m - a.sim_z_m) / dt


def write_replay_csv(path: Path, samples: list[EnuSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "time_s",
        "true_x",
        "true_y",
        "true_z",
        "true_vx",
        "true_vy",
        "true_vz",
        "est_x",
        "est_y",
        "est_z",
        "est_vx",
        "est_vy",
        "est_vz",
        "gps_x",
        "gps_y",
        "gps_z",
        "uwb_x",
        "uwb_y",
        "uwb_z",
        "flow_vx",
        "flow_vy",
        "mag_yaw",
        "uwb_valid",
        "flow_valid",
        "mag_valid",
        "ref_x",
        "ref_y",
        "ref_z",
        "attack_active",
        "detected",
        "residual_norm",
        "pseudorange_residual_mean",
        "pseudorange_residual_rms",
        "pseudorange_residual_max_abs",
        "glrt_statistic",
        "glrt_threshold",
        "glrt_false_alarm_rate",
        "glrt_detected",
        "pseudorange_satellites",
        "flight_mode",
        "gps_trusted",
        "accel_bias_x",
        "accel_bias_y",
        "accel_bias_z",
        "disturbance_x",
        "disturbance_y",
        "disturbance_z",
        "thrust_n",
        "moment_x",
        "moment_y",
        "moment_z",
        "rtk_quality",
        "rtk_ratio",
        "rtk_satellites",
        "dop_gdop",
        "dop_pdop",
        "dop_hdop",
        "dop_vdop",
        "dataset_up_m",
        "sdx_m",
        "sdy_m",
        "sdz_m",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for i, sample in enumerate(samples):
            vx, vy, vz = velocity_between(samples, i)
            mode = "RTK Fixed" if sample.quality == 1 else "RTK Float" if sample.quality == 2 else f"RTK Q{sample.quality}"
            trusted = sample.quality == 1
            common = {
                "time_s": f"{sample.time_s:.3f}",
                "true_x": f"{sample.east_m:.6f}",
                "true_y": f"{sample.north_m:.6f}",
                "true_z": f"{sample.sim_z_m:.6f}",
                "true_vx": f"{vx:.6f}",
                "true_vy": f"{vy:.6f}",
                "true_vz": f"{vz:.6f}",
                "est_x": f"{sample.east_m:.6f}",
                "est_y": f"{sample.north_m:.6f}",
                "est_z": f"{sample.sim_z_m:.6f}",
                "est_vx": f"{vx:.6f}",
                "est_vy": f"{vy:.6f}",
                "est_vz": f"{vz:.6f}",
                "gps_x": f"{sample.east_m:.6f}",
                "gps_y": f"{sample.north_m:.6f}",
                "gps_z": f"{sample.sim_z_m:.6f}",
                "uwb_x": f"{sample.east_m:.6f}",
                "uwb_y": f"{sample.north_m:.6f}",
                "uwb_z": f"{sample.sim_z_m:.6f}",
                "flow_vx": f"{vx:.6f}",
                "flow_vy": f"{vy:.6f}",
                "mag_yaw": f"{sample.yaw_rad:.9f}",
                "uwb_valid": "0",
                "flow_valid": "1",
                "mag_valid": "1",
                "ref_x": f"{sample.east_m:.6f}",
                "ref_y": f"{sample.north_m:.6f}",
                "ref_z": f"{sample.sim_z_m:.6f}",
                "attack_active": "0",
                "detected": "0",
                "residual_norm": "0",
                "pseudorange_residual_mean": "0",
                "pseudorange_residual_rms": "0",
                "pseudorange_residual_max_abs": "0",
                "glrt_statistic": "0",
                "glrt_threshold": "0",
                "glrt_false_alarm_rate": "0",
                "glrt_detected": "0",
                "pseudorange_satellites": str(sample.satellites),
                "flight_mode": mode,
                "gps_trusted": "1" if trusted else "0",
                "accel_bias_x": "0",
                "accel_bias_y": "0",
                "accel_bias_z": "0",
                "disturbance_x": "0",
                "disturbance_y": "0",
                "disturbance_z": "0",
                "thrust_n": "0",
                "moment_x": "0",
                "moment_y": "0",
                "moment_z": "0",
                "rtk_quality": str(sample.quality),
                "rtk_ratio": f"{sample.ratio:.3f}",
                "rtk_satellites": str(sample.satellites),
                "dop_gdop": f"{sample.gdop:.3f}",
                "dop_pdop": f"{sample.pdop:.3f}",
                "dop_hdop": f"{sample.hdop:.3f}",
                "dop_vdop": f"{sample.vdop:.3f}",
                "dataset_up_m": f"{sample.up_m:.6f}",
                "sdx_m": f"{sample.sdx_m:.6f}",
                "sdy_m": f"{sample.sdy_m:.6f}",
                "sdz_m": f"{sample.sdz_m:.6f}",
            }
            writer.writerow(common)


def relpath_for_scenario(path: Path, scenario_dir: Path) -> str:
    try:
        return str(path.relative_to(scenario_dir))
    except ValueError:
        return str(path)


def write_scenario(
    path: Path,
    waypoint_path: Path,
    sim_output_csv: Path,
    sim_output_html: Path,
    samples: list[EnuSample],
    args: argparse.Namespace,
) -> None:
    takeoff_duration_s = max(0.0, args.takeoff_duration)
    duration_s = samples[-1].time_s + takeoff_duration_s + 5.0
    if args.attack_start is None or args.attack_end is None:
        attack_start = duration_s + 1000.0
        attack_end = duration_s + 1001.0
    else:
        attack_start = args.attack_start
        attack_end = args.attack_end
    ox, oy, oz = parse_attack_offset(args.attack_offset)

    with path.open("w") as handle:
        handle.write("# Generated by tools/rtklib_dataset_adapter.py\n")
        handle.write(f"duration_s={duration_s:.3f}\n")
        handle.write(f"dt_s={args.dt:.6f}\n")
        handle.write(f"output_csv={sim_output_csv}\n")
        handle.write(f"output_html={sim_output_html}\n")
        handle.write("write_html=true\n")
        handle.write(f"trajectory_file={relpath_for_scenario(waypoint_path, path.parent)}\n")
        handle.write(f"attack_start_s={attack_start:.3f}\n")
        handle.write(f"attack_end_s={attack_end:.3f}\n")
        handle.write(f"attack_offset_m={ox:.6f},{oy:.6f},{oz:.6f}\n")
        handle.write(f"pseudorange_delay_m={args.pseudorange_delay:.6f}\n")
        handle.write(f"attack_ramp_s={args.attack_ramp:.6f}\n")
        handle.write("glrt_false_alarm_rate=0.001\n")
        handle.write("consecutive_samples=2\n")
        handle.write("enable_uwb=true\n")
        handle.write("enable_optical_flow=true\n")
        handle.write("enable_magnetometer=true\n")


def sample_range(values: Iterable[float]) -> dict[str, float]:
    values = list(values)
    return {"min": min(values), "max": max(values), "span": max(values) - min(values)}


def write_summary(path: Path, samples: list[EnuSample], origin_summary: dict[str, float], outputs: dict[str, str]) -> None:
    quality_counts: dict[str, int] = {}
    for sample in samples:
        quality_counts[str(sample.quality)] = quality_counts.get(str(sample.quality), 0) + 1

    summary = {
        "samples": len(samples),
        "duration_s": samples[-1].time_s - samples[0].time_s,
        "east_m": sample_range(sample.east_m for sample in samples),
        "north_m": sample_range(sample.north_m for sample in samples),
        "dataset_up_m": sample_range(sample.up_m for sample in samples),
        "sim_z_m": sample_range(sample.sim_z_m for sample in samples),
        "quality_counts": quality_counts,
        "satellites": sample_range(sample.satellites for sample in samples),
        "origin": origin_summary,
        "outputs": outputs,
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    pos_path = Path(args.pos).expanduser().resolve()
    dop_path = Path(args.dop).expanduser().resolve() if args.dop else None
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = parse_rtklib_pos(pos_path)
    dop = parse_dop(dop_path, rows[0].tow_s)
    samples, origin_summary = make_enu_samples(
        rows,
        dop,
        origin_mode=args.origin,
        flight_altitude_m=args.flight_altitude,
        preserve_altitude=args.preserve_altitude,
    )

    waypoint_path = output_dir / f"{args.name}_waypoints.csv"
    replay_path = output_dir / f"{args.name}_replay.csv"
    scenario_path = output_dir / f"{args.name}.scenario"
    sim_output_csv = output_dir / f"{args.name}_sim.csv"
    sim_output_html = output_dir / f"{args.name}_sim.html"
    summary_path = output_dir / f"{args.name}_summary.json"

    waypoint_count = write_waypoints(waypoint_path, samples, args.waypoint_stride, args.takeoff_duration)
    write_replay_csv(replay_path, samples)
    write_scenario(scenario_path, waypoint_path, sim_output_csv, sim_output_html, samples, args)
    write_summary(
        summary_path,
        samples,
        origin_summary,
        {
            "waypoints": str(waypoint_path),
            "replay_csv": str(replay_path),
            "scenario": str(scenario_path),
            "sim_output_csv": str(sim_output_csv),
            "sim_output_html": str(sim_output_html),
        },
    )

    print("RTKLIB dataset adapted")
    print(f"  samples: {len(samples)}")
    print(f"  waypoints: {waypoint_count}")
    print(f"  duration: {samples[-1].time_s:.1f} s")
    print(f"  scenario: {scenario_path}")
    print(f"  replay: {replay_path}")
    print(f"  summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
