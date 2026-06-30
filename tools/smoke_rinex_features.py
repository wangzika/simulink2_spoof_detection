#!/usr/bin/env python3
"""Self-contained smoke test for RINEX feature extraction."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def header(body: str, label: str) -> str:
    return f"{body:<60}{label}\n"


def obs_field(value: float | None, lli: int = 0, ssi: int = 7) -> str:
    if value is None:
        return " " * 16
    return f"{value:14.3f}{lli}{ssi}"


def sat_line(sat_id: str, values: list[float | None]) -> str:
    return sat_id + "".join(obs_field(value) for value in values) + "\n"


def create_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        header("     3.04           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
        header("SMOKE                                                       ", "MARKER NAME"),
        header("G    6 C1C L1C D1C S1C C2W S2W", "SYS / # / OBS TYPES"),
        header("     1.000", "INTERVAL"),
        header("  2024     1    29     7     0   0.0000000     GPS", "TIME OF FIRST OBS"),
        header("", "END OF HEADER"),
        "> 2024  1 29  7  0  0.0000000  0  2       0.000000000000\n",
        sat_line("G01", [20_000_000.0, 105_000_000.0, -52.55, 45.0, 20_000_004.0, 43.0]),
        sat_line("G02", [21_000_000.0, 110_000_000.0, 30.00, 40.0, 21_000_002.0, 39.0]),
        "> 2024  1 29  7  0  1.0000000  0  2       0.000000000000\n",
        sat_line("G01", [20_000_010.0, 105_000_050.0, -52.55, 45.5, 20_000_014.0, 43.5]),
        sat_line("G02", [20_999_994.0, 109_999_970.0, 31.00, 40.5, 20_999_997.0, 39.5]),
    ]
    path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    root = PROJECT_ROOT / "build" / "rinex_features_smoke"
    obs_path = root / "smoke.obs"
    output_dir = root / "out"
    create_fixture(obs_path)
    subprocess.run(
        [
            sys.executable,
            "tools/extract_rinex_features.py",
            "--obs",
            str(obs_path),
            "--name",
            "smoke",
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    summary = json.loads((output_dir / "smoke_rinex_summary.json").read_text(encoding="utf-8"))
    if summary["epochs"] != 2 or summary["satellite_rows"] != 4:
        raise SystemExit(f"Unexpected summary: {summary}")

    rows = list(csv.DictReader((output_dir / "smoke_satellite_features.csv").open()))
    second_g01 = next(row for row in rows if row["epoch_index"] == "1" and row["sat_id"] == "G01")
    if second_g01["code_doppler_error_mps"] == "":
        raise SystemExit("Expected code-Doppler consistency feature for second G01 epoch")
    epoch_rows = list(csv.DictReader((output_dir / "smoke_epoch_summary.csv").open()))
    if int(epoch_rows[0]["satellite_count"]) != 2:
        raise SystemExit("Expected two satellites in first epoch")

    print("RINEX feature smoke test passed")
    print(f"  satellite features: {output_dir / 'smoke_satellite_features.csv'}")
    print(f"  epoch summary: {output_dir / 'smoke_epoch_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
