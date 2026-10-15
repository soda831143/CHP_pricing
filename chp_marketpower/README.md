# CHP Market Power

**当前论文主线（更新至 2026-10-16）：** [区域发现算法与三项论文实验](PARAMETRIC_ORACLE_ALGORITHM_20261015.md)，结果及主图见 [三项论文实验的进展](PAPER_STUDY_20261015.md)，复现及归档范围见 [本轮结果说明](results/parametric_algorithm_20261015/README.md)。[e9393f9 阶段的 Oracle 结果](ORACLE_STUDY_2026-10-15.md)与[匹配定价规则及利润实验](MECHANISM_STUDY_2026-10-15.md)保留为前期证据；下方早期 R2/R3 段落不代表当前优先级。

本目录研究“机组报价改变后，凸包定价的最优值与节点价格如何分区变化；这些响应何时能变成按真实成本计算的额外利润”。完整研究路线见 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)；一维参数 LP、最优面左右导数、价值优先重构和价格层门槛见 [PARAMETRIC_FORMULATION.md](PARAMETRIC_FORMULATION.md)。

较早的相对乘数 G1/G5 实验见 [PAPER_DIRECTION_2026-10-14.md](PAPER_DIRECTION_2026-10-14.md)。价格选择的理论边界见 [RESEARCH_UPDATE_2026-09-23.md](RESEARCH_UPDATE_2026-09-23.md)；基事件仅保留为诊断。

代码直接复用相邻的 `../chp_energy/` 的案例、物理 UC、exact DAG-CHP 和自调度求解器，不复制第二套市场模型。

底层 `PrimalCHPLP` 现在只用 Yu/Pan 式绝对 ON-interval 出力 \(q\)（区间 \(p\) 坐标），不再把差分爬坡量 \(v\) 设为 CHP 决策变量；这是等价实现选择，不是论文方法贡献。`yu` 不再是独立 benchmark，因为它与 `chp` 是同一个 LP。6 节点 G2、\(\delta\in[0,0.1]\) 的价值层已过三档 COPT 容差检查；当前已将同一绝对报价与结算核算接到 6/30/118 节点，不扩多主体博弈。

## 可运行入口

在本目录执行（数值求解使用 COPT 8，经全局 `gurobi_compat` 垫片复用已有模型）：

当前主线可按下面的顺序复现；构造和批次输出使用尚不存在的新目录，旧价格路径版本会保留。

```powershell
python run_affine_oracle.py --discover --complete --case 30 --generator 0 --upper 8.3964 --out-dir results/paper30_new
python postprocess_oracle.py --oracle-dir results/paper30_new
python validate_affine_oracle.py --oracle-dir results/paper30_new --fractions 0.001 0.5 0.999 --persistent-direct
python run_oracle_paper_study.py --stage timing --oracle-dir results/paper30_new --output results/paper30_timing_new
```

`run_affine_oracle.py` 默认使用持久模型细分；`--endpoint-solver fresh` 是逐点重建的实现消融。`run_region_oracle.py --formulation active_cone` 使用完整活动法锥的有效区间辅助 LP；`full_dual` 保留未经消元的 formulation。`--initial-map` 可把已有小地图扩到更大的报价范围。原目录续算需要保持原求解方式，旧 fresh 地图须显式给 `--endpoint-solver fresh`；换方式应保存为新地图。

以下是前期研究和各功能入口，历史范围与优先级以页首最新实验方案为准：

