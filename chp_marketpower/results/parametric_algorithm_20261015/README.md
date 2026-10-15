# 三项论文实验：结果与复现

实验开始于 2026-10-15，完成并整理于 2026-10-16。研究解释见 [论文实验方案与结果](../../PAPER_STUDY_20261015.md)，数学条件见 [算法方案](../../PARAMETRIC_ORACLE_ALGORITHM_20261015.md)。本目录不替换此前发布的地图。

## 归档范围

四份完整主地图均保存 `oracle.npz` 原始—完整对偶见证、`audit.json`、`compact.npz`、`compression.json` 与 `validation.json`：

| 目录 | 参数范围与用途 | 价值区间 / 所选价格分段 |
|---|---|---:|
| `30_persistent_bracket` | 30-G1，0–20%，默认策略及性能主图 | 8 / 8 |
| `30_active_cone` | 同一 30-G1 范围，完整活动法锥扩张 | 8 / 8 |
| `6_persistent_bracket_complete` | 6-G2，0–10%，默认策略完整运行 | 63 / 65 |
| `6_active_cone_extended` | 同一 6-G2 范围，完整活动法锥扩张 | 63 / 65 |

其余七种探索／消融版本只提交 `audit.json`，已完成压缩者另保留 `compression.json`；包含完整覆盖版本和预算耗尽的部分版本，不将后者算作全域 Oracle。原始见证仍在本地，未重复上传。`6_active_cone` 为缓存上界系数改进之前的早期原型，不能拿它与最终完整版本直接作等配置运行时间比较。`tables/` 汇总全部版本及两种完整算法的价值图一致性。

`timing/` 保存预先固定的乱序负载、12 批实际计时和汇总，`application_final/` 保存有限范围价格影响与三点经济结算，`figures_final/` 为三张最终 PNG/PDF 图。旧的诊断图、应用输出、单次探针不重复提交。

数值环境为 COPT 8.0.6，经本机全局 `gurobi_compat` 使用；CHP 与辅助 LP 采用 simplex、可行性及对偶容差 `1e-9`。活动项阈值 `1e-8`，开放区间价值／对偶间隙门槛 `1e-6` 美元；后者不是节点价格误差界。线程按现有模型默认设置，未另行调优。运行时间受机器状态影响；三批重复针对查询阶段，离线构造成本测量一次。源文件冻结哈希和前置提交在 `timing/frozen_plan.json`；后续调整了应用图、归档和说明，并修正基线文件中一行采样覆盖注释，未改变已计时基线的运算逻辑。冻结哈希保留当时的原始记录，不改写成事后的文件哈希。

## 复现主要结果

以下在 `chp_marketpower/` 中执行。所有 `reproduce_*` 必须是新目录；不要覆盖已发布的价格路径。报价为美元/MWh 的绝对加数，命令中的 generator 是零起算索引。

```powershell
python run_affine_oracle.py --discover --complete --case 30 --generator 0 --upper 8.3964 --max-points 40 --out-dir results/reproduce_30_bracket
python run_region_oracle.py --case 30 --generator 0 --upper 8.3964 --max-chp-solves 40 --formulation active_cone --out-dir results/reproduce_30_region
python run_affine_oracle.py --discover --complete --case 6 --generator 1 --upper 1.1999875 --max-points 160 --out-dir results/reproduce_6_bracket
python run_region_oracle.py --case 6 --generator 1 --upper 1.1999875 --max-chp-solves 120 --formulation active_cone --out-dir results/reproduce_6_region
```

对每份完整输出运行后处理及独立验证，例如：

```powershell
python postprocess_oracle.py --oracle-dir results/reproduce_30_bracket
python validate_affine_oracle.py --oracle-dir results/reproduce_30_bracket --fractions 0.001 0.5 0.999 --persistent-direct
python run_oracle_paper_study.py --stage timing --oracle-dir results/reproduce_30_bracket --output results/reproduce_timing
python run_oracle_paper_study.py --stage application --oracle-dir results/reproduce_30_bracket --output results/reproduce_application
python run_oracle_paper_study.py --stage figures --oracle-dir results/reproduce_30_bracket --timing-dir results/reproduce_timing --application-dir results/reproduce_application --output results/reproduce_figures
```

应用阶段明确使用另外已归档的 `results/budgeted_oracle_30_G1_economic/`（40–45%）做 UC/自调度结算。它不是 0–20% 主图的外推。

主表其余消融通过 `--endpoint-solver fresh`、`--formulation full_dual` 或 40/120 点预算复现；旧图扩张使用 `--initial-map results/budgeted_oracle_6_G2`，新范围 `--upper 1.1999875`、总点数预算 40，旧图费用包含在报告中。`tables` 阶段使用本批目录约定的四个主图名称，汇总时应保持这些名称，而非任意重命名。

## 解释边界

两种策略利用同一原始—对偶最优性原理。辅助 LP 的全部工作计入离线成本；主 CHP 次数减少不代表总耗时必然下降。完整对偶插值构成一条声明的合法选价路径，不要求等于独立求解器任意选择的价格，不代表所有最优价格。当前结果是声明容差下的数值验证，不是符号精确边界证明，也不是整个报价域上的利润最优性证明。
