#!/usr/bin/env python3
"""View the flight simulation CSV in Rerun."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import site
import subprocess
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = PROJECT_ROOT / "third_party" / "python_deps"
LOCAL_RERUN_PKG = LOCAL_DEPS / "rerun_sdk"
LOCAL_RERUN_BIN = LOCAL_DEPS / "bin" / "rerun"


def add_local_python_deps() -> None:
    if LOCAL_DEPS.exists():
        site.addsitedir(str(LOCAL_DEPS))
        for path in (str(LOCAL_DEPS), str(LOCAL_RERUN_PKG)):
            while path in sys.path:
                sys.path.remove(path)
        sys.path.insert(0, str(LOCAL_RERUN_PKG))
        sys.path.insert(0, str(LOCAL_DEPS))
        existing = os.environ.get("PYTHONPATH")
        paths = [str(LOCAL_DEPS), str(LOCAL_RERUN_PKG)]
        if existing:
            paths.append(existing)
        os.environ["PYTHONPATH"] = os.pathsep.join(paths)
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("RERUN_ANALYTICS_ENABLED", "false")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a Rerun dashboard from an f7_sim CSV log.",
    )
    parser.add_argument(
        "csv",
        nargs="?",
        default=str(PROJECT_ROOT / "build" / "final_simulation.csv"),
        help="CSV produced by f7_sim.",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="Write a .rrd recording to PATH. Defaults to the CSV path with .rrd suffix.",
    )
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        help="Do not open the Rerun viewer after writing the recording.",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Log every Nth dynamic row. Static paths always use all rows.",
    )
    parser.add_argument(
        "--viewer",
        default=None,
        help="Optional path to a Rerun CLI/viewer executable. Defaults to 'python -m rerun_cli'.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--web",
        dest="web",
        action="store_true",
        default=True,
        help="Open the Rerun Web Viewer in a browser. This is the default.",
    )
    mode.add_argument(
        "--native",
        dest="web",
        action="store_false",
        help="Open the native Rerun viewer instead of the Web Viewer.",
    )
    parser.add_argument(
        "--renderer",
        default=None,
        help="Override the Rerun renderer. Defaults to webgl for --web.",
    )
    return parser.parse_args()


def require_rerun():
    add_local_python_deps()
    try:
        import rerun as rr
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing rerun-sdk. Install it with:\n"
            "  python -m pip install --target third_party/python_deps rerun-sdk"
        ) from exc
    return rr


def launch_viewer(viewer: str | None, recording_path: Path, *, web: bool, renderer: str | None) -> None:
    if viewer:
        viewer_path = Path(viewer).expanduser().resolve()
        if not viewer_path.exists():
            raise SystemExit(
                "Rerun viewer executable was not found. Recording was written to:\n"
                f"  {recording_path}\n"
                f"Missing viewer: {viewer_path}"
            )
        command = [str(viewer_path), str(recording_path)]
    else:
        command = [sys.executable, "-m", "rerun_cli", str(recording_path)]

    if web:
        command.append("--new")
        command.append("--web-viewer")
        command.extend(["--web-viewer-port", "0"])
        command.extend(["--renderer", renderer or "webgl"])
    elif renderer:
        command.extend(["--renderer", renderer])

    subprocess.Popen(
        command,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def as_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"CSV is missing numeric column '{key}'") from exc


def as_bool(row: dict[str, str], key: str) -> bool:
    return as_float(row, key) != 0.0


def has_column(rows: list[dict[str, str]], key: str) -> bool:
    return bool(rows) and key in rows[0]


def optional_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    if key not in row or row[key] == "":
        return default
    return as_float(row, key)


def xyz(row: dict[str, str], prefix: str) -> list[float]:
    return [
        as_float(row, f"{prefix}_x"),
        as_float(row, f"{prefix}_y"),
        as_float(row, f"{prefix}_z"),
    ]


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"CSV is empty: {csv_path}")
    return rows


def path_points(rows: Iterable[dict[str, str]], prefix: str) -> list[list[float]]:
    return [xyz(row, prefix) for row in rows]


def valid_points(rows: Iterable[dict[str, str]], prefix: str, valid_column: str) -> list[list[float]]:
    return [xyz(row, prefix) for row in rows if as_bool(row, valid_column)]


def contiguous_segments(rows: list[dict[str, str]], flag_column: str, prefix: str) -> list[list[list[float]]]:
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    for row in rows:
        if as_bool(row, flag_column):
            current.append(xyz(row, prefix))
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return [segment for segment in segments if len(segment) >= 2]


def log_static_scene(rr, rows: list[dict[str, str]], csv_path: Path) -> None:
    rr.log(
        "world/paths/true",
        rr.LineStrips3D([path_points(rows, "true")], colors=[[0, 180, 95]], radii=[0.025]),
        static=True,
    )
    rr.log(
        "world/paths/estimate",
        rr.LineStrips3D([path_points(rows, "est")], colors=[[70, 135, 255]], radii=[0.02]),
        static=True,
    )
    rr.log(
        "world/paths/gps",
        rr.LineStrips3D([path_points(rows, "gps")], colors=[[235, 195, 30]], radii=[0.018]),
        static=True,
    )
    rr.log(
        "world/paths/reference",
        rr.LineStrips3D([path_points(rows, "ref")], colors=[[180, 180, 190]], radii=[0.018]),
        static=True,
    )

    attack_segments = contiguous_segments(rows, "attack_active", "gps")
    if attack_segments:
        rr.log(
            "world/paths/gps_attack",
            rr.LineStrips3D(attack_segments, colors=[[245, 65, 65]], radii=[0.045]),
            static=True,
        )

    uwb = valid_points(rows, "uwb", "uwb_valid")
    if uwb:
        rr.log(
            "world/sensors/uwb_points",
            rr.Points3D(uwb, colors=[[160, 80, 255]] * len(uwb), radii=[0.035] * len(uwb)),
            static=True,
        )

    rr.log(
        "plots/residual_norm",
        rr.SeriesLines(colors=[[70, 135, 255]], names=["GPS residual norm"]),
        static=True,
    )
    rr.log(
        "plots/glrt_statistic",
        rr.SeriesLines(colors=[[245, 65, 65]], names=["GLRT statistic"]),
        static=True,
    )
    rr.log(
        "plots/glrt_threshold",
        rr.SeriesLines(colors=[[125, 125, 135]], names=["GLRT threshold"]),
        static=True,
    )
    rr.log(
        "plots/pseudorange_rms",
        rr.SeriesLines(colors=[[255, 165, 40]], names=["Pseudorange RMS"]),
        static=True,
    )
    rr.log(
        "plots/trust_state",
        rr.SeriesLines(
            colors=[[0, 180, 95], [245, 65, 65], [255, 165, 40]],
            names=["GPS trusted", "Detected", "Attack active"],
        ),
        static=True,
    )

    if has_column(rows, "rtk_quality"):
        rr.log(
            "plots/rtk_quality",
            rr.SeriesLines(colors=[[40, 200, 210]], names=["RTK quality"]),
            static=True,
        )
    if has_column(rows, "rtk_ratio"):
        rr.log(
            "plots/rtk_ratio",
            rr.SeriesLines(colors=[[150, 115, 255]], names=["RTK ambiguity ratio"]),
            static=True,
        )
    if has_column(rows, "rtk_satellites"):
        rr.log(
            "plots/rtk_satellites",
            rr.SeriesLines(colors=[[75, 190, 85]], names=["RTK satellites"]),
            static=True,
        )
    if all(has_column(rows, key) for key in ("dop_pdop", "dop_hdop", "dop_vdop")):
        rr.log(
            "plots/dop",
            rr.SeriesLines(
                colors=[[245, 65, 65], [70, 135, 255], [255, 165, 40]],
                names=["PDOP", "HDOP", "VDOP"],
            ),
            static=True,
        )

    first = rows[0]
    last = rows[-1]
    extra_plot_text = ""
    if has_column(rows, "rtk_quality"):
        extra_plot_text = ", RTK quality, RTK ratio, satellite count, DOP"
    summary = "\n".join(
        [
            "# F7 Flight Simulation",
            "",
            f"- Source: `{csv_path}`",
            f"- Samples: {len(rows)}",
            f"- Time span: {as_float(first, 'time_s'):.2f}s to {as_float(last, 'time_s'):.2f}s",
            "- 3D paths: true, estimate, GPS, reference, GPS attack segment, UWB points",
            f"- Time plots: residual norm, GLRT statistic, threshold, pseudorange RMS, trust state{extra_plot_text}",
        ]
    )
    rr.log("readme", rr.TextDocument(summary, media_type="text/markdown"), static=True)


def log_dynamic_rows(rr, rows: list[dict[str, str]], stride: int) -> None:
    stride = max(1, stride)
    previous_mode = None
    previous_trust = None

    for index, row in enumerate(rows):
        if index % stride != 0 and index != len(rows) - 1:
            continue

        rr.set_time("sim_time", duration=as_float(row, "time_s"))
        rr.log("world/live/true", rr.Points3D([xyz(row, "true")], colors=[[0, 220, 120]], radii=[0.12]))
        rr.log("world/live/estimate", rr.Points3D([xyz(row, "est")], colors=[[70, 135, 255]], radii=[0.1]))
        rr.log("world/live/gps", rr.Points3D([xyz(row, "gps")], colors=[[235, 195, 30]], radii=[0.08]))
        rr.log("world/live/reference", rr.Points3D([xyz(row, "ref")], colors=[[210, 210, 215]], radii=[0.07]))

        rr.log("plots/residual_norm", rr.Scalars([as_float(row, "residual_norm")]))
        rr.log("plots/glrt_statistic", rr.Scalars([as_float(row, "glrt_statistic")]))
        rr.log("plots/glrt_threshold", rr.Scalars([as_float(row, "glrt_threshold")]))
        rr.log("plots/pseudorange_rms", rr.Scalars([as_float(row, "pseudorange_residual_rms")]))
        rr.log(
            "plots/trust_state",
            rr.Scalars(
                [
                    1.0 if as_bool(row, "gps_trusted") else 0.0,
                    1.0 if as_bool(row, "detected") else 0.0,
                    1.0 if as_bool(row, "attack_active") else 0.0,
                ]
            ),
        )
        if has_column(rows, "rtk_quality"):
            rr.log("plots/rtk_quality", rr.Scalars([optional_float(row, "rtk_quality")]))
        if has_column(rows, "rtk_ratio"):
            rr.log("plots/rtk_ratio", rr.Scalars([optional_float(row, "rtk_ratio")]))
        if has_column(rows, "rtk_satellites"):
            rr.log("plots/rtk_satellites", rr.Scalars([optional_float(row, "rtk_satellites")]))
        if all(has_column(rows, key) for key in ("dop_pdop", "dop_hdop", "dop_vdop")):
            rr.log(
                "plots/dop",
                rr.Scalars(
                    [
                        optional_float(row, "dop_pdop"),
                        optional_float(row, "dop_hdop"),
                        optional_float(row, "dop_vdop"),
                    ]
                ),
            )

        mode = row.get("flight_mode", "")
        gps_trusted = as_bool(row, "gps_trusted")
        if mode != previous_mode or gps_trusted != previous_trust:
            trust_text = "trusted" if gps_trusted else "rejected"
            rr.log("events/state_changes", rr.TextLog(f"{mode}: GPS {trust_text}"))
            previous_mode = mode
            previous_trust = gps_trusted


def main() -> int:
    args = parse_args()
    if args.stride < 1:
        raise SystemExit("--stride must be >= 1")

    rr = require_rerun()
    csv_path = Path(args.csv).expanduser().resolve()
    rows = load_rows(csv_path)

    recording_path = Path(args.save).expanduser().resolve() if args.save else csv_path.with_suffix(".rrd")
    recording_path.parent.mkdir(parents=True, exist_ok=True)

    rr.init("f7_flight_sim_rerun")
    rr.save(recording_path)

    try:
        log_static_scene(rr, rows, csv_path)
        log_dynamic_rows(rr, rows, args.stride)
    finally:
        rr.disconnect()

    if args.no_spawn:
        print(f"Wrote Rerun recording: {recording_path}")
    else:
        launch_viewer(args.viewer, recording_path, web=args.web, renderer=args.renderer)
        print(f"Wrote Rerun recording: {recording_path}")
        viewer_kind = "Web Viewer" if args.web else "native viewer"
        print(f"Launched Rerun {viewer_kind} for {recording_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
