# 第五版论文与交付入口

更新：2026-11-03。当前英文题目为 **Strategic Profit Evaluation and Generation Substitution under Multiperiod Convex Hull Pricing**。本轮以首份重评建议为准，暂不按十页压缩；当前编译稿为13页，英文摘要172词、15条引用、四图两表。

- [可阅读 PDF](CHP_market_power_draft.pdf)、[可编辑 LaTeX](main.tex)、[中文摘要](ABSTRACT_ZH.md)
- [第五版建议落实](REVISION_05.md)、[独立修订核查](REVIEW_REVISION_05.md)、[机器验收](validation.json)
- [论证与证据图](DRAFT_PLAN.md)、[统一术语](TERMINOLOGY.md)、[文献与基础模型核查](LITERATURE_AND_MODEL_AUDIT.md)
- [统一实验分析](../paper_results/RESULTS_ANALYSIS.md)、[图表及数值源表](../paper_results/README.md)
- [作者与投稿声明待确认项](SUBMISSION_DECLARATIONS.md)

## 论文主线

第一项贡献把合法参数化 CHP 价格、完整物理 UC 区间与申报 LOC 结算连接起来，使连续报价域可由有限候选评价。第二项贡献用这项能力解释价格收益如何积累，以及竞争机组的跨时段替代成本怎样改变获利机会。

Section IV 先推导实际利润的局部报价响应和完整路径核算，再介绍有成本的发电替代。替代成本前沿提供统一解释：正文给出其定义和值函数关系，数值分析识别实际 A/B/C 竞争方案及成本比。主结果从 G1 的7,811.56美元额外利润出发，再解释G5提前运行；在线成本与线路条件的对照区分既有替代方案变贵和新替代方案可行。

Section V 的四小节依次为利润及结算、发电替代、成本与网络、计算表现。图1利润路径、图2两面板替代机制、图3两面板竞争条件、图4计算复用；表I为结算，表II为计算。历史绘图源文件编号保留。价格参考分量、全矩形排除和网络结算恒等式分别放入附录A–C。

## 编译与验证

本机沿用已安装MiKTeX与LaTeX插件，使用多文件项目的本地编译流程。相对图件路径和BibTeX检索目录必须保留。从 `chp_marketpower` 执行：

```powershell
$env:PYTHONUTF8='1'
$env:PATH='C:/software/Git/usr/bin;'+$env:PATH
$env:BIBINPUTS=(Resolve-Path manuscript).Path+';'
python -X utf8 C:/Users/250010153/.codex/plugins/cache/openai-bundled/latex/0.2.8/scripts/compile_latex.py manuscript/main.tex --compiler texlive --output-directory manuscript/build --json
```

跨机器可使用标准IEEEtran/BibTeX构建。编译输出 `build/main.pdf`，交付副本为 `CHP_market_power_draft.pdf`。检查交付副本、全部图件、引用和源表：

```powershell
python -X utf8 manuscript/check_draft.py
```

`check_draft.py`不再设置页数上限；它核对两项贡献、图表数量、所有引用与关键公式、两表全部数值，以及网络/成本源数据。当前验证中的 `new_optimization_solves=0` 指本轮重构；`archived_factorial_optimization_solves=17` 指复用的11月2日实验。构建缓存、预览与编译过程输出不进入Git。

## 当前状态

本轮完成英文论文、中文摘要、实验分析和图表的统一重构，数值均来自已验证的实验。独立修订核查针对首份建议及数学/证据一致性，不代表期刊正式评审。作者、基金、CRediT、利益冲突和最终AI声明由作者确认，具体记录在声明文件中。投稿页数整理将在用户要求时另行处理。
