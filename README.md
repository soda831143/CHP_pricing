# CHP Research

当前主线是多时段网络约束凸包定价下的连续策略利润评价，以及价格响应和竞争性发电替代如何共同形成获利机会。2026-11-03完成第五版论文与结果整合；主分支为 `master`。

- [英文论文 PDF](chp_marketpower/manuscript/CHP_market_power_draft.pdf)与[可编辑正文](chp_marketpower/manuscript/main.tex)
- [当前进度与复现入口](chp_marketpower/README.md)
- [统一实验分析](chp_marketpower/paper_results/RESULTS_ANALYSIS.md)
- [论文修订与建议落实](chp_marketpower/manuscript/REVISION_05.md)
- [仓库整理说明](chp_marketpower/CLEANUP.md)

```text
chp_energy/       UC、精确 CHP 引擎、算例和基础测试
chp_marketpower/  连续报价方法、利润评价、论文及证据
```

G1 案例的完整结算额外利润为 7,811.56 USD。报价路径上的价格收益积累与 G5 提前启动的替代成本承担不同的解释任务；在线成本变化移动原有替代门槛，线路放松则允许另一套更便宜的运行方案。方法将该连续报价域归结为 116 个报价/物理方案候选。计算计时覆盖 30、118 节点，比例专指重复 CHP 价格查询。

核心复现从 `chp_marketpower` 执行：

```powershell
python -m paper_results.audit_results
python -m paper_results.audit_revision_20261020
python -m paper_results.revise_20261021
python -m paper_results.competition_analysis_20261102
```

这些命令核对已有见证和源表，不新增优化求解。完整环境、论文编译和测试说明见市场力目录。原始算例与必要结果保留；本地 `energy-reserve/` 是未被当前代码导入的旧引擎副本，不纳入版本控制。旧研究分支保留历史，后续常规推进同步到 `master`。
