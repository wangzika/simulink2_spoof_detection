#!/usr/bin/env python3
"""Generate LaTeX paper figures from the paper-platform experiment outputs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "build" / "matplotlib_cache"))
os.environ.setdefault("XDG_CACHE_HOME", str(PROJECT_ROOT / "build" / "font_cache"))

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate figures and metric macros for paper/main.tex.")
    parser.add_argument("--attack-csv", default="build/paper_platform/full_data_attack/full_data_attack_detection.csv")
    parser.add_argument("--clean-csv", default="build/paper_platform/full_data_clean/full_data_clean_detection.csv")
    parser.add_argument("--attack-metrics", default="build/paper_platform/full_data_attack/full_data_attack_metrics.json")
    parser.add_argument("--clean-metrics", default="build/paper_platform/full_data_clean/full_data_clean_metrics.json")
    parser.add_argument("--rinex-summary", default="build/paper_platform/rinex_rover/full_data_rover_rinex_summary.json")
    parser.add_argument("--rinex-epoch", default="build/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv")
    parser.add_argument("--adaptive-dir", default="build/paper_platform/adaptive_experiments")
    parser.add_argument("--output-dir", default="paper/figures")
    parser.add_argument("--metrics-tex", default="paper/generated_metrics.tex")
    return parser.parse_args()


def resolve(path: str) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value


def require(path: Path) -> Path:
    if not path.exists():
        raise SystemExit(f"Missing required input: {path}\nRun `cmake --build build --target paper_pipeline` first.")
    return path


def savefig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=220, bbox_inches="tight")
    plt.close()
    print(f"wrote {path}")


def load_inputs(args: argparse.Namespace):
    attack = pd.read_csv(require(resolve(args.attack_csv)))
    clean = pd.read_csv(require(resolve(args.clean_csv)))
    rinex_epoch = pd.read_csv(require(resolve(args.rinex_epoch)))
    attack_metrics = json.loads(require(resolve(args.attack_metrics)).read_text(encoding="utf-8"))
    clean_metrics = json.loads(require(resolve(args.clean_metrics)).read_text(encoding="utf-8"))
    rinex_summary = json.loads(require(resolve(args.rinex_summary)).read_text(encoding="utf-8"))
    adaptive_dir = require(resolve(args.adaptive_dir))
    matrix = pd.read_csv(require(adaptive_dir / "matrix_results.csv"))
    detector_summary = pd.read_csv(require(adaptive_dir / "detector_summary.csv"))
    scenario_summary = pd.read_csv(require(adaptive_dir / "scenario_summary.csv"))
    adaptive_timeline = pd.read_csv(require(adaptive_dir / "adaptive_timeline.csv"))
    experiment_summary = json.loads(require(adaptive_dir / "experiment_summary.json").read_text(encoding="utf-8"))
    return (
        attack,
        clean,
        rinex_epoch,
        attack_metrics,
        clean_metrics,
        rinex_summary,
        matrix,
        detector_summary,
        scenario_summary,
        adaptive_timeline,
        experiment_summary,
    )


def draw_box(ax, xy, text, width=2.25, height=0.75, color="#e8f1fb"):
    x, y = xy
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.04,rounding_size=0.06",
        linewidth=1.0,
        edgecolor="#2d4059",
        facecolor=color,
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=9)


def draw_arrow(ax, start, end):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=1.1,
            color="#2d4059",
        )
    )


def plot_architecture(output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 4.7))
    ax.axis("off")
    boxes = {
        "rinex": (0.2, 3.2, "RINEX\nrover/base obs"),
        "rtk": (0.2, 2.05, "RTKLIB\n.pos, DOP"),
        "fast": (0.2, 0.9, "FAST_GLIO\nloose/raw/tight logs"),
        "extract": (3.0, 3.2, "Raw observation\nfeature extraction"),
        "sync": (3.0, 1.75, "Time alignment\nGPST/Unix"),
        "detect": (5.8, 2.45, "Multi-cue\nspoof scoring"),
        "eval": (5.8, 1.15, "Evaluation\nF1, ROC, latency"),
    }
    colors = {
        "rinex": "#e9f5db",
        "rtk": "#fff3bf",
        "fast": "#ffe3e3",
        "extract": "#d8f3dc",
        "sync": "#e7f5ff",
        "detect": "#f3d9fa",
        "eval": "#dee2ff",
    }
    for key, (x, y, text) in boxes.items():
        draw_box(ax, (x, y), text, color=colors[key])
    draw_arrow(ax, (2.45, 3.58), (3.0, 3.58))
    draw_arrow(ax, (2.45, 2.43), (3.0, 2.05))
    draw_arrow(ax, (2.45, 1.28), (3.0, 1.95))
    draw_arrow(ax, (5.25, 3.58), (5.8, 2.86))
    draw_arrow(ax, (5.25, 2.10), (5.8, 2.62))
    draw_arrow(ax, (6.92, 2.45), (6.92, 1.90))
    ax.set_xlim(0, 8.4)
    ax.set_ylim(0.4, 4.25)
    savefig(output_dir / "system_architecture.png")


def plot_trajectory_quality(attack: pd.DataFrame, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
    ax = axes[0]
    scatter = ax.scatter(
        attack["rtk_enu_e_m"],
        attack["rtk_enu_n_m"],
        c=attack["time_s"],
        s=13,
        cmap="viridis",
        linewidths=0,
    )
    ax.set_title("RTK trajectory in local ENU")
    ax.set_xlabel("East (m)")
    ax.set_ylabel("North (m)")
    ax.axis("equal")
    cbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Experiment time (s)")

    ax = axes[1]
    ax.plot(attack["time_s"], attack["rinex_satellite_count"], label="RINEX satellites", color="#1c7ed6")
    ax.set_xlabel("Experiment time (s)")
    ax.set_ylabel("Satellite count")
    ax2 = ax.twinx()
    ax2.plot(attack["time_s"], attack["rinex_mean_cn0_dbhz"], label="Mean C/N0", color="#e67700", alpha=0.85)
    ax2.set_ylabel("Mean C/N0 (dB-Hz)")
    ax.set_title("Raw-observation availability")
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="lower right", fontsize=8)
    savefig(output_dir / "trajectory_quality.png")


def plot_spoof_score(attack: pd.DataFrame, metrics: dict, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    t = attack["time_s"]
    ax.plot(t, attack["spoof_score"], color="#364fc7", linewidth=1.3, label="Spoof score")
    ax.axhline(float(attack["score_threshold"].iloc[0]), color="#d9480f", linestyle="--", label="Fixed threshold")
    best = metrics.get("threshold_sweep", {}).get("best_f1", {})
    if best:
        ax.axhline(float(best["threshold"]), color="#2b8a3e", linestyle=":", label="Best-F1 threshold")
    attack_mask = attack["attack_label"] > 0
    if attack_mask.any():
        ax.fill_between(t, 0, attack["spoof_score"].max() * 1.08, where=attack_mask, color="#ffd43b", alpha=0.28, label="Injected attack")
    det = attack["detected"] > 0
    if det.any():
        ax.scatter(t[det], attack.loc[det, "spoof_score"], s=10, color="#c92a2a", label="Detected samples", zorder=3)
    ax.set_xlabel("Experiment time (s)")
    ax.set_ylabel("Score")
    ax.set_title("Spoof-score timeline with synthetic attack")
    ax.legend(loc="upper right", fontsize=8)
    savefig(output_dir / "spoof_score_timeline.png")


def plot_raw_observation_summary(rinex_epoch: pd.DataFrame, output_dir: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 6.0), sharex=True)
    t = rinex_epoch["time_s"]
    axes[0].plot(t, rinex_epoch["satellite_count"], color="#1c7ed6", linewidth=1.0)
    axes[0].set_ylabel("Satellites")
    axes[0].set_title("RINEX raw-observation summary")
    axes[1].plot(t, rinex_epoch["mean_cn0_dbhz"], color="#e67700", linewidth=1.0)
    axes[1].set_ylabel("Mean C/N0\n(dB-Hz)")
    axes[2].plot(t, rinex_epoch["code_delta_rms_m"], color="#5f3dc4", linewidth=1.0)
    axes[2].set_ylabel("Code delta\nRMS (m)")
    axes[2].set_xlabel("RINEX time since first observation (s)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    savefig(output_dir / "raw_observation_summary.png")


def plot_raw_raim_timeline(attack: pd.DataFrame, output_dir: Path) -> None:
    required = {"raw_raim_score", "raw_reference_residual_rms_m", "raw_raim_detected"}
    if not required.issubset(set(attack.columns)):
        return
    if float(pd.to_numeric(attack["raw_raim_used_satellite_count"], errors="coerce").fillna(0).max()) <= 0.0:
        return
    fig, ax = plt.subplots(figsize=(9.0, 3.9))
    t = attack["time_s"]
    raim_score = pd.to_numeric(attack["raw_raim_score"], errors="coerce").fillna(0.0)
    reference_rms = pd.to_numeric(attack["raw_reference_residual_rms_m"], errors="coerce").fillna(0.0)
    ax.plot(t, raim_score, color="#0b7285", linewidth=1.2, label="RAIM score")
    ax.axhline(1.0, color="#d9480f", linestyle="--", linewidth=1.0, label="RAIM threshold")
    attack_mask = attack["attack_label"] > 0
    if attack_mask.any():
        upper = max(1.2, float(raim_score.max()) * 1.08)
        ax.fill_between(t, 0, upper, where=attack_mask, color="#ffd43b", alpha=0.25, label="Injected attack")
    det = pd.to_numeric(attack["raw_raim_detected"], errors="coerce").fillna(0) > 0
    if det.any():
        ax.scatter(t[det], raim_score[det], s=13, color="#c92a2a", label="RAIM detections", zorder=3)
    ax.set_xlabel("Experiment time (s)")
    ax.set_ylabel("RAIM score")
    ax2 = ax.twinx()
    ax2.plot(t, reference_rms, color="#5f3dc4", linewidth=1.0, alpha=0.72, label="Reference residual RMS")
    ax2.set_ylabel("Reference RMS (m)")
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="upper right", fontsize=8)
    ax.set_title("Broadcast-ephemeris raw pseudorange residuals")
    ax.grid(True, alpha=0.25)
    savefig(output_dir / "raw_raim_timeline.png")


def compute_sweep(df: pd.DataFrame):
    labels = (df["attack_label"].to_numpy() >= 0.5).astype(int)
    scores = df["spoof_score"].to_numpy(dtype=float)
    thresholds = np.linspace(float(np.nanmin(scores)), float(np.nanmax(scores)), 160)
    precision, recall, f1 = [], [], []
    for threshold in thresholds:
        det = scores >= threshold
        tp = np.sum((labels == 1) & det)
        fp = np.sum((labels == 0) & det)
        fn = np.sum((labels == 1) & (~det))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        precision.append(p)
        recall.append(r)
        f1.append(2 * p * r / (p + r) if p + r else 0.0)
    return thresholds, np.array(precision), np.array(recall), np.array(f1)


def plot_threshold_calibration(attack: pd.DataFrame, output_dir: Path) -> None:
    thresholds, precision, recall, f1 = compute_sweep(attack)
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.plot(thresholds, precision, label="Precision", color="#1864ab")
    ax.plot(thresholds, recall, label="Recall", color="#2b8a3e")
    ax.plot(thresholds, f1, label="F1", color="#c92a2a")
    best_idx = int(np.argmax(f1))
    ax.scatter([thresholds[best_idx]], [f1[best_idx]], color="#c92a2a", s=32, zorder=3)
    ax.set_xlabel("Score threshold")
    ax.set_ylabel("Metric")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title("Threshold calibration on synthetic spoofing run")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.25)
    savefig(output_dir / "threshold_calibration.png")


def plot_constellation_distribution(summary: dict, output_dir: Path) -> None:
    systems = summary.get("systems", {})
    order = ["G", "R", "E", "C", "J", "I"]
    names = {"G": "GPS", "R": "GLONASS", "E": "Galileo", "C": "BDS", "J": "QZSS", "I": "IRNSS"}
    labels = [names.get(key, key) for key in order if key in systems]
    values = [systems[key] for key in order if key in systems]
    fig, ax = plt.subplots(figsize=(7.2, 3.7))
    bars = ax.bar(labels, values, color=["#1c7ed6", "#f08c00", "#2b8a3e", "#5f3dc4", "#c92a2a", "#0b7285"])
    ax.set_ylabel("Satellite-observation rows")
    ax.set_title("RINEX constellation distribution")
    ax.bar_label(bars, padding=3, fontsize=8)
    ax.grid(axis="y", alpha=0.22)
    savefig(output_dir / "constellation_distribution.png")


def plot_adaptive_baseline_comparison(detector_summary: pd.DataFrame, output_dir: Path) -> None:
    order = [
        "raim_only",
        "pseudorange_glrt_only",
        "lio_residual_only",
        "fixed_fused",
        "adaptive_seq_full",
    ]
    labels = {
        "raim_only": "RAIM",
        "pseudorange_glrt_only": "PR GLRT",
        "lio_residual_only": "LIO-GNSS",
        "fixed_fused": "Fixed fused",
        "adaptive_seq_full": "Adaptive seq.",
    }
    data = detector_summary.set_index("detector").loc[[item for item in order if item in set(detector_summary["detector"])]]
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(8.8, 3.9))
    ax.bar(x - 0.18, data["attack_f1_mean"], width=0.36, label="Attack F1", color="#1864ab")
    ax.bar(x + 0.18, data["mean_false_alarm_per_min"] / max(1.0, float(data["mean_false_alarm_per_min"].max())), width=0.36, label="FA/min (normalized)", color="#e67700")
    ax.set_xticks(x)
    ax.set_xticklabels([labels.get(idx, idx) for idx in data.index], rotation=18, ha="right")
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("Score")
    ax.set_title("Baseline comparison across the experiment matrix")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    savefig(output_dir / "adaptive_baseline_comparison.png")


def plot_attack_matrix_heatmap(matrix: pd.DataFrame, output_dir: Path) -> None:
    attack = matrix[(matrix["detector"] == "adaptive_seq_full") & (matrix["scenario_type"] == "synthetic_spoofing")]
    if attack.empty:
        return
    pivot = attack.pivot_table(index="strength_m", columns="ramp_s", values="f1", aggfunc="mean")
    pivot = pivot.sort_index().sort_index(axis=1)
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    im = ax.imshow(pivot.to_numpy(dtype=float), origin="lower", aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels([f"{value:g}" for value in pivot.columns])
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([f"{value:g}" for value in pivot.index])
    ax.set_xlabel("Ramp duration (s)")
    ax.set_ylabel("Attack strength (m)")
    ax.set_title("Adaptive sequential detector F1 over attack matrix")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            ax.text(j, i, f"{pivot.iloc[i, j]:.2f}", ha="center", va="center", color="white", fontsize=8)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("F1")
    savefig(output_dir / "attack_matrix_heatmap.png")


def plot_ablation_comparison(detector_summary: pd.DataFrame, output_dir: Path) -> None:
    order = [
        "adaptive_seq_full",
        "adaptive_seq_no_raw",
        "adaptive_seq_no_lio",
        "adaptive_seq_no_env",
        "adaptive_seq_no_cusum",
    ]
    labels = {
        "adaptive_seq_full": "Full",
        "adaptive_seq_no_raw": "No raw",
        "adaptive_seq_no_lio": "No LIO",
        "adaptive_seq_no_env": "No env",
        "adaptive_seq_no_cusum": "No CUSUM",
    }
    data = detector_summary.set_index("detector").loc[[item for item in order if item in set(detector_summary["detector"])]]
    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    bars = ax.bar([labels.get(idx, idx) for idx in data.index], data["attack_f1_mean"], color=["#2b8a3e", "#5c940d", "#0b7285", "#e67700", "#c92a2a"])
    ax.bar_label(bars, labels=[f"{value:.2f}" for value in data["attack_f1_mean"]], padding=3, fontsize=8)
    ax.set_ylim(0, max(0.55, float(data["attack_f1_mean"].max()) * 1.22))
    ax.set_ylabel("Mean attack F1")
    ax.set_title("Ablation of the adaptive sequential detector")
    ax.grid(axis="y", alpha=0.25)
    savefig(output_dir / "ablation_comparison.png")


def plot_adaptive_cusum_timeline(timeline: pd.DataFrame, output_dir: Path) -> None:
    if timeline.empty:
        return
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 6.0), sharex=True)
    t = timeline["time_s"]
    attack = timeline["attack_label"] > 0
    axes[0].plot(t, timeline["detector_score"], color="#1864ab", linewidth=1.1, label="Fused GLRT score")
    axes[0].plot(t, timeline["adaptive_threshold"], color="#d9480f", linestyle="--", linewidth=1.0, label="Adaptive threshold")
    axes[0].set_ylabel("Score")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[1].plot(t, timeline["cusum"], color="#2b8a3e", linewidth=1.1, label="CUSUM")
    det = timeline["detected"] > 0
    if det.any():
        axes[1].scatter(t[det], timeline.loc[det, "cusum"], color="#c92a2a", s=10, label="Detections", zorder=3)
    axes[1].set_ylabel("CUSUM")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[2].plot(t, timeline["confidence"], color="#5f3dc4", linewidth=1.0, label="Confidence")
    axes[2].plot(t, timeline["environment_degradation"], color="#e67700", linewidth=1.0, alpha=0.8, label="Environment degradation")
    axes[2].set_ylabel("Probability / index")
    axes[2].set_xlabel("Experiment time (s)")
    axes[2].legend(loc="upper right", fontsize=8)
    for ax in axes:
        if attack.any():
            ax.fill_between(t, ax.get_ylim()[0], ax.get_ylim()[1], where=attack, color="#ffd43b", alpha=0.18)
        ax.grid(True, alpha=0.25)
    axes[0].set_title("Environment-adaptive sequential GLRT timeline")
    savefig(output_dir / "adaptive_cusum_timeline.png")


def macro(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}\n"


def write_metrics_tex(
    path: Path,
    attack: pd.DataFrame,
    attack_metrics: dict,
    clean_metrics: dict,
    rinex_summary: dict,
    detector_summary: pd.DataFrame,
    scenario_summary: pd.DataFrame,
    experiment_summary: dict,
) -> None:
    best_f1 = attack_metrics.get("threshold_sweep", {}).get("best_f1", {})
    latency = attack_metrics.get("detection_latency_s", {})
    raw_raim_coverage = int((pd.to_numeric(attack.get("raw_raim_used_satellite_count", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
    raw_raim_detected = int((pd.to_numeric(attack.get("raw_raim_detected", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
    raw_reference_mean = float(pd.to_numeric(attack.get("raw_reference_residual_rms_m", pd.Series(dtype=float)), errors="coerce").fillna(0).mean())
    summary_by_detector = detector_summary.set_index("detector")
    paired_stats = experiment_summary.get("paired_statistics", {})

    def dvalue(detector: str, column: str) -> float:
        if detector not in summary_by_detector.index:
            return 0.0
        return float(summary_by_detector.loc[detector, column])

    rows = [
        macro("RinexEpochCount", f"{int(rinex_summary['epochs'])}"),
        macro("RinexSatelliteRowCount", f"{int(rinex_summary['satellite_rows'])}"),
        macro("DetectionRowCount", f"{len(attack)}"),
        macro("RinexCoverageRows", f"{int((attack['rinex_satellite_count'] > 0).sum())}"),
        macro("AttackPrecision", f"{attack_metrics['precision']:.3f}"),
        macro("AttackRecall", f"{attack_metrics['recall']:.3f}"),
        macro("AttackFone", f"{attack_metrics['f1']:.3f}"),
        macro("AttackRocAuc", f"{attack_metrics['roc_auc']:.3f}"),
        macro("AttackLatencyMean", f"{float(latency.get('mean') or 0.0):.3f}"),
        macro("BestFoneThreshold", f"{float(best_f1.get('threshold', 0.0)):.3f}"),
        macro("BestFonePrecision", f"{float(best_f1.get('precision', 0.0)):.3f}"),
        macro("BestFoneRecall", f"{float(best_f1.get('recall', 0.0)):.3f}"),
        macro("BestFoneScore", f"{float(best_f1.get('f1', 0.0)):.3f}"),
        macro("CleanFalseAlarmPerMinute", f"{clean_metrics['false_alarm_per_min']:.3f}"),
        macro("RinexMeanSatellites", f"{float(rinex_summary['satellite_count']['mean']):.2f}"),
        macro("RawRaimCoverageRows", f"{raw_raim_coverage}"),
        macro("RawRaimDetectedRows", f"{raw_raim_detected}"),
        macro("RawReferenceResidualMean", f"{raw_reference_mean:.3f}"),
        macro("MatrixScenarioCount", f"{len(scenario_summary)}"),
        macro("MatrixAttackScenarioCount", f"{int((scenario_summary['scenario_type'] == 'synthetic_spoofing').sum())}"),
        macro("AdaptiveSeqPrecision", f"{dvalue('adaptive_seq_full', 'attack_precision_mean'):.3f}"),
        macro("AdaptiveSeqRecall", f"{dvalue('adaptive_seq_full', 'attack_recall_mean'):.3f}"),
        macro("AdaptiveSeqFone", f"{dvalue('adaptive_seq_full', 'attack_f1_mean'):.3f}"),
        macro("AdaptiveSeqLatency", f"{dvalue('adaptive_seq_full', 'attack_latency_mean_s'):.3f}"),
        macro("AdaptiveSeqFalseAlarm", f"{dvalue('adaptive_seq_full', 'mean_false_alarm_per_min'):.3f}"),
        macro("AdaptiveSeqDegradedFalseAlarm", f"{dvalue('adaptive_seq_full', 'degraded_false_alarm_per_min'):.3f}"),
        macro("FixedFusedMatrixFone", f"{dvalue('fixed_fused', 'attack_f1_mean'):.3f}"),
        macro("FixedFusedMatrixFalseAlarm", f"{dvalue('fixed_fused', 'mean_false_alarm_per_min'):.3f}"),
        macro("PseudorangeGlrtFone", f"{dvalue('pseudorange_glrt_only', 'attack_f1_mean'):.3f}"),
        macro("LioResidualFone", f"{dvalue('lio_residual_only', 'attack_f1_mean'):.3f}"),
        macro("RaimOnlyFone", f"{dvalue('raim_only', 'attack_f1_mean'):.3f}"),
        macro("NoRawFone", f"{dvalue('adaptive_seq_no_raw', 'attack_f1_mean'):.3f}"),
        macro("NoLioFone", f"{dvalue('adaptive_seq_no_lio', 'attack_f1_mean'):.3f}"),
        macro("NoEnvFone", f"{dvalue('adaptive_seq_no_env', 'attack_f1_mean'):.3f}"),
        macro("NoCusumFone", f"{dvalue('adaptive_seq_no_cusum', 'attack_f1_mean'):.3f}"),
        macro("AdaptiveVsFixedFoneGain", f"{float(paired_stats.get('mean_f1_difference', 0.0)):.3f}"),
        macro("AdaptiveVsFixedCiLow", f"{float(paired_stats.get('ci95_low', 0.0)):.3f}"),
        macro("AdaptiveVsFixedCiHigh", f"{float(paired_stats.get('ci95_high', 0.0)):.3f}"),
        macro("AdaptiveVsFixedPvalue", f"{float(paired_stats.get('sign_test_p_value', 1.0)):.3f}"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(rows), encoding="utf-8")
    print(f"wrote {path}")


def main() -> int:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    metrics_tex = resolve(args.metrics_tex)
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "figure.facecolor": "white",
        }
    )
    (
        attack,
        clean,
        rinex_epoch,
        attack_metrics,
        clean_metrics,
        rinex_summary,
        matrix,
        detector_summary,
        scenario_summary,
        adaptive_timeline,
        experiment_summary,
    ) = load_inputs(args)
    _ = clean
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_architecture(output_dir)
    plot_trajectory_quality(attack, output_dir)
    plot_spoof_score(attack, attack_metrics, output_dir)
    plot_raw_observation_summary(rinex_epoch, output_dir)
    plot_raw_raim_timeline(attack, output_dir)
    plot_threshold_calibration(attack, output_dir)
    plot_constellation_distribution(rinex_summary, output_dir)
    plot_adaptive_baseline_comparison(detector_summary, output_dir)
    plot_attack_matrix_heatmap(matrix, output_dir)
    plot_ablation_comparison(detector_summary, output_dir)
    plot_adaptive_cusum_timeline(adaptive_timeline, output_dir)
    write_metrics_tex(
        metrics_tex,
        attack,
        attack_metrics,
        clean_metrics,
        rinex_summary,
        detector_summary,
        scenario_summary,
        experiment_summary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