```powershell
python run_unified_bid_experiment.py --case 6 --generator 1 --rho 0 0.025 0.05 0.10 0.20 0.30 0.50
python run_unified_bid_experiment.py --case 30 --generator 0 --rho 0 0.025 0.05 0.10 0.20 0.30 0.50
python run_unified_bid_experiment.py --case 30 --generator 4 --rho 0 0.025 0.05 0.10 0.20 0.30 0.50
python run_unified_bid_experiment.py --case 118 --generator 10 --T 12 --rho 0 0.05 0.10 0.20
python run_pricing_diagnostics.py --case 6 --scenario C3 --T 24 --segments 3 --dual-audit --include-uc --out-dir results/diagnostics_C3
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization relative --epsilon 0.005 --out-dir results/full_C3_relative_eps0005
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization absolute --epsilon 0.1 --out-dir results/full_C3_absolute_eps01
python run_profit_validation.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generators 0 1 2 --beta 0 0.05 0.10 --bid-cap 0.10 --out results/profit_c3_24h_pilot_strict.csv
python run_parametric_regime_scan.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --grid 0 0.025 0.05 0.075 0.10 --out-dir results/regime_G2_direct
python run_basis_dual_audit.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --deltas 0 0.04 0.06 0.10 --out results/basis_dual_G2.json
python run_value_oracle.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --lower 0 --upper 0.1 --out-dir results/value_oracle_G2_absolute_residual_audit
python run_affine_oracle.py --regimes results/value_oracle_G2_absolute_residual_audit/value_regimes.csv --out-dir results/affine_oracle_G2
python run_affine_oracle.py --out-dir results/affine_oracle_G2 --query 0.05
python run_affine_oracle.py --discover --case 6 --generator 1 --lower 0 --upper 0.1 --max-points 30 --out-dir results/budgeted_oracle_6_G2
python run_affine_oracle.py --discover --case 30 --generator 0 --lower 16.7928 --upper 18.8919 --max-points 30 --out-dir results/budgeted_oracle_30_G1_economic
python validate_affine_oracle.py --oracle-dir results/budgeted_oracle_30_G1_economic --extra-deltas 17.84235
python run_affine_oracle.py --out-dir results/budgeted_oracle_30_G1_economic --query 17.84235
python run_selector_settlement.py --oracle-dir results/budgeted_oracle_30_G1_economic --delta 17.84235 --output results/budgeted_oracle_30_G1_economic/selector_settlement.json
python run_affine_oracle.py --discover --case 30 --generator 0 --lower 0 --upper 20.991 --max-points 30 --focus-lower 16.7928 --focus-upper 18.8919 --focus-budget 12 --out-dir results/budgeted_oracle_30_G1_broad_focused
python run_affine_oracle.py --discover --complete --case 30 --generator 0 --lower 0 --upper 8.3964 --max-points 40 --out-dir results/complete_oracle_30_G1_0to20pct
python postprocess_oracle.py --oracle-dir results/complete_oracle_30_G1_0to20pct
python run_affine_oracle.py --discover --complete --endpoint-solver persistent --case 30 --generator 0 --upper 8.3964 --out-dir results/new_30_persistent_bracket
python postprocess_oracle.py --oracle-dir results/new_30_persistent_bracket
python run_region_oracle.py --case 6 --generator 1 --upper 1.1999875 --max-chp-solves 120 --formulation active_cone --out-dir results/new_6_region
python run_oracle_paper_study.py --stage timing --oracle-dir results/new_30_persistent_bracket --output results/new_timing
python benchmark_oracle_queries.py --oracle-dir results/complete_oracle_30_G1_0to20pct --queries 24
python run_affine_oracle.py --discover --case 6 --generator 1 --lower 0 --upper 1.1999875 --max-points 55 --resume-from results/complete_oracle_6_G2_0to10pct --seed-delta 0.05 --out-dir results/learned_oracle_6_G2_seed005_local
python run_price_probe.py --regimes results/value_oracle_G2_absolute_nominal/value_regimes.csv --out-dir results/price_probe_G2_absolute
```

`run_affine_oracle.py --discover` 是当前主线：在 6/30 节点用共同原问题最优解和**完整对偶**审计建立可在线插值的报价窗口。`--complete` 要求全域价格覆盖，否则到预算上限时保留检查点并明确退出；普通预算模式只开放已通过区间，其他价格直接重求 CHP，不把小价值误差误作价格误差。`--resume` 在同目录续算；`--resume-from` 与 `--seed-delta` 则从旧部分地图分叉、只在被查询的未覆盖区间追加求解，旧地图不变。`postprocess_oracle.py` 分别合并价值区间和无损压缩既有选价路径，保留原始见证；`benchmark_oracle_queries.py` 实测固定报价工作负载下的新建模型、同模型重优化与精简 Oracle。`validate_affine_oracle.py` 在未用于建图的内部点重求 CHP 并检验插值完整对偶。`run_selector_settlement.py` 固定同一物理 UC，比较两个合法价格下的收入、uplift 与利润。详见顶部研究方案；早期基追踪入口仅作诊断。

