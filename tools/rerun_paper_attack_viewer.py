#!/usr/bin/env python3
"""Build a Rerun recording for paper-level GNSS spoofing experiments."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
from pathlib import Path
import site
import subprocess
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = PROJECT_ROOT / "third_party" / "python_deps"
LOCAL_RERUN_PKG = LOCAL_DEPS / "rerun_sdk"


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
        description="Create a Rerun dashboard for the paper attack/detection timeline.",
    )
    parser.add_argument(
        "detection_csv",
        nargs="?",
        default=str(PROJECT_ROOT / "build" / "paper_platform" / "full_data_attack_full_timeline" / "full_data_attack_full_timeline_detection.csv"),
        help="Detection CSV produced by tools/build_detection_dataset.py.",
    )
    parser.add_argument("--timeline", help="Optional adaptive_sequential_detector.py output CSV.")
    parser.add_argument("--detector", default="adaptive_seq_full", help="Detector name to visualize from --timeline.")
    parser.add_argument("--satellite-features", help="Optional attacked per-satellite observation feature CSV.")
    parser.add_argument("--attack-summary", help="Optional observation-level attack summary JSON.")
    parser.add_argument("--save", metavar="PATH", help="Write .rrd recording to PATH.")
    parser.add_argument("--no-spawn", action="store_true", help="Do not open the viewer after writing the recording.")
    parser.add_argument("--stride", type=int, default=1, help="Log every Nth detection row dynamically.")
    parser.add_argument("--viewer", default=None, help="Optional path to a Rerun CLI/viewer executable.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web", dest="web", action="store_true", default=True, help="Open the Rerun Web Viewer.")
    mode.add_argument("--native", dest="web", action="store_false", help="Open the native viewer.")
    parser.add_argument("--renderer", default=None, help="Override the Rerun renderer. Defaults to webgl for --web.")
    return parser.parse_args()


def clean_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


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
            raise SystemExit(f"Rerun viewer executable was not found: {viewer_path}")
        command = [str(viewer_path), str(recording_path)]
    else:
        command = [sys.executable, "-m", "rerun_cli", str(recording_path)]
    if web:
        command.extend(["--new", "--web-viewer", "--web-viewer-port", "0", "--renderer", renderer or "webgl"])
    elif renderer:
        command.extend(["--renderer", renderer])
    subprocess.Popen(
        command,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    if not path.exists():
        raise SystemExit(f"CSV not found: {path}")
    with path.open(newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path | None) -> dict:
    if path is None:
        return {}
    if not path.exists():
        raise SystemExit(f"JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def f(row: dict[str, str] | None, key: str, default: float = 0.0) -> float:
    if row is None:
        return default
    value = row.get(key, "")
    if value is None or value == "" or str(value).lower() == "nan":
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def point(row: dict[str, str]) -> list[float]:
    return [f(row, "rtk_enu_e_m"), f(row, "rtk_enu_n_m"), f(row, "rtk_enu_u_m")]


def valid_point(row: dict[str, str]) -> bool:
    return any(abs(value) > 1e-9 for value in point(row)) or f(row, "rtk_quality", 0.0) > 0.0


def filter_timeline(rows: list[dict[str, str]], detector: str) -> list[dict[str, str]]:
    if not rows:
        return []
    if "detector" not in rows[0]:
        return rows
    filtered = [row for row in rows if row.get("detector") == detector]
    return filtered or rows


def intervals(rows: list[dict[str, str]], flag: str = "attack_label") -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start: float | None = None
    previous = 0.0
    for row in rows:
        time_s = f(row, "time_s")
        active = f(row, flag) > 0.0
        if active and start is None:
            start = time_s
        if start is not None and not active:
            out.append((start, previous))
            start = None
        previous = time_s
    if start is not None:
        out.append((start, previous))
    return out


def first_time(rows: list[dict[str, str]], flag: str) -> float | None:
    for row in rows:
        if f(row, flag) > 0.0:
            return f(row, "time_s")
    return None


def inside_any_interval(time_s: float, attack_intervals: list[tuple[float, float]]) -> bool:
    return any(start <= time_s <= end for start, end in attack_intervals)


def detection_kind(time_s: float, attack_intervals: list[tuple[float, float]]) -> str:
    if inside_any_interval(time_s, attack_intervals):
        return "ATTACK-WINDOW DETECTION"
    return "ALARM OUTSIDE ATTACK WINDOW"


def rows_with_flag(rows: Iterable[dict[str, str]], flag: str) -> list[dict[str, str]]:
    return [row for row in rows if f(row, flag) > 0.0]


def nearest_by_time(rows: list[dict[str, str]], times: list[float], time_s: float) -> dict[str, str] | None:
    if not rows:
        return None
    pos = bisect.bisect_left(times, time_s)
    candidates = []
    if pos < len(times):
        candidates.append(pos)
    if pos > 0:
        candidates.append(pos - 1)
    best = min(candidates, key=lambda idx: abs(times[idx] - time_s))
    return rows[best]


def path_segments(rows: list[dict[str, str]], flag: str) -> list[list[list[float]]]:
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    for row in rows:
        if f(row, flag) > 0.0 and valid_point(row):
            current.append(point(row))
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return [segment for segment in segments if len(segment) >= 2]


def summarize_attack(attack_summary: dict, satellite_rows: list[dict[str, str]], first_stamp: float) -> str:
    windows = attack_summary.get("windows", [])
    window_text = ", ".join(f"+{float(item.get('start_s', 0.0)):.1f}s:+{float(item.get('end_s', 0.0)):.1f}s" for item in windows) or "n/a"
    attacked = rows_with_flag(satellite_rows, "attack_label")
    sats = sorted({row.get("sat_id", "") for row in attacked if row.get("sat_id")})
    if not sats and attack_summary.get("satellites"):
        sats = [str(value) for value in attack_summary.get("satellites", [])]
    attacked_times = [f(row, "stamp") - first_stamp for row in attacked if f(row, "stamp") > 0.0]
    active_text = "n/a"
    if attacked_times:
        active_text = f"+{min(attacked_times):.1f}s:+{max(attacked_times):.1f}s"
    return "\n".join(
        [
            "## Observation-level attack",
            "",
            f"- Configured window: {window_text}",
            f"- Observed attacked epochs: {int(attack_summary.get('attacked_epochs', len(set(attacked_times))))}",
            f"- Observed attacked rows: {int(attack_summary.get('attacked_rows', len(attacked)))}",
            f"- Active attacked-observation span after stamp alignment: {active_text}",
            f"- Common pseudorange delay: {float(attack_summary.get('common_delay_m', 0.0)):.1f} m",
            f"- Per-satellite bias magnitude: {float(attack_summary.get('per_satellite_bias_m', 0.0)):.1f} m",
            f"- Satellite mode: {attack_summary.get('satellite_mode', 'n/a')}",
            f"- Systems: {', '.join(str(value) for value in attack_summary.get('systems', [])) or 'n/a'}",
            f"- Attacked satellites visible in features: {', '.join(sats) or 'n/a'}",
        ]
    )


def log_static(rr, detection: list[dict[str, str]], timeline: list[dict[str, str]], satellite_rows: list[dict[str, str]], attack_summary: dict, csv_path: Path) -> None:
    valid_rows = [row for row in detection if valid_point(row)]
    if not valid_rows:
        raise SystemExit("Detection CSV has no usable RTK ENU trajectory columns.")
    points = [point(row) for row in valid_rows]
    rr.log("world/trajectory/rtk_full", rr.LineStrips3D([points], colors=[[70, 80, 90]], radii=[0.035]), static=True)

    attack_segments = path_segments(detection, "attack_label")
    if attack_segments:
        rr.log("world/trajectory/synthetic_attack_window", rr.LineStrips3D(attack_segments, colors=[[255, 193, 7]], radii=[0.075]), static=True)

    dataset_detected = rows_with_flag(detection, "detected")
    if dataset_detected:
        rr.log(
            "world/detections/fixed_score",
            rr.Points3D([point(row) for row in dataset_detected if valid_point(row)], colors=[[255, 111, 0]] * len(dataset_detected), radii=[0.16] * len(dataset_detected)),
            static=True,
        )

    sorted_detection = sorted(detection, key=lambda row: f(row, "time_s"))
    detection_times = [f(row, "time_s") for row in sorted_detection]
    timeline_detected_points = []
    for row in rows_with_flag(timeline, "detected"):
        match = nearest_by_time(sorted_detection, detection_times, f(row, "time_s"))
        if match is not None and valid_point(match):
            timeline_detected_points.append(point(match))
    if timeline_detected_points:
        rr.log(
            "world/detections/adaptive_seq",
            rr.Points3D(timeline_detected_points, colors=[[201, 42, 42]] * len(timeline_detected_points), radii=[0.20] * len(timeline_detected_points)),
            static=True,
        )

    for entity, rows, colors, names in [
        ("plots/dataset_state", detection, [[255, 193, 7], [201, 42, 42], [255, 111, 0]], ["attack label", "detected", "triggered"]),
        ("plots/dataset_score", detection, [[54, 79, 199], [217, 72, 15], [43, 138, 62]], ["spoof score", "score threshold", "attack scale"]),
    ]:
        _ = rows
        rr.log(entity, rr.SeriesLines(colors=colors, names=names), static=True)

    if timeline:
        rr.log(
            "plots/adaptive_seq",
            rr.SeriesLines(
                colors=[[24, 100, 171], [217, 72, 15], [43, 138, 62], [95, 61, 196]],
                names=["detector score", "adaptive threshold", "CUSUM", "confidence"],
            ),
            static=True,
        )
        rr.log(
            "plots/evidence_components",
            rr.SeriesLines(
                colors=[[24, 100, 171], [230, 119, 0], [43, 138, 62], [95, 61, 196], [11, 114, 133]],
                names=["LIO-GNSS", "pseudorange", "raw GNSS", "quality", "Doppler"],
            ),
            static=True,
        )

    if satellite_rows:
        rr.log(
            "plots/observation_injection",
            rr.SeriesLines(
                colors=[[201, 42, 42], [230, 119, 0], [24, 100, 171]],
                names=["attacked satellite count", "max abs injected bias", "mean C/N0 of attacked obs"],
            ),
            static=True,
        )

    first_stamp = f(detection[0], "stamp")
    attack_doc = summarize_attack(attack_summary, satellite_rows, first_stamp) if attack_summary or satellite_rows else "## Observation-level attack\n\nNo observation-level attack metadata was provided."
    attack_intervals = intervals(detection)
    adaptive_detection = first_time(timeline, "detected") if timeline else None
    dataset_detection = first_time(detection, "detected")
    attack_text = ", ".join(f"+{start:.1f}s:+{end:.1f}s" for start, end in attack_intervals) or "n/a"
    detection_text = (
        f"+{adaptive_detection:.1f}s ({detection_kind(adaptive_detection, attack_intervals).lower()})"
        if adaptive_detection is not None
        else "n/a"
    )
    dataset_detection_text = (
        f"+{dataset_detection:.1f}s ({detection_kind(dataset_detection, attack_intervals).lower()})"
        if dataset_detection is not None
        else "n/a"
    )
    readme = "\n".join(
        [
            "# GNSS Spoofing Paper Visualization",
            "",
            f"- Detection CSV: `{csv_path}`",
            f"- Rows: {len(detection)}",
            f"- Time span: +{f(detection[0], 'time_s'):.1f}s to +{f(detection[-1], 'time_s'):.1f}s",
            f"- Synthetic residual/pseudorange attack window in detection CSV: {attack_text}",
            f"- First fixed-score detection: {dataset_detection_text}",
            f"- First EA-SGLRT detection: {detection_text}",
            "",
            attack_doc,
            "",
            "## How to read this recording",
            "",
            "- `world/trajectory/rtk_full` shows the full RTKLIB route used as the visualization backbone.",
            "- Yellow trajectory segments show the configured synthetic attack interval.",
            "- Red points show EA-SGLRT detections; orange points show the fixed-score dataset detector.",
            "- `events/injection_and_detection` logs attack start/end, observation injection, and first-detection prompts.",
            "- `plots/*` contains attack labels, injected pseudorange bias, fused scores, adaptive threshold, CUSUM, confidence, and evidence components.",
        ]
    )
    rr.log("readme", rr.TextDocument(readme, media_type="text/markdown"), static=True)


def log_detection_rows(rr, detection: list[dict[str, str]], stride: int, attack_intervals: list[tuple[float, float]]) -> None:
    stride = max(1, stride)
    previous_attack = False
    first_detection_logged = False
    for idx, row in enumerate(detection):
        if idx % stride != 0 and idx != len(detection) - 1:
            continue
        time_s = f(row, "time_s")
        rr.set_time("sim_time", duration=time_s)
        if valid_point(row):
            rr.log("world/live/rtk", rr.Points3D([point(row)], colors=[[70, 80, 90]], radii=[0.12]))
        attack = f(row, "attack_label") > 0.0
        if attack and valid_point(row):
            rr.log("world/live/attack_active", rr.Points3D([point(row)], colors=[[255, 193, 7]], radii=[0.18]))
        if f(row, "detected") > 0.0 and valid_point(row):
            rr.log("world/live/fixed_score_detection", rr.Points3D([point(row)], colors=[[255, 111, 0]], radii=[0.22]))

        rr.log("plots/dataset_state", rr.Scalars([1.0 if attack else 0.0, f(row, "detected"), f(row, "triggered")]))
        rr.log("plots/dataset_score", rr.Scalars([f(row, "spoof_score"), f(row, "score_threshold"), f(row, "attack_scale")]))

        if attack and not previous_attack:
            offset_norm = math.sqrt(f(row, "synthetic_offset_x_m") ** 2 + f(row, "synthetic_offset_y_m") ** 2 + f(row, "synthetic_offset_z_m") ** 2)
            rr.log(
                "events/injection_and_detection",
                rr.TextLog(
                    f"ATTACK START +{time_s:.1f}s: residual offset norm {offset_norm:.2f} m, "
                    f"pseudorange delay {f(row, 'synthetic_pseudorange_delay_m'):.2f} m"
                ),
            )
        if previous_attack and not attack:
            rr.log("events/injection_and_detection", rr.TextLog(f"ATTACK END +{time_s:.1f}s"))
        if f(row, "detected") > 0.0 and not first_detection_logged:
            rr.log(
                "events/injection_and_detection",
                rr.TextLog(f"FIXED-SCORE {detection_kind(time_s, attack_intervals)} +{time_s:.1f}s, score={f(row, 'spoof_score'):.3f}"),
            )
            first_detection_logged = True
        previous_attack = attack


def log_timeline_rows(rr, timeline: list[dict[str, str]], detection: list[dict[str, str]], attack_intervals: list[tuple[float, float]]) -> None:
    if not timeline:
        return
    sorted_detection = sorted(detection, key=lambda row: f(row, "time_s"))
    detection_times = [f(row, "time_s") for row in sorted_detection]
    previous_detected = False
    for row in timeline:
        time_s = f(row, "time_s")
        rr.set_time("sim_time", duration=time_s)
        rr.log("plots/adaptive_seq", rr.Scalars([f(row, "detector_score"), f(row, "adaptive_threshold"), f(row, "cusum"), f(row, "confidence")]))
        rr.log(
            "plots/evidence_components",
            rr.Scalars([f(row, "score_lio"), f(row, "score_pseudorange"), f(row, "score_raw"), f(row, "score_quality"), f(row, "score_doppler")]),
        )
        detected = f(row, "detected") > 0.0
        if detected:
            match = nearest_by_time(sorted_detection, detection_times, time_s)
            if match is not None and valid_point(match):
                rr.log("world/live/adaptive_detection", rr.Points3D([point(match)], colors=[[201, 42, 42]], radii=[0.26]))
        if detected and not previous_detected:
            attack_type = row.get("attack_type", "unknown")
            rr.log(
                "events/injection_and_detection",
                rr.TextLog(
                    f"EA-SGLRT {detection_kind(time_s, attack_intervals)} +{time_s:.1f}s: confidence={f(row, 'confidence'):.3f}, "
                    f"CUSUM={f(row, 'cusum'):.3f}, type={attack_type}"
                ),
            )
        previous_detected = detected


def log_satellite_injection(rr, satellite_rows: list[dict[str, str]], detection: list[dict[str, str]], attack_summary: dict) -> None:
    if not satellite_rows:
        return
    first_stamp = f(detection[0], "stamp")
    per_epoch: dict[float, dict[str, float]] = {}
    for row in satellite_rows:
        if f(row, "attack_label") <= 0.0:
            continue
        stamp = f(row, "stamp")
        if stamp <= 0.0:
            continue
        item = per_epoch.setdefault(stamp, {"count": 0.0, "max_bias": 0.0, "cn0_sum": 0.0})
        item["count"] += 1.0
        item["max_bias"] = max(item["max_bias"], abs(f(row, "injected_pseudorange_bias_m")))
        item["cn0_sum"] += f(row, "mean_cn0_dbhz")
    first_event = True
    for stamp in sorted(per_epoch):
        item = per_epoch[stamp]
        time_s = stamp - first_stamp
        mean_cn0 = item["cn0_sum"] / max(1.0, item["count"])
        rr.set_time("sim_time", duration=time_s)
        rr.log("plots/observation_injection", rr.Scalars([item["count"], item["max_bias"], mean_cn0]))
        if first_event:
            common_delay = float(attack_summary.get("common_delay_m", 0.0)) if attack_summary else 0.0
            per_sat = float(attack_summary.get("per_satellite_bias_m", 0.0)) if attack_summary else item["max_bias"]
            rr.log(
                "events/injection_and_detection",
                rr.TextLog(
                    f"OBSERVATION-LEVEL INJECTION +{time_s:.1f}s: attacked satellites={int(item['count'])}, "
                    f"common delay={common_delay:.1f} m, per-satellite bias={per_sat:.1f} m"
                ),
            )
            first_event = False


def main() -> int:
    args = parse_args()
    if args.stride < 1:
        raise SystemExit("--stride must be >= 1")
    rr = require_rerun()

    detection_csv = clean_path(args.detection_csv)
    assert detection_csv is not None
    detection = read_csv(detection_csv)
    if not detection:
        raise SystemExit(f"Detection CSV is empty: {detection_csv}")
    detection.sort(key=lambda row: f(row, "time_s"))
    timeline = filter_timeline(read_csv(clean_path(args.timeline)), args.detector)
    timeline.sort(key=lambda row: f(row, "time_s"))
    satellite_rows = read_csv(clean_path(args.satellite_features))
    attack_summary = read_json(clean_path(args.attack_summary))

    recording_path = clean_path(args.save) if args.save else detection_csv.with_suffix(".rrd")
    assert recording_path is not None
    recording_path.parent.mkdir(parents=True, exist_ok=True)

    rr.init("gnss_spoofing_paper_visualization")
    rr.save(recording_path)
    try:
        attack_intervals = intervals(detection)
        log_static(rr, detection, timeline, satellite_rows, attack_summary, detection_csv)
        log_detection_rows(rr, detection, args.stride, attack_intervals)
        log_timeline_rows(rr, timeline, detection, attack_intervals)
        log_satellite_injection(rr, satellite_rows, detection, attack_summary)
    finally:
        rr.disconnect()

    print(f"Wrote paper Rerun recording: {recording_path}")
    if not args.no_spawn:
        launch_viewer(args.viewer, recording_path, web=args.web, renderer=args.renderer)
        print("Launched Rerun viewer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
