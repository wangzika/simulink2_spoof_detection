# C++ F7 Flight Simulation

中文总览和操作手册见 [docs/project_architecture_and_usage.md](docs/project_architecture_and_usage.md)。该文档按当前项目状态整理了整体架构、数据流、C++ 仿真、ImGui/Rerun 可视化、真实数据适配、论文实验矩阵、route-split、LaTeX 论文生成和投稿前限制。

This is a standalone C++17 migration prototype for the MATLAB/Simulink GPS attack project. It rebuilds the main closed-loop structure in native C++:

- trajectory planning
- quadrotor rigid-body dynamics
- IMU/GPS/barometer/UWB/optical-flow/magnetometer sensor simulation
- GPS spoofing attack injection
- lightweight inertial/GPS/UWB/optical-flow/barometer/magnetometer navigation fusion
- migrated `PARAM_INAV_*`-style parameter struct
- Stateflow-inspired flight/GPS mode logic
- 3-axis Kalman fusion with position, velocity, and acceleration-bias states
- position, velocity, and attitude control
- pseudorange residual and GLRT-based spoofing detection
- GPS ephemeris, satellite ECEF, receiver ECEF/ENU, pseudorange simulation, LMS filtering, and enhanced Kalman/disturbance-observer pseudorange prediction
- disturbance-observer-inspired rotational residual estimate
- GPS rejection/reacquisition failsafe reference handling and landing descent logic
- CSV logging for analysis
- standalone HTML dashboard generation
- optional Dear ImGui desktop dashboard
- optional Rerun 3D/time-series dashboard
- CTest-based native C++ regression tests

It is not a bit-exact translation of the Simulink model. The original model contains Stateflow charts, Simulink Bus objects, generated code, and many platform-specific details. This C++ version is an independent, inspectable implementation of the same system-level architecture.

## Build

```bash
cd /Users/wangzhibo/Desktop/博士研究/simulink2/cpp_flight_sim
cmake -S . -B build
cmake --build build
```

## Test

```bash
ctest --test-dir build --output-on-failure
```

The test executable covers coordinate transforms, chi-square thresholding, trajectory continuity, configured landing timing, auxiliary sensor fusion while GPS is untrusted, no-attack false-alarm behavior, and attack detection/rejection behavior.

## Run

```bash
./build/f7_sim
```

By default it writes:

```text
simulation.csv
dashboard.html
```

The CSV contains true state, navigation estimate, GPS measurement, trajectory reference, attack flag, detector flag, pseudorange residual metrics, GLRT statistic/threshold/result, flight mode, GPS trust/rejection state, acceleration-bias estimate, and control outputs.

It also logs UWB position, optical-flow horizontal velocity, magnetometer yaw, and each auxiliary sensor's valid flag so MATLAB/Python/offline tools can compare GPS-only and multi-sensor fusion behavior.

The HTML dashboard is a dependency-free local file. Open it in a browser:

```bash
open build/dashboard.html
```

## Custom Simulation Scenarios

The simulator can now run custom routes without editing C++ code.

Quick built-in trajectory selection:

```bash
./build/f7_sim --trajectory hover --duration 20 --output build/hover.csv
./build/f7_sim --trajectory figure8 --duration 50 --output build/figure8.csv
```

Waypoint CSV route:

```csv
time_s,x,y,z,yaw_rad
0,0,0,0,0
4,0,0,1.8,0
10,2.5,0,1.8,0
16,2.5,2.5,2.0,1.5707963268
22,0,2.5,1.8,3.1415926536
28,0,0,1.8,-1.5707963268
```

Run a waypoint route directly:

```bash
./build/f7_sim --trajectory-file scenarios/custom_square.csv --duration 42 --output build/custom_square.csv --html build/custom_square.html
```

For a full reusable experiment, use a key-value scenario file:

```bash
./build/f7_sim --scenario scenarios/custom_square.scenario
python tools/rerun_viewer.py build/custom_square.csv
```

