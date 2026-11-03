# CHP 市场力研究

2026-11-03更新。研究问题是：如何在多时段网络约束 CHP 下完整评价连续报价的实际利润，以及竞争机组以什么运行成本和可行轨迹限制这种获利。当前第五版按这一问题重构，暂不按十页压缩。

## 当前成果

- **论文：** [英文 PDF](manuscript/CHP_market_power_draft.pdf)、[LaTeX 正文](manuscript/main.tex)、[中文摘要](manuscript/ABSTRACT_ZH.md)。
- **结果：** [统一实验分析](paper_results/RESULTS_ANALYSIS.md)、[图表与源数据入口](paper_results/README.md)。
- **进度：** [研究状态与后续选择](RESEARCH_PLAN.md)、[建议落实记录](manuscript/REVISION_05.md)、[独立修订核查](manuscript/REVIEW_REVISION_05.md)。
- **整理：** [保留与删除范围](CLEANUP.md)、[主分支同步约定](PUBLISHING_PREFERENCE.md)。

G1 在声明的全天增量报价方向、合法选价路径与有利边界执行规则下，额外利润为 **7,811.56 USD**。结算贡献为能量收入 +4,385.61、uplift −578.36、实际成本节约 +4,004.31 USD。利润路径核算则为价格效应 +8,741.60、连续报价暴露效应 −29.23、此前物理切换效应 −900.82 USD；两套账目分别解释最终收益与收益积累过程。

G5 提前五小时启动的完整替代方案增加实际系统成本 1,387.35 USD，并减少 G1 报价暴露 105.07 MWh，形成约 13.204 USD/MWh 的物理切换门槛。在线成本增加使原网络门槛移至 13.442；放松线路 30 后，新的可行方案 C 在指定报价—成本矩形内严格优于原 A/B。变化条件下的结算使用各自真实报价基准，范围为两个固定报价。

## 代码与证据

|目录或入口|用途|
|---|---|
|`engine.py`、`../chp_energy/`|同口径物理 UC、CHP 与自调度引擎|
|`price_vulnerability/`|固定可行域的参数化价格与完整对偶、共同物理区间|
|`run_profit_range.py`、`strategic_market_simulation/`|连续报价与完整申报 LOC 利润|
|`mechanism_study/`|利润路径、替代成本和条件对照|
|`paper_results/`|统一图表、数值源表和独立核验|
|`manuscript/`|唯一现行论文、术语、修订核查与声明|
|`dashboard/`|[本地交互工作台](dashboard/README.md)|

[参数化模型](PARAMETRIC_FORMULATION.md)、[区域发现算法](PARAMETRIC_ORACLE_ALGORITHM_20261015.md)、[报价域口径](BID_DOMAIN_AND_SCALING_20261016.md)和[连续利润技术说明](TARGETED_STUDY_20261016.md)保留为技术参考。阶段性规划已整合到上述当前入口；历史版本可从 Git 历史恢复。

## 复现与检查

在已安装 COPT、NumPy、Matplotlib、PyMuPDF 的研究环境中，从本目录执行：

```powershell
python -m paper_results.audit_results
python -m paper_results.audit_revision_20261020
python -m paper_results.revise_20261021
python -m paper_results.competition_analysis_20261102
python -m pytest tests/test_competition_regimes.py tests/test_profit_identity.py tests/test_paper_components.py tests/test_predictive_mechanism.py -q
```

前四项只读取已有优化结果。当前主文图依次为利润路径、发电替代、成本与网络变化、计算复用。新对照图可独立重绘：

```powershell
python -c "from paper_results.render_figures import competition_conditions; competition_conditions()"
```

完整绘图沿用已有 Python 工作流；[论文目录](manuscript/README.md)说明编译与验收。价格查询计时、完整利润评价和场景对照各采用自己的范围：G1 有 83 个价格区间、17 个物理区间、99 个联合区间和 116 个候选；30-G2 和 118 节点结果不作为同口径全域利润排名。
