# GNSS Spoof Detection Paper Platform

本文档记录论文平台的阶段划分、复现实验入口和每一步的验收方式。当前目标是把仿真、RTKLIB、FAST_GLIO、Rerun/ImGui 可视化和论文评测统一到一个可提交、可复查的工程里。

## Phase 1: 数据闭环和基线评测

已实现内容：

- RTKLIB `.pos` 到 ENU 轨迹、仿真 scenario、Rerun replay CSV 的适配。
- FAST_GLIO `gnss_loose_diag.csv`、`gnss_raw_update_log.csv`、`gnss_tight_pose.csv` 与 RTKLIB/DOP 的同时间轴合并。
- RINEX `rover.obs` 原始观测特征提取：每颗卫星每历元的 code/carrier/Doppler/C/N0、LLI、SSI、码间差、code-Doppler consistency。
- RINEX 每历元汇总特征合入检测数据集：卫星数、系统数、观测数、C/N0 统计、低 C/N0 卫星数、码间差 RMS、周跳计数。
- GPS 广播星历原始伪距残差：解析 RINEX navigation，计算 GPS 卫星 ECEF、卫星钟差、仰角/方位角、GNSS-only WLS 后验 RAIM 残差，以及 RTK 参考位置伪距残差。
- 观测级攻击注入：直接改写 per-satellite CSV 中的 `primary_code_m`，保留 `clean_primary_code_m`、`injected_pseudorange_bias_m`、攻击标签和 scale。
- 环境自适应序贯 GLRT：融合 raw GNSS residual、receiver pseudorange GLRT、LiDAR--GNSS residual、DOP/C/N0/RTK ratio/satellite count 环境质量，输出 adaptive threshold、CUSUM、confidence 和攻击类型。
- 实验矩阵：clean real data、degraded non-attack data、80 个 synthetic spoofing case，覆盖 1/2/5/10 m 强度、1/5/20/60 s ramp、position bias/pseudorange delay/single-satellite outlier/coordinated spoof/slow drift 五类攻击。
- Baseline/ablation：RAIM-only、pseudorange GLRT-only、LIO-GNSS-only、fixed fused、adaptive fused、EA-SGLRT、no raw、no LIO、no environment、no CUSUM。
- GPS week/TOW 到 Unix 时间的转换，默认 GPST-UTC = 18 s。
- 合成欺骗窗口注入：位置残差偏移、伪距延迟、ramp-in/ramp-out。
- 基线检测分数：LiDAR/IMU-GNSS 残差、Mahalanobis gate、伪距 RMS/最大残差、Doppler/TDCP、RTK 质量。
- 评测报告：TP/FP/TN/FN、precision、recall、specificity、F1、ROC AUC、误报率、检测延迟。
- CTest 烟雾测试，使用自造小数据验证干净样本无误报、合成攻击可检出。

一键验证：

```bash
cd /Users/wangzhibo/Desktop/博士研究/simulink2/cpp_flight_sim
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

RINEX 原始观测特征：

```bash
python tools/extract_rinex_features.py \
  --obs ../full_data/gnss/rover.obs \
  --name full_data_rover \
  --output-dir build/paper_platform/rinex_rover
```

输出文件：

```text
build/paper_platform/rinex_rover/full_data_rover_satellite_features.csv
build/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv
build/paper_platform/rinex_rover/full_data_rover_rinex_summary.json
```

生成真实数据检测集：

```bash
python tools/build_detection_dataset.py \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --dop ../full_data/gnss/dop.txt \
  --loose /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_loose_diag.csv \
  --raw /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_raw_update_log.csv \
  --tight /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_tight_pose.csv \
  --rinex-summary build/paper_platform/rinex_rover/full_data_rover_epoch_summary.csv \
  --name full_data_clean \
  --output-dir build/paper_platform/full_data_clean
```

生成带合成欺骗的检测集并评测：

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
  build/paper_platform/full_data_attack/full_data_attack_detection.csv \
  --output-json build/paper_platform/full_data_attack/full_data_attack_metrics.json \
  --output-md build/paper_platform/full_data_attack/full_data_attack_metrics.md
```

CMake 快捷入口：

