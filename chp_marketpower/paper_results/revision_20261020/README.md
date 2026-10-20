# 2026-10-20：定向实验整理与论文结果修订

本轮复用两项已有结果：IEEE118独立500次查询工作负载，以及IEEE30-G1仅改变第1小时报价的完整结算对照。新增优化求解和计时运行均为0。之前四张主图、源表及交付指纹保持原样。

## 修订后的展示

- [Fig. 1](figures/fig1_cumulative_pricing_time.pdf)：三面板保持原结构；IEEE118以独立Q500为主，虚线保留原Q200对照。[SVG](figures/fig1_cumulative_pricing_time.svg) / [PNG](figures/fig1_cumulative_pricing_time.png)。
- [Table I](TABLE_I.md)：四条独立工作负载，保留每项成本和实测摊销点。完整数字见[source_data/table_I_four_workloads.csv](source_data/table_I_four_workloads.csv)。
- [时段报价对照](source_data/temporal_offer_comparison.csv)：进入论文利润结果小节的一段文字，无需增加第五张主图。
- [候选账目](source_data/hour1_profit_candidates_verified.csv)及[共同UC区间证书](source_data/hour1_common_UC_certificates.csv)：可追溯地支持单小时连续报价域结论。
- [修订说明](EXPERIMENT_REVISION.md)、[输入指纹](input_manifest.json)、[核验结果](verification.json)。

## 复现

从`chp_marketpower`目录运行：

```powershell
python -m paper_results.revise_20261020
python -m paper_results.audit_revision_20261020
```

第一条重新读取历史数据、检查模型身份与共同区间证书、生成本目录源表和Fig. 1；不调用优化器。第二条独立核验源指纹、查询前缀与生成表。绘图沿用已安装Python/matplotlib和nature-figure对齐审计脚本。PDF/SVG是矢量交付，PNG为600 dpi预览。

## Fig. 1 caption

**Repeated CHP pricing under fixed market conditions.** Measured cumulative times for (a) IEEE30-G1, (b) IEEE30-G2 and (c) IEEE118-G11. The 30-bus streams each contain 1,000 queries. Solid curves in (c) show the independent 500-query workload; dashed curves retain the separately measured 200-query workload. The two workloads use different query grids and are neither joined nor interpreted as replicate measurements. Persistent reoptimization includes model setup, objective updates, optimization and raw-price extraction. Parametric costs include archived construction, postprocessing, file loading and measured online lookup. Open markers identify the first observed amortized integer query: 138, 18 and 224 for the three principal workloads. The independent 200-query workload does not amortize. System UC and uplift settlement are excluded.

## 图形核验

Fig. 1为183 mm宽三面板定量图，回答“重复报价评价能否摊销完整建图成本”。前两面板展示两个IEEE30报价方向，第三面板用较大模型的两条独立固定工作负载说明查询任务长短的影响。全部实测前缀均保留，无补造或拼接点，无统计重复或置信带。图形对齐通过，PDF最小字体7 pt，严格碰撞检查0 fail/0 warn；整体及每面板已目视检查。静态检查20 pass/1 warn/0 fail，唯一提醒为未生成TIFF；本次以可编辑PDF/SVG和PNG预览交付。
