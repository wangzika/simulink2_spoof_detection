# GNSS Spoofing and Interference Detection Literature Notes

本文档按检测层级整理 GNSS 欺骗/干扰检测文献，用于扩展论文 Related Work 和后续实验设计。重点不是逐篇罗列，而是提炼“他们检测什么、依赖什么输入、局限在哪里、本文可以如何对标”。

## 1. 威胁模型和早期欺骗验证

- Humphreys et al., ION GNSS 2008, “Assessing the Spoofing Threat: Development of a Portable GPS Civilian Spoofer”
  - 做法：构建便携式民用 GPS spoofer，证明低成本欺骗设备可以逐步牵引普通接收机。
  - 价值：这是后续 GNSS spoofing detection 论文常引用的威胁模型起点。
  - 对本文启发：实验中的 ramp attack、coordinated spoofing 和 slow drift 都应强调来自这种“逐渐牵引”的实际攻击模式。

- Jafarnia-Jahromi et al., IJNO 2012, “GPS Vulnerability to Spoofing Threats and a Review of Antispoofing Techniques”
  - 做法：系统梳理 GPS spoofing 威胁和抗欺骗技术。
  - 对本文启发：Related Work 开头可用它支撑“spoofing threat 已系统化研究，但不同层级方法输入要求不同”。

- Psiaki and Humphreys, Proceedings of the IEEE 2016, “GNSS Spoofing and Detection”
  - 做法：综述 spoofing 机制、攻击模型和检测技术。
  - 对本文启发：可以作为顶层综述引用，说明本文属于 receiver-output / measurement-navigation layer。

## 2. 信号级 / 接收机内部检测

- Akos, NAVIGATION 2012, “Who’s Afraid of the Spoofer? GPS/GNSS Spoofing Detection via Automatic Gain Control”
  - 做法：利用 AGC/前端功率异常检测 overpowering spoofing。
  - 优点：简单、实时、计算量低。
  - 局限：需要接收机前端/AGC 输出；对低功率、匹配真实信号功率的欺骗不一定稳健。

- Wesson et al., IEEE TAES 2018, “GNSS Signal Authentication via Power and Distortion Monitoring”
  - 做法：利用信号功率和相关峰形变进行 spoofing authentication。
  - 对本文启发：说明 signal-quality 层检测强，但需要更底层接收机信息。

- Gross et al., IEEE TAES 2019, “Signal Authentication by Power and Distortion Monitoring with Generalized Likelihood Ratio Testing”
  - 做法：把 power/distortion monitoring 写成 GLRT 检测问题。
  - 对本文启发：可作为本文 sequential GLRT 命名和统计检测思想的信号层参照。

- Seco-Granados et al., GPS Solutions 2021, “Detection of Replay Attacks to GNSS Based on Partial Correlations and Authentication Data Unpredictability”
  - 做法：利用认证数据不可预测性和 partial correlation 检测 replay/spoofing。
  - 优点：对带认证信号的系统更有安全意义。
  - 局限：依赖信号认证机制或相关器级访问，不能直接用于普通 RINEX/RTK/LiDAR 后处理链路。

- Ardizzon et al., arXiv 2023, “Satellite Cross-Authentication Against GNSS Spoofing Attacks”
  - 做法：利用卫星间交叉认证思想抵抗 spoofing。
  - 对本文启发：认证类方法适合未来与本文 residual/fusion detector 互补。

- Sathaye et al., NDSS 2021, “SemperFi: A Spoofer Eliminating GPS Receiver for UAVs”
  - 做法：设计能够消除 spoofing 影响的 UAV GPS 接收机架构。
  - 优点：从接收机信号处理层主动抑制 spoofing。
  - 局限：工程侵入性强，需要专门接收机实现。

## 3. 空间多天线 / 多接收机检测

- Psiaki et al., GPS Solutions 2014, “GNSS Spoofing Detection Using Two-Antenna Differential Carrier Phase”
  - 做法：双天线载波相位差约束信号到达方向；spoofing 信号通常来自同一发射源，破坏真实卫星空间几何。
  - 优点：对同源 spoofing 很强。
  - 局限：需要天线基线和载波相位稳定性。

