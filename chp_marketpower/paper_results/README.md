# CHP 策略获利、发电替代与统一结果入口

更新于 2026-11-03。本目录汇总当前论文采用的利润曲线、结算账目、竞争方案和计算证据。研究重点是 G1 如何积累实际收益，以及竞争机组的跨时段替代成本和网络可行性怎样改变获利机会。本次整理复用既有优化和计时结果。

## 阅读顺序与当前主结果

1. [统一实验分析](RESULTS_ANALYSIS.md)：按“利润来源→发电替代→成本与网络条件→连续评价能力”解释完整证据。
2. [英文论文](../manuscript/README.md)：当前稿件、图表与编译入口。
3. [统一符号](SYMBOLS.md)与[数据追溯](TRACEABILITY.md)：核对调度、申报 LOC、价格分量及原始档案。

在全天统一增量报价 $\delta\in[0,20.991]$ USD/MWh 下，IEEE30-G1 的有利边界候选增加实际利润 **7,811.56 美元**；左侧 0.001 USD/MWh 的已核验报价增加 7,810.84 美元。最终账目为能量收入增加 4,385.61、uplift 减少 578.36、真实成本节约 4,004.31 美元。路径分析则将同一收益写成自调度加权价格效应 8,741.602193、连续暴露效应 −29.225308、此前物理切换 −900.821783 美元。

G5 提前五小时运行使系统多付 1,387.35 美元，减少 105.07 MWh 的 G1 报价暴露，形成原网络约 **13.204 USD/MWh** 的 A/B 替代门槛。G5 在线成本增加 5 美元/小时后，已验证门槛移至 **13.442**。线路 30 放松则允许新方案 C 进入；在放松网络、$\delta\in[0,20.991]$、$\varepsilon\in[0,5]$ 的指定报价—成本矩形内，C 相对固定 A/B 的最低优势为 **1,635.46 美元**，使原门槛退出最优出清竞争。

## 当前论文的四张主图

> 本节描述第五版（②）的四图证据层。2026-11-26 起的修改基线是新稿 ③（`paper_v6/`），其图件为三张 JPG，见该目录 README。

图号按论文叙事排列；源文件沿用已有命名。历史 `TABLE_I.md`、`TABLE_II.md` 也保留源文件编号，现行正文按结算表、计算表顺序引用。

| 正文图号 | 论证职责 | 预览 | 矢量文件 |
|---|---|---|---|
| 1 | G1 完整报价—额外利润及 uplift 路径 | [PNG](figures/fig3_strategic_profit_uplift.png) | [PDF](figures/fig3_strategic_profit_uplift.pdf) / [SVG](figures/fig3_strategic_profit_uplift.svg) |
| 2 | G5 提前运行、替代成本与 A/B 门槛 | [PNG](figures/fig4_generation_substitution.png) | [PDF](figures/fig4_generation_substitution.pdf) / [SVG](figures/fig4_generation_substitution.svg) |
| 3 | 运行成本改变既有竞争，网络改变可行方案 | [PNG](figures/fig2_competition_conditions.png) | [PDF](figures/fig2_competition_conditions.pdf) / [SVG](figures/fig2_competition_conditions.svg) |
| 4 | IEEE30/118 独立实测查询流的计算复用 | [PNG](revision_20261020/figures/fig1_cumulative_pricing_time.png) | [PDF](revision_20261020/figures/fig1_cumulative_pricing_time.pdf) / [SVG](revision_20261020/figures/fig1_cumulative_pricing_time.svg) |

## 必要结果与来源