Scenario files use `key=value` lines. Supported keys include:

```text
duration_s, dt_s, output_csv, output_html, write_html
trajectory, trajectory_file
attack_start_s, attack_end_s, attack_offset_m, pseudorange_delay_m, attack_ramp_s
glrt_threshold, glrt_false_alarm_rate, pseudorange_noise_sigma_m, gps_residual_threshold_m
consecutive_samples, glrt_warmup_samples
enable_uwb, enable_optical_flow, enable_magnetometer
reference_lat_deg, reference_lon_deg, reference_alt_m
```

Print a starter scenario template:

```bash
./build/f7_sim --print-scenario-template
```

## Adapting Your Dataset

For the current `../full_data/gnss` dataset, the quickest path is to use the RTKLIB output `rtklib.pos` as the measured route. The adapter converts ECEF positions to local ENU, generates a waypoint route for `f7_sim`, and also emits a replay CSV that can be opened directly in Rerun.

Generate dataset artifacts:

```bash
python tools/rtklib_dataset_adapter.py \
  --pos ../full_data/gnss/rtklib.pos \
  --dop ../full_data/gnss/dop.txt \
  --name full_data_rtklib \
  --output-dir build/datasets/full_data_rtklib
```

This writes:

```text
build/datasets/full_data_rtklib/full_data_rtklib_waypoints.csv
build/datasets/full_data_rtklib/full_data_rtklib.scenario
build/datasets/full_data_rtklib/full_data_rtklib_replay.csv
build/datasets/full_data_rtklib/full_data_rtklib_summary.json
```

Open the real RTK route and quality metrics in Rerun:

```bash
python tools/rerun_viewer.py build/datasets/full_data_rtklib/full_data_rtklib_replay.csv
```

Run the simulator along the adapted route:

```bash
./build/f7_sim --scenario build/datasets/full_data_rtklib/full_data_rtklib.scenario
python tools/rerun_viewer.py build/datasets/full_data_rtklib/full_data_rtklib_sim.csv
```

The adapter defaults to a constant simulated flight altitude of `1.8 m` while preserving the measured horizontal ENU path. Use `--preserve-altitude` if you want the simulated z coordinate to follow the RTK local up component instead.

Useful CMake shortcuts are enabled when `../full_data/gnss/rtklib.pos` exists:

```bash
cmake --build build --target adapt_full_data
cmake --build build --target simulate_full_data
```

To test synthetic spoofing on your measured route, pass attack options to the adapter:

```bash
python tools/rtklib_dataset_adapter.py \
  --pos ../full_data/gnss/rtklib.pos \
  --dop ../full_data/gnss/dop.txt \
  --name full_data_attack \
  --output-dir build/datasets/full_data_attack \
  --attack-start 180 \
  --attack-end 260 \
  --attack-offset 4.0,-2.0,0.8
./build/f7_sim --scenario build/datasets/full_data_attack/full_data_attack.scenario
```

## Paper Platform

The repository now includes the first reproducible layer for a GNSS spoof-detection paper platform:

