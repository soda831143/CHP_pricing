# CHP Market Power论文初稿

当前为2026-11-02第四版完整英文研究论文（按用户要求采用12–13页工作稿）。目标IEEE Transactions on Energy Markets, Policy, and Regulation。入口为[可编辑LaTeX](main.tex)、[编译PDF](CHP_market_power_draft.pdf)和[中文摘要](ABSTRACT_ZH.md)。

当前修订依据见[第四版修改记录](REVISION_04.md)、[成本与网络的机制区分实验](../paper_results/revision_20261102/README.md)、[全文术语账本](TERMINOLOGY.md)和[当前验证结果](validation.json)。引言保持三段开场、Related Work、三点Our Contributions。经济分析以替代门槛及其适用条件为主线；[第三版](REVISION_03.md)的结算关系和切换推论作为理论工具保留。当前文献15条。

## 论文结构与本轮推进

题目：**Parametric Convex Hull Pricing for Strategic Offer Evaluation and Market Power Analysis**。

六节分别为Introduction、Market Model and Strategic Offers、Parametric Pricing and Finite Offer Evaluation、Profit Formation and Substitution Regimes、Numerical Results、Conclusion。数值结果保留四个既定小节和四图两表。第四版补齐原网络/放松网络与G5在线成本0/+5美元的2×2对照，固定两个报价并使用各条件自己的真实报价基准；新增5次物理UC、6次CHP和6次自调度求解。完整数据和来源进入定向实验目录，不另增主图。

模型沿用旧稿的物理UC、PTDF和三种调度对象，参考经典网络流/扩展式，使用直接区间功率及相邻功率爬坡约束。当前引擎已经采用直接区间功率，不需要改动基础模型。基础UC凸化是已有研究基础；新稿的三点贡献依次为可复用参数化CHP、物理UC区域与有限利润候选、结算及替代机制；它们围绕计算能力和市场认识两条主线。

- [写作配置、提纲与主张—证据映射](DRAFT_PLAN.md)
- [初版12条文献与直接功率模型核查](LITERATURE_AND_MODEL_AUDIT.md)；[BibTeX文献库](references.bib)
- [两项定向实验修订与来源](../paper_results/revision_20261020/README.md)
- [初版独立首轮审阅](REVIEW_ROUND1.md)；[初版验收记录](QA_REPORT.md)；[当前修订验收](REVISION_04.md)
- [作者、基金、CRediT、利益冲突和AI声明确认表](SUBMISSION_DECLARATIONS.md)

## 编译与结果复现

从仓库`chp_marketpower`目录执行定向数据核验：

```powershell
python -m paper_results.revise_20261020
python -m paper_results.audit_revision_20261020
python -m paper_results.revise_20261021
python -m paper_results.competition_analysis_20261102
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

2026-10-20已查阅[IEEE T-EMPR官方页面](https://ieee-pes.org/publications/transactions-on-energy-markets-policy-and-regulation/)与[PES作者指南](https://ieee-pes.org/publications/authors-kit/information-for-authors-of-ieee-power-energy-society-transactions-papers/)：首次投稿不超过10页，摘要约150–200词。当前按用户要求先完成12–13页工作稿，未按正式投稿页数压缩方法。本文采用IEEEtran双栏；当前摘要词数、编译页数和引用核验见validation.json，初版QA报告保留为历史记录。

当前第四版13页、英文摘要184词，引用与版面核验见validation.json。作者/单位暂沿用用户旧稿，基金、贡献分工与利益冲突需作者确认。本稿没有提交期刊；研究范围是已声明方向、报价域、选价和执行规则。IEEE118两个工作负载是独立测量，计时比例不是UC/LOC利润评价的整体加速；变化条件的利润结果为两个指定报价的比较，未计算各条件全域最大市场力。