诊断入口分别输出定价 LP 正流 ON/OFF 弧、活动爬坡、线路潮流与对偶，并可单独保存物理 UC；hourly 入口输出节点×价格小时×报价小时的 Jacobian、全矩阵及逐报价小时步长预警和热图，支持相对百分比及绝对美元/MWh 斜率扰动；利润入口逐点重求 UC/CHP/申报 uplift，并按不变的真实成本核算利润。`run_price_vulnerability.py` 用于整段相对或绝对加价快筛，**其分数不是 hourly VI**。利润网格的最大增益只是观察值，不是全局最优策略。

`run_parametric_regime_scan.py` 是一维绝对报价加数的 **direct-solve grid baseline**：输出各网格点、相邻区间价格/目标斜率和候选切换点。这里的加数作用于战略机组的高于最小出力电量 \(p-P_{\min}u\)，已改写为只进入目标函数；网格候选仍不能称为精确断点。

`run_value_oracle.py` 先重构与基选择无关的凹分段线性价值函数。每个参数点除原 CHP 外，还在带显式美元容差的数值最优面上最小化/最大化增量电量暴露，以近似右/左导数；原 CHP 和两个辅助 LP 均须 `OPTIMAL`。支撑线交点递归发现隐藏区间，最终在每个区间的 25%、50%、75% 处直接复算。6 节点 G2 的 \([0,0.1]\) 绝对坐标在三档 COPT 容差下均得到 5 个价值区间和 4 个断点（约 0.017679、0.018044、0.043396、0.084123），每档 15 个内部验证点全部通过，最窄段在三档下保留。它们是 **numerically validated piecewise-linear value regimes under COPT optimality and declared tolerances**，不是数学精确证书，亦不是 price oracle。CLI 可设置 `--feasibility-tolerance`、`--optimality-tolerance`、`--face-tolerance`，输出包含各辅助 LP 运行时间。

`run_price_probe.py` 仅在这五段各取 10%/50%/90% 三个内部点，用未经裁剪的全节点价格比较 simplex 与 barrier+crossover，并在中点增加 barrier without crossover，测中点仿射误差。它是 R3 的 Go/No-Go 探针，**不是**全局价格区间枚举；若出现算法选择分歧，先报告价格区间或退回价值区间加直接重求的经验价格，不强称精确 price oracle。

`run_basis_dual_audit.py` 用 simplex 与 barrier+crossover 检查 COPT 基状态、约化成本符号、零约化成本非基本变量、落在界上的基本变量和算法间价格差。它是 **R1.5 退化审计**，不是新的市场力指标：基事件、价值事件、价格事件和物理/经济事件必须分层；算法结果一致不能证明对偶唯一，存在零约化成本也不能单独证明对偶不唯一。

候选切换点前后的 Phase-1 活动弧、爬坡和线路对偶直接复用诊断入口，例如 `--bid-adder 1 0.04`。该选项只诊断报价后的定价 LP；它不与 `--include-uc` 混用，物理 UC 与利润必须走 `run_profit_validation.py` 的完整重结算。

诊断与 hourly 入口接受 `--scenario C0/C1/C2/C2N/C3`，依次检验启停、正常爬坡、无拥塞网络表述和收紧线限网络。C2N/C3 使用相同 PTDF、负荷及机组，只有线限不同；`--load-scale` 同比例缩放节点负荷，`--load-shift FROM_BUS TO_BUS FRACTION` 在每小时总负荷不变时移动节点负荷，`--warmup-initial-state` 用一日前置物理 UC 的日末状态构造正式日初态。利润入口不接受 `--scenario`；其中 `--network ptdf --congestion tight` 对应 C3。更完整的数值、局限和后续检验见 [PILOT_EVIDENCE.md](PILOT_EVIDENCE.md)，复现命令见 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)。旧文献可比性见 [REFERENCE_2021_AUDIT.md](REFERENCE_2021_AUDIT.md)。

## 检查与输出

```powershell
python -m pytest -q tests
python tests/check_chp_integration.py
```

前者包含小规模 COPT 辅助 LP，需要安装 COPT 及兼容接口；后者需要有效 COPT 许可证，验证默认报价兼容性、逐小时报价、绝对斜率加数、C0 的跨小时零响应、C2N/C3 拥塞配对及利润会计恒等式。持久模型解刷新另见 `python tests/check_persistent_chp.py`。利润入口要求 UC、自调度和 CHP 均证明最优，否则拒绝该网格点。输出放在 `results/`；正式论文结果应另存案例配置、COPT/垫片版本和原始表。

