# 原研究档案到统一结果的追溯

以下路径以`chp_marketpower/`为根。开发阶段目录名只用于复现定位；结果叙事采用经济问题与统一符号。逐文件SHA-256见`input_manifest.json`，逐行映射见`TRACEABILITY.csv`。

|结果对象|原始依据|统一数据及用途|
|---|---|---|
|调度、节点价格、网络结算定义|用户确认的`CHP_dual/chp_primal/chp_5th.tex`|`SYMBOLS.md`；只核实定义，不合并旧算例数值|
|实际累计查询时间|`results/finalization_20261017/figures/`及其引用的原查询流|`fig1_measured_query_prefixes.csv`、`table_I_computation.csv`；Fig. 1、Table I|
|完整报价价格及网络对偶|`results/scope_study_20261016/30_bracket_repeat1/`|`price_components.npz`、`nodal_price_components.csv`、`price_boundary_continuity.csv`；Fig. 2|
|物理共同区域与有限候选|`results/targeted_study_20261016/30_G1_profit_0to50/`；G2的`results/dashboard_uc_regions/30-G2-all/`|Table I、`certified_full_range_pieces.csv`；Fig. 3|
|利润价格效应路径|`results/mechanism_20261019/P1_profit_path_io_recovery/`|`price_effect_subintervals.csv`、`price_effect_by_hour.csv`；Fig. 2及利润路径对账|
|六机组结算与当前网络恒等式|`results/figure_study_20261016/economic_source_audit.json`、`generator_settlements.csv`及其匹配当前模型的归档|`absolute_generator_settlements.csv`、`table_II_settlement_changes.csv`、`network_settlement_identity.csv`；Table II|
|全域曲线缺失的自调度见证|直接复用原路径38个响应；本轮补64个单机响应|`supplement/missing_self_schedules/`、`fig3_profit_uplift_curves.csv`；Fig. 3|
|发电替代与成本竞争|`results/mechanism_20261019/`下的门槛预测、原A/B见证及成本扰动|`fig4_generation_substitution.csv`、`fig4_cost_competition.csv`、`fig4_threshold_predictions.csv`；Fig. 4|
|线路30原网络/放松网络|`results/mechanism_20261018/followup/E4_causal_recovery_02/`；`results/mechanism_20261019/network_lower_envelope.json`|`network_counterfactual_settlements.csv`、`network_counterfactual_hourly_prices.csv`、`network_pricing_duals_vs_physical_flows.csv`；网络机制分析|
|定价线路与参考敏感性|原完整Oracle的平衡、正/反向容量行对偶及PTDF|`active_line_congestion_prices_at_G5.csv`、`line_effect_on_G1_G5_spread.csv`及`analysis_summary.json`；辅助解释，价差诊断不当成G1拥塞收益|

所有源表在`source_data/`。未进入四张主图的局部导数、MRG、对偶面检查和旧失败日志保留在原研究档案，未删除或更改。新构建最初检查发现旧图件清单中一个未被本轮消费的单小时验证文件曾发生变化；失败日志与处理说明见`QA_NOTES.md`，没有跳过本轮实际消费输入的指纹核验。
