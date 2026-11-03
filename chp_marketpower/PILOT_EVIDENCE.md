# 研究证据索引：当前结论、验证层与早期试点

更新于 2026-11-03。本文件维护不同结果的证据范围及原始入口。当前研究问题和进度见[RESEARCH_PLAN.md](RESEARCH_PLAN.md)，完整经济解释见[统一实验报告](paper_results/RESULTS_ANALYSIS.md)。早期价格脆弱性试点与当前连续域利润研究分别保留各自口径。

## 1. 当前论文采用的证据

| 证据对象 | 可支持的结论 | 主要来源 |
|---|---|---|
| IEEE30-G1，全天统一增量报价 $[0,20.991]$ USD/MWh | 有利边界候选增加利润 7,811.56 美元；临界左侧 0.001 的报价增加 7,810.84 美元 | `paper_results/source_data/fig3_profit_uplift_curves.csv`、`absolute_generator_settlements.csv`；底层 `results/targeted_study_20261016/30_G1_profit_0to50/` |
| 最终结算账目 | 增量收入 4,385.61、uplift −578.36、成本节约 4,004.31 美元 | `paper_results/source_data/table_II_settlement_changes.csv` |
| 利润路径 | 自调度加权价格效应 8,741.602193、连续报价暴露效应 −29.225308、此前物理切换 −900.821783 美元 | `paper_results/analysis_summary.json`、`source_data/price_effect_subintervals.csv`；底层 `results/mechanism_20261019/P1_profit_path_io_recovery/` |
| A/B 发电替代 | 提前启用 G5 多花 1,387.346991 美元、减少 G1 报价暴露 105.069565 MWh，原网络门槛约 13.204080444 USD/MWh | `paper_results/source_data/fig4_generation_substitution.csv`、`fig4_cost_competition.csv`、`fig4_threshold_predictions.csv` |
| G5 在线成本处理 | 增加 5 美元/在线小时后，原网络门槛约 13.442018042 USD/MWh，已有全局 UC 支持 | `paper_results/source_data/fig4_threshold_predictions.csv`；底层 `results/mechanism_20261019/` |
| 线路 30 放松与固定方案 C | C 在原网络不可行，在放松网络指定矩形内比 A/B 至少便宜 1,635.464038 美元，排除 A/B 最优性 | `paper_results/revision_20261102/source_data/frozen_competition_predictions.csv`、`threshold_eligibility.csv` |
| 两个固定报价的 2×2 结算 | 成本与网络改变后的收益由各条件自身真实报价基准评价 | `paper_results/revision_20261102/source_data/factorial_settlements.csv`；底层 `results/competition_regimes_20261102/` |
| 计算表现 | 30-G1/G2 的 Q1000、118-G11 的独立 Q500/Q200 实测流 | `paper_results/revision_20261020/source_data/table_I_four_workloads.csv` |
| 同一 G1 的时段报价对照 | 同域仅小时 1 加价的连续候选最高增益为 0，全天加价具有正收益 | `paper_results/revision_20261020/source_data/temporal_offer_comparison.csv`、`hour1_common_UC_certificates.csv`、`hour1_profit_candidates_verified.csv` |

原始优化记录和完整自调度见证决定重建能力，派生表、图件及输入指纹决定论文数据的可核查性。当前结果消费关系见 [TRACEABILITY.md](paper_results/TRACEABILITY.md)；每层实际使用的文件和 SHA-256 由相应 `input_manifest.json` 保存。

## 2. 这些结果怎样经过核验？

基础结果层的[核验文件](paper_results/verification.json)记录 76 个消费来源指纹，102 个自调度见证、99 个共同区间和 116 条利润候选的对账。曲线账目最大误差约 $1.69\times10^{-8}$ 美元，候选利润误差约 $6.14\times10^{-9}$ 美元，利润路径残差约 $-5.56\times10^{-9}$ 美元。完整价格分量的重构最大误差约 $1.42\times10^{-14}$ USD/MWh。基础曲线整合时补过 64 次单机自调度，沿用其余 38 个响应。

独立 [20261020 核验](paper_results/revision_20261020/verification.json)加入 IEEE118 Q500 与 Q200 的分开计时、同域单小时候选和共同 UC 证书；[20261021 核验](paper_results/revision_20261021/verification.json)检查 1,440 组节点—时段情景响应与 16 处物理切换，申报成本交点最大误差约 $3.64\times10^{-11}$ 美元。这两层均复用档案，没有新增优化或计时。