- Chen and Wang, arXiv 2024, “GNSS Spoofing Detection by Crowdsourcing Double Differential Pseudorange Spatial Distribution”
  - 做法：多用户 crowdsourcing，利用 double-differenced pseudorange 的空间分布异常检测 spoofing。
  - 优点：适合区域性/协同检测。
  - 局限：依赖多接收机协作和通信网络。

- Park et al., arXiv 2026, “Wide-Area GNSS Spoofing and Jamming Detection Using AIS-Derived Spatiotemporal Integrity Monitoring”
  - 做法：用 AIS 船舶轨迹的时空一致性检测大范围 GNSS spoofing/jamming。
  - 优点：能覆盖海事场景和区域性事件。
  - 局限：依赖 AIS 基础设施，不适用于单平台自主检测。

## 4. 观测级 / RAIM / GLRT 检测

- Parkinson and Axelrad, NAVIGATION 1988, “Autonomous GPS Integrity Monitoring Using the Pseudorange Residual”
  - 做法：经典 pseudorange residual RAIM。
  - 对本文启发：本文 raw RAIM baseline 可以用它说明 residual-based integrity 的根基。

- Brown, NAVIGATION 1992, “A Baseline GPS RAIM Scheme and a Note on the Equivalence of Three RAIM Methods”
  - 做法：总结 baseline RAIM scheme 及不同 RAIM 方法等价性。
  - 对本文启发：适合作为 RAIM-only baseline 的理论背景。

- 经典 RAIM/GLRT 类方法总结
  - 做法：用伪距残差、WLS 后验残差、卡方统计量或导航滤波创新检测异常。
  - 优点：透明、可解释、能直接基于 RINEX/receiver output 工作。
  - 局限：固定阈值容易把低 C/N0、差 DOP、遮挡、多路径、RTK float 状态误判为攻击。

- Liu and Papadimitratos, arXiv 2024, “Extending RAIM with a Gaussian Mixture of Opportunistic Information”
  - 做法：用 opportunistic information 的高斯混合扩展 RAIM，提高定位完整性和异常检测能力。
  - 对本文启发：说明 RAIM 需要引入上下文信息；本文用 C/N0、DOP、RTK ratio、satellite count、LIO quality 做环境自适应。

- Zheng et al., arXiv 2023, “Hybrid ARAIM and Signal Quality Monitoring for GNSS Spoofing Detection”
  - 做法：把 ARAIM 和 signal quality monitoring 结合。
  - 对本文启发：支持“只用 RAIM 不够，需要环境/质量信息”的方法论。

- Suzuki, arXiv 2024, “Multipath and NLOS Detection in Urban Environments Using GNSS Signal Correlation Output”
  - 做法：面向城市环境 NLOS/multipath 检测。
  - 对本文启发：说明 degraded non-attack 不只是合成噪声，而是城市 GNSS 真实痛点。

- Kriezis et al., arXiv 2025, “GNSS Jamming and Spoofing Monitoring Using Low-Cost COTS Receivers”
  - 做法：低成本商用接收机监测 jamming/spoofing 特征。
  - 对本文启发：投稿时可以强调本文也走 commodity-output / observation-level 的可复现路线，而不是依赖专用 RF 前端。

## 5. 多传感器融合 / INS / LiDAR-IMU 一致性

- Clements et al., ION ITM 2022, “Carrier-Phase and IMU Based GNSS Spoofing Detection for Ground Vehicles”
  - 做法：融合 IMU 和 carrier phase，利用运动一致性检测地面车辆 spoofing。
  - 对本文启发：GNSS 和自包含传感器的一致性是强线索；本文进一步加入 LiDAR-inertial consistency 和 raw pseudorange residual。

- Johansson et al., arXiv 2025, “Consumer INS Coupled with Carrier Phase Measurements for GNSS Spoofing Detection”
  - 做法：用消费级 INS 和载波相位增强低成本 spoofing detection。
  - 局限：仍侧重 INS/carrier phase，未覆盖 LiDAR-inertial 退化质量和 raw observation 残差联合建模。

- Dasgupta et al., IEEE T-ITS 2022, “A Sensor Fusion-Based GNSS Spoofing Attack Detection Framework for Autonomous Vehicles”
  - 做法：面向自动驾驶，把 GNSS 和车载传感器融合用于攻击检测。
  - 对本文启发：要把本文定位为“raw GNSS + LiDAR-inertial”的可解释融合检测，而不是黑盒融合分类器。