- `tools/build_detection_dataset.py` merges RTKLIB `.pos`/DOP data with FAST_GLIO loose/raw/tight GNSS logs.
- `tools/extract_rinex_features.py` extracts RINEX per-satellite raw observation features and per-epoch summaries.
- `tools/compute_raw_gnss_residuals.py` parses GPS/Galileo/BeiDou Kepler broadcast ephemerides, estimates per-constellation clock states, computes raw pseudorange residuals, writes RAIM/reference residual summaries, and emits Doppler/TDCP residual statistics. GPS/Galileo residuals are validated on the current data; BeiDou is wired through the framework and marked experimental pending BDS-specific corrections.
- `tools/inject_observation_attack.py` injects reproducible observation-level pseudorange attacks into per-satellite RINEX feature CSVs.
- `tools/adaptive_sequential_detector.py` implements the Environment-Adaptive Sequential GLRT detector plus RAIM, robust RAIM, EKF innovation, pseudorange GLRT, LIO-GNSS, fixed fused, fixed CUSUM fused, adaptive fused, and ablation detectors.
- `tools/run_experiment_matrix.py` generates clean, degraded non-attack, multi-strength, multi-ramp, multi-type spoofing experiments, baseline/ablation comparisons, attack-factor summaries, and parameter-sensitivity sweeps.
- `tools/ml_baseline.py` implements a dependency-light RandomForest/XGBoost-style tree-ensemble classifier baseline.
- `tools/route_split_experiments.py` runs train-route tuning, test-route evaluation, and optional ML-baseline comparisons across route CSVs.
- `datasets/routes.yaml` and `tools/run_configured_routes.py` provide a reproducible multi-route experiment registry, so new routes can be added without editing command lines.
- `tools/evaluate_detection.py` reports precision, recall, F1, ROC AUC, false alarms per minute, and detection latency.
- `tools/smoke_paper_pipeline.py`, `tools/smoke_rinex_features.py`, `tools/smoke_raw_residuals.py`, `tools/smoke_adaptive_detector.py`, `tools/smoke_route_split_experiments.py`, and `tools/smoke_configured_routes.py` are self-contained CTest smoke tests.
- `docs/paper_platform.md` describes the staged platform roadmap and verification commands.
- `docs/gnss_spoofing_literature.md` summarizes GNSS spoofing/jamming detection literature by method family for the Related Work section.
- `docs/paper_draft.md` contains the initial paper draft skeleton.

Run the current full-data paper pipeline when `../full_data/gnss` and FAST_GLIO logs are present:

```bash
cmake --build build --target paper_pipeline
```

Individual targets are also available: `rinex_features`, `raw_gnss_residuals`, `raw_observation_attack`, `raw_gnss_residuals_attack`, `paper_dataset`, `paper_dataset_attack`, `paper_dataset_attack_full_timeline`, `paper_adaptive_attack_full_timeline`, `paper_rerun_record`, `paper_rerun_view`, `paper_eval_clean`, `paper_eval_attack`, `adaptive_experiments`, `route_split_experiments`, and `configured_route_experiments`.

Generate the LaTeX figures and PDF draft:

```bash
cmake --build build --target adaptive_experiments
cmake --build build --target paper_figures
cmake --build build --target paper_pdf
```

The draft source is `paper/main.tex`; the compiled PDF is written to `paper/build/main.pdf`.

Extract raw RINEX observation features directly:

```bash
python tools/extract_rinex_features.py \
  --obs ../full_data/gnss/rover.obs \
  --name full_data_rover \
  --output-dir build/paper_platform/rinex_rover
```

This writes:

```text
build/paper_platform/rinex_rover/full_data_rover_satellite_features.csv
build/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv
build/paper_platform/rinex_rover/full_data_rover_rinex_summary.json
```

Compute GPS broadcast-ephemeris pseudorange residuals and the RAIM baseline:

```bash
python tools/compute_raw_gnss_residuals.py \
  --obs ../full_data/gnss/rover.obs \
  --nav ../full_data/gnss/BRDM00DLR_S_20240290000_01D_MN.rnx \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --systems G \
  --name full_data_raw_clean \
  --output-dir build/paper_platform/raw_gnss_clean
```

Run the multi-constellation raw-residual framework on a short GPS/Galileo/BeiDou sample:

```bash
python tools/compute_raw_gnss_residuals.py \
  --obs ../full_data/gnss/rover.obs \
  --nav ../full_data/gnss/BRDM00DLR_S_20240290000_01D_MN.rnx \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --systems G,E,C \
  --max-epochs 80 \
  --name multi_gnss_smoke \
  --output-dir build/paper_platform/multi_gnss_smoke
```

