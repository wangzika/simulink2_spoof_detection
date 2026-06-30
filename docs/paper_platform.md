# GNSS Spoof Detection Paper Platform

本文档记录论文平台的阶段划分、复现实验入口和每一步的验收方式。当前目标是把仿真、RTKLIB、FAST_GLIO、Rerun/ImGui 可视化和论文评测统一到一个可提交、可复查的工程里。

## Phase 1: 数据闭环和基线评测

已实现内容：

- RTKLIB `.pos` 到 ENU 轨迹、仿真 scenario、Rerun replay CSV 的适配。
- FAST_GLIO `gnss_loose_diag.csv`、`gnss_raw_update_log.csv`、`gnss_tight_pose.csv` 与 RTKLIB/DOP 的同时间轴合并。
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

生成真实数据检测集：

```bash
python tools/build_detection_dataset.py \
  --rtklib-pos ../full_data/gnss/rtklib.pos \
  --dop ../full_data/gnss/dop.txt \
  --loose /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_loose_diag.csv \
  --raw /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_raw_update_log.csv \
  --tight /Users/wangzhibo/Desktop/FAST_GLIO/FAST_LIO/Log/gnss_tight_pose.csv \
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
cmake --build build --target paper_dataset
cmake --build build --target paper_dataset_attack
cmake --build build --target paper_eval_clean
cmake --build build --target paper_eval_attack
cmake --build build --target paper_pipeline
```

## Phase 2: 原始 GNSS 观测层

下一阶段要把 RINEX/RTKLIB 原始观测进一步结构化，形成可发表的原始观测特征：

- 每颗卫星的 pseudorange、Doppler、carrier phase、C/N0、elevation/azimuth。
- 单差/双差、TDCP、RAIM 残差和 robust weighting。
- 卫星系统拆分：GPS、Galileo、BDS。
- 原始观测级 spoof injection，而不仅是融合残差级注入。

验收标准：

- 输出 per-satellite long-format CSV。
- 能按时间恢复每历元的残差统计。
- 与 `gnss_raw_update_log.csv` 的 PR RMS、healthy count、outlier count 在趋势上匹配。

## Phase 3: 可发表检测算法

建议主线：

- Raw GNSS consistency: RAIM/pseudorange/Doppler/TDCP。
- Cross-modal consistency: LiDAR/IMU odometry vs GNSS。
- Environment-aware gating: 使用 LIO quality、urban canyon score、DOP、satellite count 自适应调阈值。
- Sequential decision: CUSUM/GLRT/finite-state confirmation，输出检测时延和误报率。

验收标准：

- 干净数据低误报。
- 合成攻击高召回、低时延。
- 至少包含固定阈值、RAIM-only、LIO-GNSS-only、融合算法四个 baseline/ablation。

## Phase 4: 论文实验矩阵

需要完成的实验：

- 不同攻击幅值：1 m、2 m、5 m、10 m、渐进 ramp。
- 不同攻击类型：位置偏移、伪距公共延迟、卫星子集偏置、慢漂移。
- 不同环境/质量：open sky、遮挡、urban canyon 或人为降质片段。
- 消融：去掉 Doppler、去掉 LIO consistency、去掉 adaptive gate。
- 鲁棒性：采样率、时间同步误差、GNSS 中断、RTK fixed/float 状态切换。

## Phase 5: 论文初稿和投稿材料

最终要输出：

- 英文论文初稿。
- 图表：平台架构、时间同步、攻击模型、检测状态机、ROC/PR 曲线、时延箱线图、轨迹可视化。
- 可复现实验命令和结果表。
- 数据说明和伦理/安全说明。