历史 30 节点 P0 的主结果为 `full_case30_C3_relative_twostep_copt/`、`full_case30_C3_absolute_twostep_copt/`、`profit_case30_C3_all_dispatched_copt.csv` 和 `copt_validation_C3/`；smoke、单步长运行和局部探针保留作审计。当前论文主结果以页首三项实验为准。

P1 主结果为 `p1_shift23to21_r020/` 和 `p1_warmup/`；`p1_shift23to21_r005_diagnostics/` 只记录“同一活动区域，按规则停止”的负结果，不追加对应 VI 或利润。

## COPT 迁移状态

代码中已无 `gurobipy` 直接导入；现有代数模型通过全局 `gurobi_compat` 调用 COPT，矩阵 CHP 路径使用 COPT 原生的矩阵变量命名、约束方向和向量取值接口。迁移回归包括：`chp_energy` 12 项测试、上述市场力集成检查、6 节点全部定价方法 smoke，以及 6/30 节点同配置的目标、节点价、结算量和 UC 数值对照。30 节点比较中 UC 目标差 $5.82\times10^{-11}$ 美元、CHP 定价目标差 $2.13\times10^{-6}$ 美元，详细判据见 [PILOT_EVIDENCE.md](PILOT_EVIDENCE.md)。COPT 的 `auto/simplex/barrier+crossover` 审计只检查算法选择敏感性，不证明对偶唯一。

## 历史阶段记录：R2 残差审计与早期 R3 价格探针（6 节点 G2）

以下记录解释研究如何从基追踪转向完整对偶选价；其中当时的范围限制与“下一步”不适用于当前 Oracle 主线，现行结论以页首研究方案为准。

当时只使用全日统一绝对报价加数 `δ∈[0,0.1]`，暂不扩 30 节点、利润或其他报价参数。复算顺序：

```powershell
python run_value_oracle.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --lower 0 --upper 0.1 --out-dir results/value_oracle_G2_absolute_residual_audit
python tests/check_price_envelope.py
python run_price_probe.py --regimes results/value_oracle_G2_absolute_residual_audit/value_regimes.csv --out-dir results/price_probe_G2_absolute_three_methods
python run_price_oracle.py
```

最优面辅助 LP 现在逐点记录 `face_min_residual` 和 `face_max_residual`。原先把约束 RHS 放宽整整 `1e-10` 美元时，实际目标残差在 20/24 点超出该数（最大 `1.237e-10`），故那次运行不算通过。将 RHS 只放宽审计带的一半，另一半留给数值行误差后，仍得到五个价值区间、15 个内部点全部通过，24 个点的最大实测残差为 `8.004e-11` 美元。该半带是数值保护，不是符号证明；若换求解器或数据，必须重跑实测审计。

节点负荷双侧差分对第 19 小时第 1、6 节点的 raw CHP 电价误差分别为 `1.76e-9`、`2.64e-9` 美元/MWh。simplex 与 barrier+crossover 的原始价格仍高度一致；新增 barrier without crossover 在五段中点相对 simplex 的最大差异为 `3.535e-6` 美元/MWh。这是额外稳定性信息，**不证明对偶唯一**，并提醒不要把求解器容差下的微小方法差异写成完全相同。

R3 目前在五段中观察到五条不同的完整节点×小时 simplex 仿射价格线；各段 25%/50%/75% 和四个价值断点两侧共 23 次直接价格复核，最大误差 `2.52e-12` 美元/MWh（另有 10 次端内锚点求解）。`price_vulnerability/price_oracle.py` 已同时检查原变量约化成本和所有不等式行松弛/对偶，避免漏掉线路或爬坡行事件。但 COPT 在部分区间内部给出零距离退化事件，个别基反解还不可用，无法据此完成无遗漏的基延拓。因此 `run_price_oracle.py` 明确输出 `complete_price_regime_count: null`：**当前答案是五条不同且经数值复核的选定价格线，不是已经证明全域恰有五个真正价格区间**。下一步只需解决退化基下的完整延拓或改为明确定义的对偶价格选择/区间；在此之前不进入利润层。