The output summary reports `supported_broadcast_systems`, ephemeris counts by constellation, missing ephemerides, used systems, and per-system WLS/reference clock biases.

Inject an observation-level pseudorange attack and recompute raw residuals:

```bash
python tools/inject_observation_attack.py \
  --satellite-features build/paper_platform/rinex_rover/full_data_rover_satellite_features.csv \
  --name full_data_rover_attack \
  --output-dir build/paper_platform/rinex_rover_attack \
  --relative-origin-csv /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_loose_diag.csv \
  --attack-window +180:+260 \
  --common-delay-m 18.0 \
  --per-satellite-bias-m 180.0 \
  --satellite-mode list \
  --satellites G02 \
  --systems G

python tools/compute_raw_gnss_residuals.py \
  --satellite-features build/paper_platform/rinex_rover_attack/full_data_rover_attack_satellite_features.csv \
  --nav ../full_data/gnss/BRDM00DLR_S_20240290000_01D_MN.rnx \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --systems G \
  --name full_data_raw_attack \
  --output-dir build/paper_platform/raw_gnss_attack
```

Or run the tools directly:

```bash
python tools/build_detection_dataset.py \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --dop ../full_data/gnss/dop.txt \
  --loose /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_loose_diag.csv \
  --raw /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_raw_update_log.csv \
  --tight /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_tight_pose.csv \
  --rinex-summary build/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv \
  --name full_data_attack \
  --output-dir build/paper_platform/full_data_attack \
  --attack-window +180:+260 \
  --attack-offset 8.0,-3.0,0.5 \
  --pseudorange-delay 18.0

python tools/evaluate_detection.py \
  build/paper_platform/full_data_attack/full_data_attack_detection.csv
```

Run the method-paper adaptive detector matrix directly:

```bash
python tools/run_experiment_matrix.py \
  --base-csv build/paper_platform/full_data_clean/full_data_clean_detection.csv \
  --output-dir build/paper_platform/adaptive_experiments
```

This writes detector comparisons and ablations:

```text
build/paper_platform/adaptive_experiments/matrix_results.csv
build/paper_platform/adaptive_experiments/detector_summary.csv
build/paper_platform/adaptive_experiments/scenario_summary.csv
build/paper_platform/adaptive_experiments/attack_type_summary.csv
build/paper_platform/adaptive_experiments/attack_strength_summary.csv
build/paper_platform/adaptive_experiments/attack_ramp_summary.csv
build/paper_platform/adaptive_experiments/environment_summary.csv
build/paper_platform/adaptive_experiments/integrity_summary.csv
build/paper_platform/adaptive_experiments/sensitivity_summary.csv
build/paper_platform/adaptive_experiments/attack_classification_summary.csv
build/paper_platform/adaptive_experiments/adaptive_timeline.csv
```

Run route-held-out style experiments across multiple detection CSVs:

```bash
python tools/route_split_experiments.py \
  --route route_a=build/paper_platform/full_data_clean/full_data_clean_detection.csv \
  --route route_b=/path/to/another_route_detection.csv \
  --train-routes route_a \
  --test-routes route_b \
  --output-dir build/paper_platform/route_split_experiments
```

This writes:

```text
build/paper_platform/route_split_experiments/tuning_summary.csv
build/paper_platform/route_split_experiments/train_results.csv
build/paper_platform/route_split_experiments/test_results.csv
build/paper_platform/route_split_experiments/detector_summary.csv
build/paper_platform/route_split_experiments/route_split_summary.json
```

When only one route is available, the CMake `route_split_experiments` target runs a same-route demonstration. For paper claims, use disjoint train/test route names.

For repeatable paper experiments, add routes and train/test splits to `datasets/routes.yaml`, then run the configured wrapper:

```bash
python tools/run_configured_routes.py \
  --config datasets/routes.yaml \
  --output-dir build/paper_platform/configured_route_experiments
```