```bash
cmake --build build --target rinex_features
cmake --build build --target raw_gnss_residuals
cmake --build build --target raw_observation_attack
cmake --build build --target raw_gnss_residuals_attack
cmake --build build --target paper_dataset
cmake --build build --target paper_dataset_attack
cmake --build build --target paper_eval_attack
cmake --build build --target paper_eval_clean
cmake --build build --target paper_pipeline
cmake --build build --target adaptive_experiments
cmake --build build --target paper_figures
cmake --build build --target paper_pdf
```

LaTeX 论文源文件在 `paper/main.tex`，实验图在 `paper/figures/`，编译结果在 `paper/build/main.pdf`。

## Phase 2: 原始 GNSS 观测层

当前已完成 GPS-only 第一版原始残差链路。它把 RINEX 原始观测进一步变成检测算法里的统计量：

- 每颗卫星的 pseudorange、carrier phase、C/N0 已抽取；base.obs 中的 Doppler 也可抽取，rover.obs 当前无 Doppler 字段。
- `tools/compute_raw_gnss_residuals.py` 已实现 GPS 广播星历解析、卫星位置/钟差、仰角/方位角、C/N0/仰角加权、GNSS-only WLS、RAIM chi-square、RTK 参考伪距残差。
- `tools/inject_observation_attack.py` 已实现观测级 pseudorange bias 注入，输出攻击后的 per-satellite CSV，可以直接送入 raw residual 引擎。
- 当前 full_data 默认工况使用 G02 单星 outlier + common delay 作为 RAIM stress baseline；coordinated all-satellite spoofing 可能被 WLS 位置/钟差吸收，这是 RAIM-only 的预期局限，不应作为最终方法。

验收标准：

- 已输出 per-satellite long-format CSV。
- 已输出 per-epoch summary CSV，并合入检测数据集。
- 已输出 raw GPS per-satellite residual CSV 和 per-epoch RAIM/reference residual CSV。
- 已通过 `raw_residuals_smoke` 自包含测试：clean RAIM 分数低，观测级单星攻击后 RAIM 分数升高。
- 已通过 `adaptive_detector_smoke` 自包含测试：持续攻击可检出，环境自适应相对无环境版本降低误报。
- 待完成：多星座 Galileo/BDS 广播星历、ionosphere/troposphere correction、Doppler/TDCP、单差/双差、robust weighting 与 `gnss_raw_update_log.csv` 的 PR RMS/healthy count/outlier count 定量趋势匹配。

## Phase 3: 可发表检测算法

当前主线已经实现第一版：

- Raw GNSS consistency: RAIM/reference pseudorange residual。
- Cross-modal consistency: LiDAR/IMU odometry vs GNSS。
- Environment-aware gating: 使用 C/N0、DOP、RTK ratio、satellite count、raw coverage、alignment quality 自适应调阈值。
- Sequential decision: CUSUM/GLRT confirmation，输出 confidence、检测时延、误报率和 attack type。

验收标准：

- 当前矩阵中 EA-SGLRT 在 82 场景上取得 mean attack F1 高于 fixed fused，同时 mean false alarms/min 更低。
- 已包含固定阈值、RAIM-only、pseudorange GLRT-only、LIO-GNSS-only、adaptive fused、EA-SGLRT 和四个消融。
- 下一步要把 degraded non-attack 从合成降质扩展为真实 urban/open-sky 分段，并补充统计显著性检验。

## Phase 4: 论文实验矩阵

需要完成的实验：

- 不同攻击幅值：1 m、2 m、5 m、10 m、渐进 ramp。
- 不同 ramp：1 s、5 s、20 s、60 s。
- 不同攻击类型：位置偏移、伪距公共延迟、单星 outlier、协同欺骗、慢漂移。
- 不同环境/质量：clean real、degraded non-attack；待补真实 open sky、遮挡、urban canyon 分段。
- 消融：去掉 raw GNSS、去掉 LIO consistency、去掉 adaptive gate、去掉 CUSUM。
- 鲁棒性：采样率、时间同步误差、GNSS 中断、RTK fixed/float 状态切换。

## Phase 5: 论文初稿和投稿材料

最终要输出：

- 英文论文初稿。
- 图表：平台架构、时间同步、攻击模型、检测状态机、ROC/PR 曲线、时延箱线图、轨迹可视化。
- 可复现实验命令和结果表。
- 数据说明和伦理/安全说明。
