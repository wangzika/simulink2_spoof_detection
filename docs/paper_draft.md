# Toward Robust GNSS Spoofing Detection with Raw Observation and LiDAR-Inertial Consistency

## Abstract

GNSS spoofing can induce hazardous position errors in autonomous navigation systems while preserving apparently plausible satellite measurements. This paper presents a reproducible spoofing-detection platform that combines raw GNSS observation consistency with LiDAR-inertial odometry cross-checks. The platform aligns RTKLIB positioning outputs, raw GNSS update diagnostics, and FAST_GLIO fusion logs on a unified time axis, supports controlled synthetic spoofing injection, and reports detection accuracy, false alarm rate, and latency. Our initial baseline uses pseudorange residual statistics, Mahalanobis gating, RTK quality indicators, Doppler/TDCP diagnostics, and LiDAR/IMU-GNSS consistency residuals. The complete evaluation protocol is designed to support ablation studies across attack magnitude, ramp rate, satellite subset bias, and degraded-environment conditions.

## 1. Introduction

GNSS is widely used by autonomous vehicles, robots, and aerial platforms, but its open civilian signal structure makes it vulnerable to spoofing. A successful spoofing attack can gradually pull a navigation solution away from the true trajectory without causing an immediate loss of lock. Classical receiver-side checks based only on positioning residuals are often insufficient in complex environments, where multipath, occlusion, and poor satellite geometry can mimic attack-like anomalies.

This work studies a multi-source detection strategy. Instead of treating GNSS as an isolated sensor, we compare raw GNSS consistency with independent LiDAR-inertial motion constraints. The central hypothesis is that spoofing produces coupled anomalies across pseudorange residuals, Doppler/TDCP consistency, and GNSS-to-LIO alignment that can be separated from ordinary degradation by adaptive gating and sequential decision logic.

Contributions:

1. A reproducible C++/Python experimental platform linking flight simulation, RTKLIB data products, FAST_GLIO logs, and visualization.
2. A time-synchronized detection dataset format that preserves RTK quality, DOP, raw pseudorange diagnostics, Doppler/TDCP diagnostics, and LIO-GNSS residuals.
3. A controlled spoofing injection mechanism for evaluating attack magnitude, ramp time, and pseudorange delay.
4. A baseline multi-cue detector with standard metrics: precision, recall, F1, ROC AUC, false alarms per minute, and detection latency.

## 2. Related Work

Prior GNSS spoofing detection methods can be grouped into signal-level monitoring, measurement-level residual tests, navigation filter innovation tests, and cross-modal consistency checks. Signal-level approaches require access to receiver tracking channels or specialized antennas. Measurement-level methods such as RAIM and GLRT are easier to deploy but can be sensitive to urban multipath and satellite geometry. Cross-modal methods use inertial, vision, LiDAR, wheel odometry, or map constraints to validate GNSS motion. This paper focuses on a deployable measurement/navigation-layer design that uses raw GNSS diagnostics and LiDAR-inertial consistency without requiring custom RF hardware.

## 3. System Overview

The platform contains four layers:

1. Data ingestion: RINEX/RTKLIB products, FAST_GLIO loose/tight GNSS fusion logs, and simulation CSVs.
2. Time synchronization: GPS week/TOW and GPST timestamps are converted to Unix time with an explicit GPST-UTC offset.
3. Feature construction: pseudorange residual statistics, Doppler/TDCP status, RTK quality, DOP, LiDAR/IMU-GNSS residuals, and environment-quality indicators.
4. Detection and evaluation: baseline scoring, sequential confirmation, attack labels, metrics, and reports.

## 4. Attack Model

We consider spoofing attacks that introduce a controlled GNSS measurement bias over a time interval. The current platform supports residual-level injection using a three-dimensional offset and a pseudorange common delay with smooth ramp-in/ramp-out. Future versions will extend this to satellite-specific raw-observation injection, including satellite subset bias, clock drift, and slowly varying position pull-off attacks.

## 5. Detection Method

The baseline detector computes a normalized spoofing score:

- LiDAR/IMU-GNSS residual score.
- Mahalanobis innovation score relative to the fusion gate.
- Pseudorange RMS and maximum residual score.
- Doppler/TDCP anomaly score.
- RTK quality and ambiguity-ratio penalty.

The detector triggers when the fused score exceeds a threshold and confirms spoofing after a configurable number of consecutive triggered samples. This baseline is intentionally transparent; it will serve as the reference for later adaptive and learned variants.

## 6. Experimental Protocol

Datasets:

- Clean real dataset from RTKLIB and FAST_GLIO logs.
- Synthetic spoofed variants generated from the same real trajectory.
- Simulation routes from the C++ flight simulator for controlled closed-loop validation.

Metrics:

- Precision, recall, specificity, F1.
- ROC AUC.
- False alarms per minute on clean intervals.
- Detection latency after attack onset.
- Ablation performance under removed feature groups.

Planned experiments:

- Attack offset magnitude sweep.
- Pseudorange delay sweep.
- Ramp duration sweep.
- GNSS degradation and urban-canyon-like quality variation.
- Baseline comparison: RAIM-only, LIO-GNSS-only, pseudorange-only, fused baseline, adaptive fused method.

## 7. Preliminary Platform Status

The current implementation already builds synchronized detection CSV files and evaluation reports. Initial smoke tests verify that clean synthetic fixtures produce no false positives, while injected spoofing windows are detected. Real-data reports will be filled after the full experiment matrix is generated and reviewed.

## 8. Limitations and Next Steps

The present spoofing injection is residual-level rather than raw observation-level. This is useful for platform verification, but a top-tier GNSS paper should include raw RINEX-level injection and satellite-wise residual analysis. The next step is to parse rover/base RINEX observations, construct per-satellite features, and compare them against RTKLIB/FAST_GLIO internal diagnostics.

## 9. Conclusion

This paper will present a reproducible GNSS spoofing-detection platform that integrates raw GNSS diagnostics with LiDAR-inertial consistency. The proposed evaluation pipeline is designed to measure both detection reliability and operational latency, enabling systematic comparison of classical residual tests and multi-modal adaptive detectors.