or use the CMake shortcut:

```bash
cmake --build build --target configured_route_experiments
```

The configured run writes the same route-split result files plus:

```text
build/paper_platform/configured_route_experiments/configured_routes_manifest.json
```

## ImGui Desktop UI

The project includes an optional Dear ImGui desktop dashboard executable, `f7_imgui`. It reads the generated CSV and shows playback controls, flight status, GPS trust/rejection state, trajectory replay, UWB auxiliary points, and residual/GLRT plots.

It is conditionally built when these dependencies are present:

```text
third_party/imgui/          # official Dear ImGui source tree
GLFW                        # e.g. Homebrew /opt/homebrew/opt/glfw
OpenGL
```

Expected ImGui layout:

```text
third_party/imgui/imgui.cpp
third_party/imgui/imgui_draw.cpp
third_party/imgui/imgui_tables.cpp
third_party/imgui/imgui_widgets.cpp
third_party/imgui/backends/imgui_impl_glfw.cpp
third_party/imgui/backends/imgui_impl_opengl3.cpp
```

Build and run after placing Dear ImGui there:

```bash
cmake -S . -B build
cmake --build build
./build/f7_sim --output build/final_simulation.csv --html build/final_dashboard.html
open -n build/f7_imgui.app --args "$(pwd)/build/final_simulation.csv"
```

If `f7_imgui` is not built, CMake will print a status message explaining that ImGui sources or GLFW are missing. The core simulator and tests still build normally.

## Rerun Dashboard

The project also includes an optional Rerun viewer script, `tools/rerun_viewer.py`. It reads the generated CSV and opens a 3D/time-series dashboard with true, estimated, GPS, and reference trajectories; GPS attack segments; UWB points; live replay markers; residual, pseudorange RMS, GLRT, and GPS trust-state plots.

Install the Rerun Python SDK into the project-local dependency folder:

```bash
python -m pip install --target third_party/python_deps rerun-sdk
python -m pip install --target third_party/python_deps --upgrade numpy==1.26.4
```

The NumPy pin avoids a current macOS wheel ABI warning observed with `rerun-sdk` 0.33.1 while keeping all dependencies local to this project.

Run through CMake:

```bash
cmake --build build --target rerun_view
```

Or run the script directly against any generated CSV. By default it writes a `.rrd` beside the CSV and opens the Rerun Web Viewer in a browser using the WebGL renderer; pass `--native` if you want to try the native Rerun viewer instead.

```bash
./build/f7_sim --output build/final_simulation.csv --html build/final_dashboard.html
python tools/rerun_viewer.py build/final_simulation.csv
```

For an offline recording instead of opening the viewer:

```bash
cmake --build build --target rerun_record
python tools/rerun_viewer.py build/final_simulation.csv --save build/final_simulation.rrd --no-spawn
PYTHONPATH=third_party/python_deps:third_party/python_deps/rerun_sdk python -m rerun_cli build/final_simulation.rrd
```

For the paper attack experiment, build a full RTKLIB-timeline Rerun recording:

```bash
cmake --build build --target paper_rerun_record
python tools/rerun_paper_attack_viewer.py \
  build/paper_platform/full_data_attack_full_timeline/full_data_attack_full_timeline_detection.csv \
  --timeline build/paper_platform/full_data_attack_full_timeline/full_data_attack_full_timeline_adaptive_seq.csv \
  --satellite-features build/paper_platform/rinex_rover_attack/full_data_rover_attack_satellite_features.csv \
  --attack-summary build/paper_platform/rinex_rover_attack/full_data_rover_attack_attack_summary.json \
  --save build/paper_platform/paper_attack_visualization.rrd \
  --no-spawn
```