- Dasgupta et al., arXiv 2024, “Experimental Evaluation of GNSS Spoofing Attack Detection Frameworks for Autonomous Vehicles”
  - 做法：实验评价自动驾驶 GNSS spoofing 检测框架。
  - 对本文启发：后续需要更多真实/回放数据做外部验证。

- Dasgupta et al., arXiv 2024, “Slow-Drift GNSS Spoofing Attack Detection for Autonomous Vehicles”
  - 做法：聚焦 slow-drift attack。
  - 对本文启发：本文实验矩阵里的 slow drift/ramp attack 应作为重要攻击类型，而不是附属场景。

- Dai et al., arXiv 2023, “Spoofing-Resilient LiDAR-GPS Factor Graph Localization with Chimera Authentication”
  - 做法：结合 LiDAR-GPS factor graph 和 Chimera authentication。
  - 对本文启发：直接支撑“LiDAR consistency + GNSS authentication/residual 可以互补”的研究方向。

## 6. 航海 / NMEA / 应用层完整性

- Spravil et al., JMSE 2023, “Detecting Maritime GPS Spoofing Attacks Based on NMEA Sentence Integrity Monitoring”
  - 做法：检查 NMEA sentence 的一致性和完整性，用于海事 GPS spoofing 检测。
  - 优点：输入层级高，易部署。
  - 局限：依赖应用层消息，不能解释原始观测和传感器一致性来源。

- Androjna et al., JMSE 2020, “Assessing Cyber Challenges of Maritime Navigation”
  - 做法：综述海事导航网络安全挑战。
  - 对本文启发：说明 GNSS spoofing 不只是机器人问题，也涉及海事和关键基础设施。

- Leite et al., Sensors 2021, “GNSSSD: A Dataset for GNSS Spoofing Detection in Autonomous Vehicles”
  - 做法：构建自动驾驶 GNSS spoofing detection 数据集。
  - 对本文启发：投稿前需要强调当前数据集限制，并规划 external dataset validation。

- Risbud et al., arXiv 2018, “Aviation GPS Spoofing Detection Based on COTS Aviation Receivers for Smart Grid Timing Security”
  - 做法：利用 COTS aviation receiver 检测 spoofing，用于智能电网 timing security。
  - 对本文启发：低成本接收机输出也能服务关键基础设施监测，但需要明确应用约束。

## 7. 本项目已下载的开放论文

下载脚本：

```bash
python3 tools/download_reference_papers.py
```

清单：

```text
paper/literature/reference_papers.csv
paper/literature/reference_papers_downloaded.json
paper/literature/papers/
```

当前脚本已下载 19 篇 PDF。`spravil2023nmea`、`jafarnia2012review`、`androjna2020maritime`、`leite2021gnsssd` 是开放论文，但出版站点对脚本请求返回 403，需要浏览器手动下载。

## 8. 本文 Related Work 应强调的 gap

1. 信号级方法强，但往往依赖 AGC、相关器、认证信号或特殊接收机。
2. 多天线/多接收机方法强，但依赖硬件基线、协作网络或外部基础设施。
3. RAIM/GLRT 可解释、可复现，但固定阈值在城市退化中 precision 低。
4. INS/多传感器方法有效，但很多工作没有显式建模 C/N0、DOP、RTK ratio、satellite count、raw coverage、LIO quality 等环境质量。
5. 本文的定位：在单平台、后处理友好、RINEX/RTK/FAST_GLIO 可复现输入上，融合 raw pseudorange residual 与 LiDAR-inertial consistency，并通过环境自适应阈值 + sequential GLRT/CUSUM 降低 degraded non-attack 误报。

## 9. 后续还应该继续补的文献方向

- GNSS jamming detection：C/N0 drop、AGC、noise floor、spectrogram、multi-frequency interference classification。
- Signal quality monitoring：correlator distortion、early-minus-late、multi-correlator metrics。
- Urban multipath 与 spoofing 区分：3D map、NLOS detection、factor graph / robust estimation。
- 真实数据集：TEXBAT、JammerTest、STRIKE3、Galileo OSNMA public datasets、maritime spoofing reports。
- 统计评测：route-held-out、dataset-held-out、attack-strength/ramp held-out、confidence calibration。
