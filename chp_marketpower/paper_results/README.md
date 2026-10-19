# CHP市场力：统一结果、价格分解与经济分析

2026-10-19。本目录完成现有研究成果的结果整理与分析，不是完整论文初稿。保留当前研究分支及原始实验档案。以工作区`../../../chp_5th.tex`对应的用户确认版本核实模型定义，精确路径与哈希见`input_manifest.json`；旧稿数值未混入当前基准。

## 阅读入口

- [结果分析](RESULTS_ANALYSIS.md)：四个结果小节的研究问题、图表依据、现象、机制及贡献边界。
- [统一符号](SYMBOLS.md)：三个调度对象、能量/拥塞价格、收入、uplift payment、真实成本和利润。
- [图表说明](FIGURE_CAPTIONS.md)、[Table I](TABLE_I.md)、[Table II](TABLE_II.md)。
- [数据充分性与最小新增计算](DATA_AUDIT.md)、[结果追溯](TRACEABILITY.md)、[验证记录](QA_NOTES.md)。

## 四张主图

|图|内容|预览|可编辑矢量|
|---|---|---|---|
|1|三组实际累计查询时间|[PNG](figures/fig1_cumulative_pricing_time.png)|[PDF](figures/fig1_cumulative_pricing_time.pdf) / [SVG](figures/fig1_cumulative_pricing_time.svg)|
|2|节点价格、能量/拥塞分解和逐小时利润价格效应|[PNG](figures/fig2_energy_congestion_prices.png)|[PDF](figures/fig2_energy_congestion_prices.pdf) / [SVG](figures/fig2_energy_congestion_prices.svg)|
|3|全报价域额外利润与uplift|[PNG](figures/fig3_strategic_profit_uplift.png)|[PDF](figures/fig3_strategic_profit_uplift.pdf) / [SVG](figures/fig3_strategic_profit_uplift.svg)|
|4|G1–G5发电替代、成本竞争与临界报价预测|[PNG](figures/fig4_substitution_threshold.png)|[PDF](figures/fig4_substitution_threshold.pdf) / [SVG](figures/fig4_substitution_threshold.svg)|

重要结果：原PTDF参考节点与G1同为bus 1，所以G1价格效应+8,741.60美元的原参考分解为能量项+8,741.60、显式拥塞项0。这是参考约定下的会计分解；线路定价乘子、G5节点价差和线路放松结果仍直接反映网络作用。利润增加7,811.56美元同时伴随uplift减少578.36美元。详细解释与参考敏感性见结果分析。

## 数据与复现

`source_data/`保存全部主图表源数据及网络比较表；`analysis_summary.json`汇总关键数值；`verification.json`保存独立数值核验。`input_manifest.json`记录76个实际消费的历史源文件SHA-256。`supplement/missing_self_schedules/`保存补齐全域曲线所需的64次单机最优自调度、预算与恢复检查点。已有38个响应直接复用；新增系统UC、CHP建图和计时均为0。

从`chp_marketpower`目录、采用当前已安装研究环境执行：

```powershell
python -m paper_results.build_results --resume
python -m paper_results.prepare_display
python -m paper_results.render_figures
python -m paper_results.audit_results
```

第一步读取既有研究档案并严格检查来源指纹和恢复计划，当前检查点下无需重新优化。求解依赖当前COPT环境；绘图不调用优化器。绘图检查沿用本机nature-figure脚本，路径写在绘图源文件中；迁移机器时需提供该脚本目录。独立数值核验不依赖图形审计脚本。源数据消费关系见追溯表；本目录不是脱离原仓库数据即可独立运行的发布包。

## 完成边界

三项停止条件已满足：实际计时与有限候选证据；价格分量与完整利润账目的对账；G1–G5替代及单线路干预机制。118节点200次查询尚未摊销的结果完整保留。不追加报价扫描、合谋、多维报价、机器学习或完整论文写作。