This recording explicitly logs attack start/end, observation-level pseudorange injection, first fixed-score alarm, first EA-SGLRT alarm, the full RTK trajectory, score timelines, CUSUM/confidence, and injected satellite-bias plots. Event text distinguishes attack-window detections from alarms outside the attack window. The standard paper-evaluation CSV is intentionally synchronized to the shorter FAST_GLIO-compatible timeline; the full-timeline target uses `--base-timeline rtk` so visualization covers the complete RTKLIB route.

## CLI Options

```bash
./build/f7_sim --duration 60 --dt 0.002 --output build/simulation.csv
./build/f7_sim --output build/simulation.csv --html build/dashboard.html
./build/f7_sim --attack-start 20 --attack-end 34 --attack-x 4.0
./build/f7_sim --attack-delay 8 --false-alarm 0.001
./build/f7_sim --threshold 0
./build/f7_sim --attack-ramp 2 --consecutive 2 --warmup 100
./build/f7_sim --reference-lat 31.2304 --reference-lon 121.4737 --reference-alt 4
./build/f7_sim --trajectory hover
./build/f7_sim --trajectory figure8
./build/f7_sim --trajectory-file scenarios/custom_square.csv
./build/f7_sim --scenario scenarios/custom_square.scenario
./build/f7_sim --no-uwb --no-flow --no-mag
./build/f7_sim --no-html
```

## Model Notes

Coordinate convention:

- world frame: ENU-like, `z` is up
- body frame: `+z` is thrust direction
- gravity: `(0, 0, -g)`

The controller uses a cascaded structure:

1. position/velocity PD control computes desired world acceleration
2. desired acceleration maps to thrust direction and total thrust
3. attitude PD control computes body moments
4. dynamics integrates translation and rotation

The navigation stack performs:

1. gyro integration for attitude propagation
2. accelerometer-based inertial prediction
3. 3-axis Kalman prediction with states `[position, velocity, acceleration_bias]`
4. trusted GPS position/velocity correction
5. UWB position correction, optical-flow horizontal velocity correction, barometer altitude correction, and magnetometer yaw correction
6. pseudorange residual calculation before correction

GPS spoofing is injected into the GPS position measurement and the pseudorange observations during the configured attack window. The pseudorange path computes satellite ECEF states from lightweight ephemerides, converts the receiver ENU state to ECEF, simulates true range, white noise, multipath, and attack delay, filters each satellite channel with LMS, predicts pseudorange with an enhanced Kalman/disturbance state, and applies a chi-square GLRT threshold derived from the configured false alarm rate.

The current version includes a Stateflow-inspired mode machine:

```text
Grounded -> Takeoff -> Mission -> GPS Suspect -> GPS Rejected -> GPS Reacquire -> Mission/Landing
```

During `GPS Rejected`, GPS measurements are not fused into the navigation estimate. The commanded reference switches to a vertical-hold failsafe so horizontal inertial drift does not consume attitude authority during long GPS outages. During `GPS Reacquire`, GPS is trusted again only after the detector has been quiet and the residual drops under the recovery gate for a configured period. During `Landing`, the controller follows a local vertical descent reference.

The default trajectory uses a smooth transition from takeoff hover to the circular mission segment. Custom waypoint trajectories are interpolated with a quintic smoothstep profile, producing position, velocity, and acceleration setpoints for the controller instead of discontinuous point jumps.

## Next Migration Steps

Implemented in this C++ migration but still simplified relative to the original Simulink project:

1. Replace the compact C++ Kalman filter with the exact generated Simulink `Navigation_F7` fusion equations.
2. Map every generated Simulink Bus field to C++ structs, including robotic arm, TWR/UAV info, actuator, and telemetry buses.
3. Reproduce the full Stateflow trajectory/robotic-arm/failsafe charts instead of the compact mission state machine.
4. Load and replay the saved `1214_replay_*.mat` and `1215_replay_*.mat` datasets for calibration against the original figures.
5. Extend the ImGui/Rerun dashboards with real-time simulator streaming if a cockpit-style runtime UI is needed.
