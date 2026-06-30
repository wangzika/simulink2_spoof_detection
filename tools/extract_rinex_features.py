#!/usr/bin/env python3
"""Extract per-satellite and per-epoch features from RINEX 3/4 observation files."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Iterable


GPS_EPOCH_UNIX_S = 315964800.0
SPEED_OF_LIGHT_MPS = 299792458.0
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ObservationValue:
    obs_type: str
    value: float | None
    lli: int | None
    ssi: int | None


@dataclass
class SatelliteRecord:
    sat_id: str
    values: list[ObservationValue]


@dataclass
class EpochRecord:
    stamp: float
    time_s: float
    flag: int
    receiver_clock_offset_s: float
    satellites: list[SatelliteRecord]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract RINEX observation features for GNSS spoof-detection studies.")
    parser.add_argument("--obs", required=True, help="RINEX observation file, e.g. rover.obs.")
    parser.add_argument("--name", default="rinex_obs", help="Output file prefix.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "build" / "paper_platform" / "rinex_features"),
        help="Output directory.",
    )
    parser.add_argument("--gps-utc-leap-seconds", type=float, default=18.0)
    parser.add_argument("--max-epochs", type=int, default=0, help="Optional limit for fast smoke tests.")
    parser.add_argument(
        "--systems",
        default="",
        help="Optional comma-separated GNSS systems to keep, e.g. G,E,C. Empty keeps all.",
    )
    return parser.parse_args()


def clean_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_float(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text.replace("D", "E"))
    except ValueError:
        return None


def parse_int_char(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def gpst_datetime_to_unix(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: float,
    leap_seconds: float,
) -> float:
    whole_second = int(math.floor(second))
    microsecond = int(round((second - whole_second) * 1_000_000.0))
    if microsecond >= 1_000_000:
        whole_second += 1
        microsecond -= 1_000_000
    dt = datetime(year, month, day, hour, minute, whole_second, microsecond, tzinfo=timezone.utc)
    return dt.timestamp() - leap_seconds


def parse_obs_types(header_lines: list[str]) -> dict[str, list[str]]:
    obs_types: dict[str, list[str]] = {}
    current_system: str | None = None
    expected_count = 0
    for line in header_lines:
        label = line[60:].strip() if len(line) >= 60 else ""
        if label != "SYS / # / OBS TYPES":
            continue
        body = line[:60]
        if body[:1].strip():
            parts = body.split()
            if len(parts) < 3:
                continue
            current_system = parts[0]
            try:
                expected_count = int(parts[1])
            except ValueError:
                expected_count = 0
            obs_types[current_system] = parts[2:]
        elif current_system:
            obs_types[current_system].extend(body.split())
        if current_system and expected_count > 0:
            obs_types[current_system] = obs_types[current_system][:expected_count]
    return obs_types


def parse_header(handle) -> tuple[list[str], dict[str, list[str]], dict[str, object]]:
    header_lines: list[str] = []
    metadata: dict[str, object] = {}
    for line in handle:
        header_lines.append(line.rstrip("\n"))
        label = line[60:].strip() if len(line) >= 60 else ""
        body = line[:60]
        if label == "RINEX VERSION / TYPE":
            metadata["rinex_version"] = body[:9].strip()
            metadata["file_type"] = body[20:21].strip()
            metadata["satellite_system"] = body[40:41].strip()
        elif label == "MARKER NAME":
            metadata["marker_name"] = body.strip()
        elif label == "REC # / TYPE / VERS":
            metadata["receiver"] = body.strip()
        elif label == "ANT # / TYPE":
            metadata["antenna"] = body.strip()
        elif label == "APPROX POSITION XYZ":
            parts = body.split()
            if len(parts) >= 3:
                metadata["approx_position_xyz_m"] = [float(parts[0]), float(parts[1]), float(parts[2])]
        elif label == "INTERVAL":
            value = parse_float(body)
            if value is not None:
                metadata["interval_s"] = value
        elif label == "LEAP SECONDS":
            value = parse_float(body)
            if value is not None:
                metadata["leap_seconds_header"] = value
        elif label == "END OF HEADER":
            break
    obs_types = parse_obs_types(header_lines)
    metadata["observation_types"] = obs_types
    return header_lines, obs_types, metadata


def parse_epoch_line(line: str, leap_seconds: float) -> tuple[float, int, int, float]:
    fields = line[1:].split()
    if len(fields) < 8:
        raise ValueError(f"Invalid RINEX epoch line: {line.rstrip()}")
    year = int(fields[0])
    month = int(fields[1])
    day = int(fields[2])
    hour = int(fields[3])
    minute = int(fields[4])
    second = float(fields[5])
    flag = int(fields[6])
    satellite_count = int(fields[7])
    receiver_clock_offset_s = float(fields[8]) if len(fields) > 8 else 0.0
    stamp = gpst_datetime_to_unix(year, month, day, hour, minute, second, leap_seconds)
    return stamp, flag, satellite_count, receiver_clock_offset_s


def parse_observation_fields(data: str, obs_types: list[str]) -> list[ObservationValue]:
    values: list[ObservationValue] = []
    for index, obs_type in enumerate(obs_types):
        field = data[index * 16 : (index + 1) * 16]
        values.append(
            ObservationValue(
                obs_type=obs_type,
                value=parse_float(field[:14]),
                lli=parse_int_char(field[14:15]),
                ssi=parse_int_char(field[15:16]),
            )
        )
    return values


def starts_new_observation_record(line: str) -> bool:
    if not line:
        return False
    if line.startswith(">"):
        return True
    return len(line) >= 3 and line[0].isalnum() and line[1:3].strip().isdigit()


def read_satellite_data(first_line: str, remaining_lines: list[str], index: int, obs_types: list[str]) -> tuple[str, int]:
    data = first_line[3:].rstrip("\n")
    required = len(obs_types) * 16
    while len(data) < required and index < len(remaining_lines):
        continuation = remaining_lines[index]
        if starts_new_observation_record(continuation):
            break
        data += continuation.rstrip("\n")
        index += 1
    return data, index


def iter_epochs(path: Path, leap_seconds: float, systems: set[str], max_epochs: int) -> tuple[list[EpochRecord], dict[str, object]]:
    epochs: list[EpochRecord] = []
    with path.open(errors="ignore") as handle:
        _header_lines, obs_types, metadata = parse_header(handle)
        remaining_lines = list(handle)
        first_stamp: float | None = None
        index = 0
        while index < len(remaining_lines):
            line = remaining_lines[index]
            index += 1
            if not line.startswith(">"):
                continue
            stamp, flag, satellite_count, receiver_clock_offset_s = parse_epoch_line(line, leap_seconds)
            if first_stamp is None:
                first_stamp = stamp
            satellites: list[SatelliteRecord] = []
            for _ in range(satellite_count):
                if index >= len(remaining_lines):
                    break
                sat_line = remaining_lines[index]
                index += 1
                sat_id = sat_line[:3].strip()
                if len(sat_id) < 2:
                    continue
                system = sat_id[0]
                system_obs_types = obs_types.get(system, [])
                data, index = read_satellite_data(sat_line, remaining_lines, index, system_obs_types)
                if systems and system not in systems:
                    continue
                satellites.append(SatelliteRecord(sat_id=sat_id, values=parse_observation_fields(data, system_obs_types)))
            epochs.append(
                EpochRecord(
                    stamp=stamp,
                    time_s=stamp - first_stamp,
                    flag=flag,
                    receiver_clock_offset_s=receiver_clock_offset_s,
                    satellites=satellites,
                )
            )
            if max_epochs > 0 and len(epochs) >= max_epochs:
                break
    return epochs, metadata


def frequency_hz(system: str, obs_type: str) -> float | None:
    if len(obs_type) < 2:
        return None
    band = obs_type[1]
    if system in {"G", "J", "S"}:
        return {
            "1": 1575.42e6,
            "2": 1227.60e6,
            "5": 1176.45e6,
        }.get(band)
    if system == "E":
        return {
            "1": 1575.42e6,
            "5": 1176.45e6,
            "6": 1278.75e6,
            "7": 1207.14e6,
            "8": 1191.795e6,
        }.get(band)
    if system == "C":
        return {
            "1": 1575.42e6,
            "2": 1561.098e6,
            "5": 1176.45e6,
            "6": 1268.52e6,
            "7": 1207.14e6,
            "8": 1191.795e6,
        }.get(band)
    if system == "I":
        return {
            "5": 1176.45e6,
            "9": 2492.028e6,
        }.get(band)
    return None


def wavelength_m(system: str, obs_type: str) -> float | None:
    freq = frequency_hz(system, obs_type)
    if freq is None:
        return None
    return SPEED_OF_LIGHT_MPS / freq


def values_by_prefix(values: list[ObservationValue], prefix: str) -> list[ObservationValue]:
    return [item for item in values if item.obs_type.startswith(prefix) and item.value is not None]


def mean(values: Iterable[float]) -> float | None:
    vals = list(values)
    if not vals:
        return None
    return sum(vals) / len(vals)


def rms(values: Iterable[float]) -> float | None:
    vals = list(values)
    if not vals:
        return None
    return math.sqrt(sum(value * value for value in vals) / len(vals))


def fmt(value: float | int | None, precision: int = 9) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    if isinstance(value, int):
        return str(value)
    return f"{value:.{precision}f}"


def build_satellite_rows(epochs: list[EpochRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_code: dict[tuple[str, str], tuple[float, float]] = {}

    for epoch_index, epoch in enumerate(epochs):
        for sat in epoch.satellites:
            system = sat.sat_id[0]
            code_values = values_by_prefix(sat.values, "C")
            carrier_values = values_by_prefix(sat.values, "L")
            doppler_values = values_by_prefix(sat.values, "D")
            cn0_values = values_by_prefix(sat.values, "S")
            primary_code = code_values[0] if code_values else None
            secondary_code = code_values[1] if len(code_values) > 1 else None
            primary_carrier = carrier_values[0] if carrier_values else None
            primary_doppler = doppler_values[0] if doppler_values else None
            primary_cn0 = cn0_values[0] if cn0_values else None
            all_cn0 = [item.value for item in cn0_values if item.value is not None]

            code_rate_mps: float | None = None
            doppler_range_rate_mps: float | None = None
            code_doppler_error_mps: float | None = None
            if primary_code and primary_code.value is not None:
                key = (sat.sat_id, primary_code.obs_type)
                previous = previous_code.get(key)
                if previous:
                    prev_stamp, prev_value = previous
                    dt = epoch.stamp - prev_stamp
                    if dt > 1e-9:
                        code_rate_mps = (primary_code.value - prev_value) / dt
                previous_code[key] = (epoch.stamp, primary_code.value)
            if primary_doppler and primary_doppler.value is not None:
                wav = wavelength_m(system, primary_doppler.obs_type)
                if wav is not None:
                    doppler_range_rate_mps = -primary_doppler.value * wav
            if code_rate_mps is not None and doppler_range_rate_mps is not None:
                code_doppler_error_mps = code_rate_mps - doppler_range_rate_mps

            carrier_phase_m: float | None = None
            carrier_minus_code_m: float | None = None
            if primary_carrier and primary_carrier.value is not None and primary_code and primary_code.value is not None:
                wav = wavelength_m(system, primary_carrier.obs_type)
                if wav is not None:
                    carrier_phase_m = primary_carrier.value * wav
                    carrier_minus_code_m = carrier_phase_m - primary_code.value

            rows.append(
                {
                    "stamp": epoch.stamp,
                    "time_s": epoch.time_s,
                    "epoch_index": epoch_index,
                    "epoch_flag": epoch.flag,
                    "receiver_clock_offset_s": epoch.receiver_clock_offset_s,
                    "sat_id": sat.sat_id,
                    "system": system,
                    "prn": sat.sat_id[1:],
                    "obs_count": sum(1 for item in sat.values if item.value is not None),
                    "code_count": len(code_values),
                    "carrier_count": len(carrier_values),
                    "doppler_count": len(doppler_values),
                    "cn0_count": len(cn0_values),
                    "primary_code_type": primary_code.obs_type if primary_code else "",
                    "primary_code_m": primary_code.value if primary_code else None,
                    "secondary_code_type": secondary_code.obs_type if secondary_code else "",
                    "secondary_code_m": secondary_code.value if secondary_code else None,
                    "code_delta_m": (secondary_code.value - primary_code.value)
                    if primary_code and secondary_code and primary_code.value is not None and secondary_code.value is not None
                    else None,
                    "primary_carrier_type": primary_carrier.obs_type if primary_carrier else "",
                    "primary_carrier_cycles": primary_carrier.value if primary_carrier else None,
                    "primary_carrier_phase_m": carrier_phase_m,
                    "carrier_minus_code_m": carrier_minus_code_m,
                    "primary_doppler_type": primary_doppler.obs_type if primary_doppler else "",
                    "primary_doppler_hz": primary_doppler.value if primary_doppler else None,
                    "code_rate_mps": code_rate_mps,
                    "doppler_range_rate_mps": doppler_range_rate_mps,
                    "code_doppler_error_mps": code_doppler_error_mps,
                    "primary_cn0_type": primary_cn0.obs_type if primary_cn0 else "",
                    "primary_cn0_dbhz": primary_cn0.value if primary_cn0 else None,
                    "mean_cn0_dbhz": mean(value for value in all_cn0 if value is not None),
                    "max_cn0_dbhz": max(all_cn0) if all_cn0 else None,
                    "min_cn0_dbhz": min(all_cn0) if all_cn0 else None,
                    "lli_count": sum(1 for item in sat.values if item.lli is not None and item.lli != 0),
                    "ssi_mean": mean(item.ssi for item in sat.values if item.ssi is not None),
                }
            )
    return rows


def build_epoch_rows(satellite_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_epoch: dict[int, list[dict[str, object]]] = {}
    for row in satellite_rows:
        by_epoch.setdefault(int(row["epoch_index"]), []).append(row)

    epoch_rows: list[dict[str, object]] = []
    for epoch_index in sorted(by_epoch):
        rows = by_epoch[epoch_index]
        systems = sorted(set(str(row["system"]) for row in rows))
        cn0_values = [float(row["mean_cn0_dbhz"]) for row in rows if row["mean_cn0_dbhz"] not in (None, "")]
        code_delta_values = [float(row["code_delta_m"]) for row in rows if row["code_delta_m"] not in (None, "")]
        doppler_errors = [
            float(row["code_doppler_error_mps"]) for row in rows if row["code_doppler_error_mps"] not in (None, "")
        ]
        first = rows[0]
        epoch_rows.append(
            {
                "stamp": first["stamp"],
                "time_s": first["time_s"],
                "epoch_index": epoch_index,
                "epoch_flag": first["epoch_flag"],
                "satellite_count": len(rows),
                "systems": ";".join(systems),
                "system_count": len(systems),
                "code_obs_count": sum(int(row["code_count"]) for row in rows),
                "carrier_obs_count": sum(int(row["carrier_count"]) for row in rows),
                "doppler_obs_count": sum(int(row["doppler_count"]) for row in rows),
                "cn0_obs_count": sum(int(row["cn0_count"]) for row in rows),
                "mean_cn0_dbhz": mean(cn0_values),
                "min_cn0_dbhz": min(cn0_values) if cn0_values else None,
                "max_cn0_dbhz": max(cn0_values) if cn0_values else None,
                "low_cn0_satellite_count": sum(1 for value in cn0_values if value < 35.0),
                "code_delta_mean_m": mean(code_delta_values),
                "code_delta_rms_m": rms(code_delta_values),
                "doppler_consistency_rms_mps": rms(doppler_errors),
                "lli_satellite_count": sum(1 for row in rows if int(row["lli_count"]) > 0),
            }
        )
    return epoch_rows


def write_satellite_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "stamp",
        "time_s",
        "epoch_index",
        "epoch_flag",
        "receiver_clock_offset_s",
        "sat_id",
        "system",
        "prn",
        "obs_count",
        "code_count",
        "carrier_count",
        "doppler_count",
        "cn0_count",
        "primary_code_type",
        "primary_code_m",
        "secondary_code_type",
        "secondary_code_m",
        "code_delta_m",
        "primary_carrier_type",
        "primary_carrier_cycles",
        "primary_carrier_phase_m",
        "carrier_minus_code_m",
        "primary_doppler_type",
        "primary_doppler_hz",
        "code_rate_mps",
        "doppler_range_rate_mps",
        "code_doppler_error_mps",
        "primary_cn0_type",
        "primary_cn0_dbhz",
        "mean_cn0_dbhz",
        "max_cn0_dbhz",
        "min_cn0_dbhz",
        "lli_count",
        "ssi_mean",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: fmt(row.get(key)) if isinstance(row.get(key), (float, int)) or row.get(key) is None else row.get(key) for key in columns})


def write_epoch_csv(path: Path, rows: list[dict[str, object]]) -> None:
    columns = [
        "stamp",
        "time_s",
        "epoch_index",
        "epoch_flag",
        "satellite_count",
        "systems",
        "system_count",
        "code_obs_count",
        "carrier_obs_count",
        "doppler_obs_count",
        "cn0_obs_count",
        "mean_cn0_dbhz",
        "min_cn0_dbhz",
        "max_cn0_dbhz",
        "low_cn0_satellite_count",
        "code_delta_mean_m",
        "code_delta_rms_m",
        "doppler_consistency_rms_mps",
        "lli_satellite_count",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: fmt(row.get(key)) if isinstance(row.get(key), (float, int)) or row.get(key) is None else row.get(key) for key in columns})


def sample_range(values: Iterable[float]) -> dict[str, float] | None:
    vals = list(values)
    if not vals:
        return None
    return {"min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals)}


def write_summary(
    path: Path,
    metadata: dict[str, object],
    satellite_rows: list[dict[str, object]],
    epoch_rows: list[dict[str, object]],
    outputs: dict[str, str],
) -> None:
    system_counts: dict[str, int] = {}
    for row in satellite_rows:
        system = str(row["system"])
        system_counts[system] = system_counts.get(system, 0) + 1
    summary = {
        "epochs": len(epoch_rows),
        "satellite_rows": len(satellite_rows),
        "systems": system_counts,
        "metadata": metadata,
        "satellite_count": sample_range(float(row["satellite_count"]) for row in epoch_rows),
        "mean_cn0_dbhz": sample_range(
            float(row["mean_cn0_dbhz"]) for row in epoch_rows if row["mean_cn0_dbhz"] is not None
        ),
        "code_delta_rms_m": sample_range(
            float(row["code_delta_rms_m"]) for row in epoch_rows if row["code_delta_rms_m"] is not None
        ),
        "outputs": outputs,
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def parse_systems(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> int:
    args = parse_args()
    obs_path = clean_path(args.obs)
    output_dir = clean_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    epochs, metadata = iter_epochs(
        obs_path,
        leap_seconds=args.gps_utc_leap_seconds,
        systems=parse_systems(args.systems),
        max_epochs=max(0, args.max_epochs),
    )
    if not epochs:
        raise SystemExit(f"No observation epochs found in {obs_path}")

    satellite_rows = build_satellite_rows(epochs)
    epoch_rows = build_epoch_rows(satellite_rows)
    satellite_csv = output_dir / f"{args.name}_satellite_features.csv"
    epoch_csv = output_dir / f"{args.name}_epoch_summary.csv"
    summary_json = output_dir / f"{args.name}_rinex_summary.json"
    write_satellite_csv(satellite_csv, satellite_rows)
    write_epoch_csv(epoch_csv, epoch_rows)
    write_summary(
        summary_json,
        metadata,
        satellite_rows,
        epoch_rows,
        {
            "satellite_features_csv": str(satellite_csv),
            "epoch_summary_csv": str(epoch_csv),
            "summary_json": str(summary_json),
        },
    )

    print("RINEX features extracted")
    print(f"  epochs: {len(epoch_rows)}")
    print(f"  satellite rows: {len(satellite_rows)}")
    print(f"  satellite features: {satellite_csv}")
    print(f"  epoch summary: {epoch_csv}")
    print(f"  summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
