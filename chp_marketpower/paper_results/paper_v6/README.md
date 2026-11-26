# 当前论文基线（③ 新稿）

> 自 2026-11-26 起，论文修改都在本目录进行。这是唯一基线稿；`../../manuscript/main.tex` 是上一版（②），只作为回写来源，不再并行修改。

## 文件

| 文件 | 说明 |
|---|---|
| `main3rd.tex` | 正文（685 行，IEEEtran journal） |
| `references.bib` | 24 条；已补齐 ② 中缺失的 6 条引用 |
| `figures/` | 4 张 JPG：DAG 示意、`heatmap-profit-uplift`、`fig_v3_competition`、`fig_v4_timing` |

状态：**未编译**（本目录无 PDF）、**未入 git**（未跟踪）。图件为 JPG，没有旧管线的 alignment / collision 审计。

> 2026-11-26 由 `From Price Influence to Actual Profit Strategic Offer under Multiperiod Convex Hull Pricing/` 改名为 `paper_v6/`，缩短带空格的长路径；正文题目不变。图件（43 MB JPG）暂不入 git，编译前需由本地 `figures/` 提供，或由 `../figures/figure.opju` 重出。

## 与 ②（manuscript/main.tex，11-17）的差异

| 项 | ② | ③ |
|---|---|---|
| 题名 | Strategic Profit Evaluation and Generation Substitution… | From Price Influence to Actual Profit: Strategic Offer… |
| 摘要 / 引言 | 旧版 | 重写，按结构性挑战 / 计算挑战组织 |
| 结构 | 三图三表 + 附录 A–C | 三图三表，附录删除；V 节 103→149 行 |
| 第三方案 | 记作 C | 改记作 W |
| 引用 | 21 个引用键，bib 15 条，6 条 undefined | 24 个引用键，bib 24 条，无 dangling ref |
| Q200 未摊销 | 表 I 保留 | 正文未出现 |
| 图件 | PDF/SVG + 审计 JSON | JPG 手工管线（含 15 MB 热图、`figure.opju`） |

数字未变：G1 额外利润 7,811.56（13.204 \$/MWh，31.45%），结算 ΔR +4,385.61 / ΔU −578.36 / ΔC −4,004.31，路径 +8,741.60 / −29.23 / −900.82，A/B 门槛 1,387.35 与 105.07 MWh，ε=5 → 13.442，W 四角优势 1,635.46，83/17/99/116 与计时 6.74× / 20.54× / 2.00×。

## 待裁决（三项，需作者决定）

1. **附录 A–C 去留**：价格参考分量、全矩形排除、网络结算恒等式目前从正文消失。若期刊篇幅允许，建议至少保留网络结算恒等式（它支撑 uplift 与输电调整的对账）。
2. **Q200 未摊销**：② 把它作为负结果保留。删掉会削弱“复用何时合算”的可信度；建议在 V-E 补一句。
3. **图件管线**：JPG 无矢量、无审计、单文件最大 15 MB。建议回到 ② 的 PDF/SVG + alignment 审计，或明确记录 JPG 为期刊终稿格式。

## 稿件内部待清理

- 第 581、611、613 行附近留有整段注释的旧版重复文字，编译不报错但会干扰后续修改。
- `\label{cor:exposure}` 挂在 `proposition` 环境上（正文称 Proposition），建议改为 `prop:exposure`。
- 正文写 "modified IEEE 30-bus system with six generators"，与 ② 一致，未复核算例文件本身。

## 编译

沿用 `manuscript/README.md` 的方法，把入口换成 `main3rd.tex`，并从本目录执行（`figures/` 为相对路径）：

```powershell
$env:PYTHONUTF8='1'
$env:PATH='C:/software/Git/usr/bin;'+$env:PATH
cd "paper_results/paper_v6"
python -X utf8 C:/Users/250010153/.codex/plugins/cache/openai-bundled/latex/0.2.8/scripts/compile_latex.py main3rd.tex --compiler texlive --json
```

首次编译后检查日志中的 undefined citation / reference，并核对图表编号与 `../../manuscript/DRAFT_PLAN.md` 的证据要求。

## 数字出处

`../../paper_results/source_data/`（利润曲线、结算、门槛、联合区间）、`../../paper_results/revision_20261020|20261021|20261102/source_data/`（计时、网络账目、2×2）。逐项对应见 `../../paper_results/README.md` 与 `RESULTS_ANALYSIS.md`。
