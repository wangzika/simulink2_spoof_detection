#!/usr/bin/env python3
"""Self-contained smoke test for broadcast-ephemeris residuals and attack injection."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

import compute_raw_gnss_residuals as raw


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def header(body: str, label: str) -> str:
    return f"{body:<60}{label}\n"


def nav_values(values: list[float]) -> str:
    return "    " + "".join(f"{value:19.12E}" for value in values) + "\n"


def write_nav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        header("     3.04           NAVIGATION DATA     G (GPS)", "RINEX VERSION / TYPE"),
        header("", "END OF HEADER"),
    ]
    toe_s = 111600.0
    week = 2299.0
    sqrt_a = 5153.7954775
    for prn in range(1, 7):
        sat = f"G{prn:02d}"
        m0 = -2.4 + prn * 0.85
        omega0 = -2.7 + prn * 0.95
        omega = 0.15 + prn * 0.32
        i0 = 0.94 + 0.015 * prn
        lines.append(f"{sat} 2024 01 29 07 00 00 0.000000000000E+00 0.000000000000E+00 0.000000000000E+00\n")
        lines.append(nav_values([float(prn), 20.0 + prn, 3.8e-9, m0]))
        lines.append(nav_values([1.0e-6, 0.008 + prn * 1.0e-4, 2.0e-6, sqrt_a]))
        lines.append(nav_values([toe_s, 1.0e-7, omega0, -1.0e-7]))
        lines.append(nav_values([i0, 180.0 + prn, omega, -8.0e-9]))
        lines.append(nav_values([1.0e-10, 1.0, week, 0.0]))
        lines.append(nav_values([2.0, 0.0, 0.0, float(prn)]))
        lines.append(nav_values([toe_s, 4.0, 0.0, 0.0]))
    path.write_text("".join(lines), encoding="utf-8")


def write_pos(path: Path, stamp: float, receiver: raw.ReceiverPosition) -> None:
    week, tow = raw.unix_to_gps_week_tow(stamp, 18.0)
    path.write_text(
        "\n".join(
            [
                "% smoke RTKLIB position",
                "%  GPST              x-ecef(m)      y-ecef(m)      z-ecef(m)   Q  ns   sdx(m)   sdy(m)   sdz(m)  sdxy(m)  sdyz(m)  sdzx(m) age(s)  ratio",
                f"{week} {tow:.3f} {receiver.x_m:.4f} {receiver.y_m:.4f} {receiver.z_m:.4f} 1 6 0.01 0.01 0.01 0 0 0 0.0 5.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def generate_feature_rows(nav_path: Path, stamps: list[float], receiver: raw.ReceiverPosition) -> list[dict[str, object]]:
    ephemerides = raw.parse_navigation_file(nav_path)
    rows = []
    receiver_clock_bias_m = 72_000.0
    previous_reference_range: dict[str, tuple[float, float]] = {}
    for epoch_index, stamp in enumerate(stamps):
        week, tow = raw.unix_to_gps_week_tow(stamp, 18.0)
        for prn in range(1, 7):
            sat_id = f"G{prn:02d}"
            eph = raw.select_ephemeris(ephemerides, sat_id, week, tow)
            assert eph is not None
            pseudorange_m = 22_000_000.0
            for _ in range(3):
                transmit_tow = tow - pseudorange_m / raw.SPEED_OF_LIGHT_MPS
                sx, sy, sz, sat_clock = raw.satellite_position_clock(eph, week, transmit_tow)
                sx, sy, sz = raw.rotate_satellite_for_earth_rotation(sx, sy, sz, pseudorange_m / raw.SPEED_OF_LIGHT_MPS)
                geom = raw.norm3(sx - receiver.x_m, sy - receiver.y_m, sz - receiver.z_m)
                pseudorange_m = geom - raw.SPEED_OF_LIGHT_MPS * sat_clock + receiver_clock_bias_m
            doppler_rate = ""
            previous = previous_reference_range.get(sat_id)
            if previous is not None:
                prev_stamp, prev_geom = previous
                doppler_rate = f"{(geom - prev_geom) / (stamp - prev_stamp):.9f}"
            previous_reference_range[sat_id] = (stamp, geom)
            rows.append(
                {
                    "stamp": f"{stamp:.9f}",
                    "time_s": f"{stamp - stamps[0]:.9f}",
                    "epoch_index": epoch_index,
                    "sat_id": sat_id,
                    "system": "G",
                    "primary_code_type": "C1C",
                    "primary_code_m": f"{pseudorange_m:.9f}",
                    "primary_carrier_phase_m": f"{geom + prn * 1000.0:.9f}",
                    "doppler_range_rate_mps": doppler_rate,
                    "primary_cn0_dbhz": "48.0",
                    "mean_cn0_dbhz": "48.0",
                    "lli_count": 0,
                }
            )
    return rows


def write_features(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_command(args: list[str]) -> None:
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


def read_epochs(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"Expected residual epochs in {path}")
    return rows


def main() -> int:
    root = PROJECT_ROOT / "build" / "raw_residual_smoke"
    nav_path = root / "smoke_nav.rnx"
    pos_path = root / "smoke.pos"
    features_path = root / "smoke_satellite_features.csv"
    clean_dir = root / "clean"
    attack_dir = root / "attack"
    attacked_features_dir = root / "attacked_features"

    receiver = raw.ReceiverPosition(0.0, -2267128.4, 5009529.1, 3221136.9, 1)
    stamp = raw.gps_week_tow_to_unix(2299, 111600.0, 18.0)
    write_nav(nav_path)
    write_pos(pos_path, stamp, receiver)
    write_features(features_path, generate_feature_rows(nav_path, [stamp, stamp + 1.0], receiver))

    run_command(
        [
            sys.executable,
            "tools/compute_raw_gnss_residuals.py",
            "--satellite-features",
            str(features_path),
            "--nav",
            str(nav_path),
            "--rtklib-pos",
            str(pos_path),
            "--name",
            "smoke_clean",
            "--output-dir",
            str(clean_dir),
            "--elevation-mask-deg",
            "-90",
            "--measurement-sigma-m",
            "1.0",
        ]
    )
    clean_epochs = read_epochs(clean_dir / "smoke_clean_raw_epoch_residuals.csv")
    clean_epoch = clean_epochs[-1]
    if float(clean_epoch["raim_score"]) > 0.10:
        raise SystemExit(f"Expected low clean RAIM score, got {clean_epoch}")
    if not any(float(row["doppler_used_count"]) > 0 and float(row["tdcp_valid_count"]) > 0 for row in clean_epochs):
        raise SystemExit(f"Expected Doppler/TDCP residual counts in clean output, got {clean_epochs}")

    run_command(
        [
            sys.executable,
            "tools/inject_observation_attack.py",
            "--satellite-features",
            str(features_path),
            "--name",
            "smoke_attack",
            "--output-dir",
            str(attacked_features_dir),
            "--attack-window",
            "+0:+10",
            "--attack-ramp-s",
            "0",
            "--per-satellite-bias-m",
            "80",
            "--satellite-mode",
            "alternating",
            "--systems",
            "G",
        ]
    )
    attacked_features = attacked_features_dir / "smoke_attack_satellite_features.csv"
    run_command(
        [
            sys.executable,
            "tools/compute_raw_gnss_residuals.py",
            "--satellite-features",
            str(attacked_features),
            "--nav",
            str(nav_path),
            "--rtklib-pos",
            str(pos_path),
            "--name",
            "smoke_attack",
            "--output-dir",
            str(attack_dir),
            "--elevation-mask-deg",
            "-90",
            "--measurement-sigma-m",
            "1.0",
        ]
    )
    attack_epoch = read_epochs(attack_dir / "smoke_attack_raw_epoch_residuals.csv")[-1]
    attack_summary = json.loads((attacked_features_dir / "smoke_attack_attack_summary.json").read_text(encoding="utf-8"))
    if attack_summary["attacked_rows"] <= 0:
        raise SystemExit("Expected attacked rows in observation injector output")
    if float(attack_epoch["raim_score"]) <= float(clean_epoch["raim_score"]) + 1.0:
        raise SystemExit(f"Expected attack RAIM score to increase, clean={clean_epoch}, attack={attack_epoch}")

    print("Raw residual smoke test passed")
    print(f"  clean residuals: {clean_dir / 'smoke_clean_raw_epoch_residuals.csv'}")
    print(f"  attack residuals: {attack_dir / 'smoke_attack_raw_epoch_residuals.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