| 证据 | 当前入口 | 使用范围 |
|---|---|---|
| G1 全域利润与结算 | [曲线](source_data/fig3_profit_uplift_curves.csv)、[全机组结算](source_data/absolute_generator_settlements.csv)、[结算变化](source_data/table_II_settlement_changes.csv) | 固定价格选择与边界执行约定下的连续域评价；其他机组各列为面对 G1 报价的收益变化 |
| 利润路径来源 | [价格积分](source_data/price_effect_subintervals.csv)、[逐小时贡献](source_data/price_effect_by_hour.csv)、[共同区间](source_data/certified_full_range_pieces.csv) | 自调度加权路径效应与实际能量收入分别解释 |
| A/B 成本与物理替代 | [成本线](source_data/fig4_cost_competition.csv)、[出力](source_data/fig4_generation_substitution.csv)、[门槛预测](source_data/fig4_threshold_predictions.csv) | 原网络中有全局 UC 支持的两套竞争方案 |
| 运行成本×网络对照 | [2×2 完整结算](revision_20261102/source_data/factorial_settlements.csv)、[冻结预测](revision_20261102/source_data/frozen_competition_predictions.csv) | 两个固定报价；C 排除 A/B 的矩形为 $\delta\in[0,20.991]$、$\varepsilon\in[0,5]$ |
| 实测计时及单小时对照 | [四工作负载](revision_20261020/source_data/table_I_four_workloads.csv)、[时段报价对照](revision_20261020/source_data/temporal_offer_comparison.csv) | Q500 与 Q200 各自独立；定价加速不含物理 UC/结算 |
| 网络结算与切换补充 | [网络账目](revision_20261021/source_data/network_settlement_responses.csv)、[16 处切换](revision_20261021/source_data/physical_switching_costs.csv) | 每个网络各用自身真实报价基准；固定报价情景比较 |

IEEE30-G1 的 83 个价格段、17 个共同 UC 区间形成 99 个联合区间和 116 条端点/执行候选。1,000 次查询的 G1/G2 实测定价累计加速分别为 6.74 与 20.54 倍。IEEE118 的独立 Q500 流约为 2.00 倍、首次在第 224 次查询摊销；独立 Q200 流为 0.90 倍，未摊销。基础 `analysis_summary.json`、旧 `TABLE_I.md` 与旧图注是基础层结果；现行计时使用上表的四工作负载源表，完整叙事以本入口及 `RESULTS_ANALYSIS.md` 为准。

## 数据层与复现

`source_data/` 保存基础图表源数据，`supplement/missing_self_schedules/` 保存完整利润曲线所需自调度见证。`revision_20261020/`、`revision_20261021/`、`revision_20261102/` 是后续证据层，各自保留来源指纹、数值核验及源表。日期目录承担追溯作用，研究结论集中在统一分析中。

从 `chp_marketpower` 目录执行下列已有入口，可读取档案并重建相应结果层：

```powershell
python -X utf8 -m paper_results.build_results --resume
python -X utf8 -m paper_results.audit_results
python -X utf8 -m paper_results.revise_20261020
python -X utf8 -m paper_results.audit_revision_20261020
python -X utf8 -m paper_results.revise_20261021
python -X utf8 -m paper_results.competition_analysis_20261102
```

当前检查点齐备时，以上入口复用保存的求解见证；绘图依赖当前 Python/matplotlib 及本机 nature-figure 审计脚本。底层优化复现需要相同 COPT 环境与原始 `results/` 档案。基本消费关系见 [TRACEABILITY.md](TRACEABILITY.md)，各层指纹以各自 `input_manifest.json` 为准。[当前证据清单](evidence_manifest.json)以仓库相对路径保留338项输入和成功见证，本轮补入旧公开版本缺失的161项。旧绝对路径清单保留历史身份；迁移机器时按相对清单定位文件。仓库派生表和图件可直接阅读。

## 当前进度与证据边界

连续利润评价、G1–G5替代分析、成本扰动和网络对照已完成，第五版论文、统一报告和必要证据同步整理。本轮没有开展新的报价扫描、机组利润排名或优化计时。G1的边界最大值依赖执行约定；成本与网络变化后的利润表是指定报价比较。统一连续域的另一机组利润—替代案例可作为后续扩展，由明确的跨机组研究问题触发。