[20261102 核验](paper_results/revision_20261102/verification.json)保存 12 条结算情形、两个事前固定报价及冻结竞争预测。该阶段实际完成 5 次 UC、6 次 CHP、6 次单机自调度，共 17 次优化；数值分析脚本读取结果时新增优化为 0。保存的物理或定价可行性/KKT 残差最大约 $6.55\times10^{-11}$，新账目重构残差为 0。本次文档重构继续使用这些记录。

## 3. 解释时采用的统一口径

- $p^{UC}$ 是实际执行，$p^{CH}$ 是定价凸化调度，$p^{SS}$ 是按申报成本的最佳自调度。结算收入使用 $p^{UC}$，路径价格效应使用 $p^{SS}$。
- 报价暴露为高于最小出力的电量 $Q=\sum_t(p_t-P^{\min}u_t)$。相对成本乘数与绝对边际加数有不同方向和单位。
- G1 的边界候选使用有利的最优物理方案；单侧可逼近上确界和临界左侧实测报价为其经济解释提供支持。改变网络或成本后的表格评价两个固定报价。
- C 的 1,635.46 美元优势限定为放松网络、$\delta\in[0,20.991]$、$\varepsilon\in[0,5]$ 相对固定 A/B 的成本差下界。指定点的全局最优执行有 UC 支持。
- 原 PTDF 参考为 bus 1，G1 同在 bus 1，因而其显式拥塞分量为 0；这是分量记账约定。线路放松对竞争可行域和结算的影响由独立情景直接评价。
- 现行性能表包含建图、后处理、加载和在线查询；Q500/Q200 是独立查询流，计时范围为 CHP 定价。基础 `analysis_summary.json` 的 Q200 记录属于较早结果层。

## 4. 早期试点的保留用途

早期 6 节点 `case6ww`、24 小时、三段成本试点验证了局部报价响应、网络配对和利润记账。该案例来自 Wood–Wollenberg 三机组数据，与 Sun–Wu 的六机组模型不同；文献可比性见 [REFERENCE_2021_AUDIT.md](REFERENCE_2021_AUDIT.md)。早期 30 节点试点进一步检查 hourly Jacobian、相对/绝对扰动尺度及有限报价网格。当前论文对这些材料采用模型诊断和研究背景用途。

| 保留的历史证据 | 原始入口 | 使用范围 |
|---|---|---|
| COPT 迁移与同配置目标、价格、结算比较 | `results/copt_validation_C3/`、`../chp_energy/results/copt_validation_30_ptdf_tight.csv` | 同配置数值一致性；LP 基和退化弧权重可因算法而异 |
| 6 节点共同价值区间与原始对偶价格检查 | `results/value_oracle_G2_absolute_nominal/`、`results/price_probe_G2_absolute/`、`results/basis_dual_G2_absolute.json` | 早期一维方法原型、退化诊断和报价暴露接口核验 |
| 30 节点 hourly 相对与绝对报价响应 | `results/full_case30_C3_relative_twostep_copt/`、`results/full_case30_C3_absolute_twostep_copt/` | 局部价格影响及跨步长筛查；相对与绝对导数单位分别保留 |
| 有限相对报价网格利润 | `results/profit_case30_C3_all_dispatched_copt.csv` | 已测网格的观察增益；与当前 G1 绝对加数连续域分开使用 |
| 空间负荷转移与 warm-up 初态 | `results/p1_shift23to21_r020/`、`results/p1_warmup/` | 相同预指定报价列和网格的情景检查；各情景有自己的初态或负荷口径 |

早期相对网格曾观察到 G1/G3/G5 的收益差异，局部价格影响较大的 G5 也有较小的已测利润增益。这个现象可以提出跨机组研究问题；若要比较连续域的最大可获利市场力，需要统一报价方向、范围、价格选择与完整执行/结算。当前没有形成全机组连续利润排名。

迁移核验的关键历史量仍可追踪：30 节点物理 UC 目标差约 $5.82\times10^{-11}$ 美元、CHP 定价目标差约 $2.13\times10^{-6}$ 美元，uplift/FTR/总缺口字段最大差约 $3.24\times10^{-5}$ 美元。它们支持所比较实现的数值一致性；当前经济结果仍由匹配自身模型的来源和对账支撑。历史单次坐标实现计时与局部价值原型时间不进入现行性能主表。

## 5. 当前可直接使用的复现入口

当前结果核验与报告重建命令见 [paper_results/README.md](paper_results/README.md#数据层与复现)。各修订层 README 记录对应源表、输入指纹及恢复约定。底层代码的职责见 [RESEARCH_PLAN.md §5](RESEARCH_PLAN.md#5-研究链条与代码库的明确对应)。本文件保留证据用途和来源，实验执行条件由各自脚本与协议维护。
