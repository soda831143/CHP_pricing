# CHP Market Power论文初稿

本轮为2026-10-20第一版完整英文研究论文。目标IEEE Transactions on Energy Markets, Policy, and Regulation。入口为[可编辑LaTeX](main.tex)、[编译PDF](CHP_market_power_draft.pdf)和[中文摘要](ABSTRACT_ZH.md)。

## 论文结构与本轮推进

题目：**Parametric Convex Hull Pricing for Strategic Offer Evaluation and Market Power Analysis**。

六节分别为Introduction、Market Model and Strategic Offers、Parametric Pricing and Finite Offer Evaluation、Profit Formation and Physical Substitution、Numerical Results、Conclusion。数值结果保留四个既定小节和四图两表；本轮将IEEE118独立Q500计时补入主图并保留独立Q200对照，将G1单小时报价对照写入V-C，不追加图件或优化求解。

模型沿用旧稿的物理UC、PTDF和三种调度对象，参考经典网络流/扩展式，使用直接区间功率及相邻功率爬坡约束。当前引擎已经采用直接区间功率，不需要改动基础模型。基础UC凸化是已有研究基础；新稿的两项贡献是参数化连续策略评价与完整申报uplift下的经济机制。

- [写作配置、提纲与主张—证据映射](DRAFT_PLAN.md)
- [12条文献与直接功率模型核查](LITERATURE_AND_MODEL_AUDIT.md)；[BibTeX文献库](references.bib)
- [两项定向实验修订与来源](../paper_results/revision_20261020/README.md)
- [独立首轮审阅](REVIEW_ROUND1.md)；[修订闭环与最终检查](QA_REPORT.md)
- [作者、基金、CRediT、利益冲突和AI声明确认表](SUBMISSION_DECLARATIONS.md)

## 编译与结果复现

从仓库`chp_marketpower`目录执行定向数据核验：

```powershell
python -m paper_results.revise_20261020
python -m paper_results.audit_revision_20261020
python -m paper_results.audit_results
```

本机已有MiKTeX和Git附带的Perl。本轮通过LaTeX插件编译；只在该编译进程设置UTF-8、Perl路径和本稿BibTeX检索目录，未修改系统环境。示例（插件路径按已安装版本）：

```powershell
$env:PYTHONUTF8='1'
$env:PATH='C:/software/Git/usr/bin;'+$env:PATH
$env:BIBINPUTS=(Resolve-Path manuscript).Path+';'
python -X utf8 C:/Users/250010153/.codex/plugins/cache/openai-bundled/latex/0.2.8/scripts/compile_latex.py manuscript/main.tex --compiler texlive --output-directory manuscript/build --json
```

输出`manuscript/build/main.pdf`；交付副本为`CHP_market_power_draft.pdf`。跨机器可采用标准IEEEtran/BibTeX构建，确保相对图件路径保留。构建缓存、预览PNG不纳入Git；交付PDF、源码、文献和验证摘要纳入Git。

## 期刊与初稿边界

2026-10-20已查阅[IEEE T-EMPR官方页面](https://ieee-pes.org/publications/transactions-on-energy-markets-policy-and-regulation/)与[PES作者指南](https://ieee-pes.org/publications/authors-kit/information-for-authors-of-ieee-power-energy-society-transactions-papers/)：首次投稿不超过10页，摘要约150–200词。本稿采用IEEEtran双栏，英文摘要193词；最终编译页数和无未定义引用记录见QA报告。

作者/单位暂沿用用户旧稿，基金、贡献分工与利益冲突需作者确认。本稿没有提交期刊；研究范围是已声明方向、报价域、选价和执行规则。IEEE118两个工作负载是独立测量，计时比例不是UC/LOC利润评价的整体加速；线路放松结果是各网络自身基准下的同报价比较。
