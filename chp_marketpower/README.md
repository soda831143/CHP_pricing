# CHP Market Power

本目录研究“机组报价改变后，凸包电价在时间和空间上如何响应；这些响应何时能变成按真实成本计算的额外利润”。完整研究路线见 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)；一维参数 LP 的命题、reduced-cost 符号、退化处理和精确 continuation 门槛见 [PARAMETRIC_FORMULATION.md](PARAMETRIC_FORMULATION.md)。

代码直接复用相邻的 `../chp_energy/` 的案例、物理 UC、exact DAG-CHP 和自调度求解器，不复制第二套市场模型。

## 可运行入口

在本目录执行（数值求解使用 COPT 8，经全局 `gurobi_compat` 垫片复用已有模型）：

```powershell
python run_pricing_diagnostics.py --case 6 --scenario C3 --T 24 --segments 3 --dual-audit --include-uc --out-dir results/diagnostics_C3
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization relative --epsilon 0.005 --out-dir results/full_C3_relative_eps0005
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization absolute --epsilon 0.1 --out-dir results/full_C3_absolute_eps01
python run_profit_validation.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generators 0 1 2 --beta 0 0.05 0.10 --bid-cap 0.10 --out results/profit_c3_24h_pilot_strict.csv
python run_parametric_regime_scan.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --grid 0 0.025 0.05 0.075 0.10 --out-dir results/regime_G2_direct
python run_basis_dual_audit.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --deltas 0 0.04 0.06 0.10 --out results/basis_dual_G2.json
```

诊断入口分别输出定价 LP 正流 ON/OFF 弧、活动爬坡、线路潮流与对偶，并可单独保存物理 UC；hourly 入口输出节点×价格小时×报价小时的 Jacobian、全矩阵及逐报价小时步长预警和热图，支持相对百分比及绝对美元/MWh 斜率扰动；利润入口逐点重求 UC/CHP/申报 uplift，并按不变的真实成本核算利润。`run_price_vulnerability.py` 用于整段相对或绝对加价快筛，**其分数不是 hourly VI**。利润网格的最大增益只是观察值，不是全局最优策略。

`run_parametric_regime_scan.py` 是一维绝对报价加数的 **direct-solve validation baseline**：输出各网格点、相邻区间价格/目标斜率和候选切换点。绝对加数已改写为只进入目标函数，PWL 约束矩阵固定；但当前候选仍依赖网格，不能称为 exact breakpoint 或 parametric oracle。精确 continuation 必须再处理 basis/reduced cost 和 CHP 对偶不唯一时的固定价格选择规则。

`run_basis_dual_audit.py` 用 simplex 与 barrier+crossover 检查 COPT 基状态、约化成本符号、零约化成本非基本变量、落在界上的基本变量和算法间价格差。它是 **R1.5 准入审计**，不是新的市场力指标：算法结果一致不能证明对偶唯一，存在零约化成本也不能单独证明对偶不唯一。

候选切换点前后的 Phase-1 活动弧、爬坡和线路对偶直接复用诊断入口，例如 `--bid-adder 1 0.04`。该选项只诊断报价后的定价 LP；它不与 `--include-uc` 混用，物理 UC 与利润必须走 `run_profit_validation.py` 的完整重结算。

诊断与 hourly 入口接受 `--scenario C0/C1/C2/C2N/C3`，依次检验启停、正常爬坡、无拥塞网络表述和收紧线限网络。C2N/C3 使用相同 PTDF、负荷及机组，只有线限不同；`--load-scale` 同比例缩放节点负荷，`--load-shift FROM_BUS TO_BUS FRACTION` 在每小时总负荷不变时移动节点负荷，`--warmup-initial-state` 用一日前置物理 UC 的日末状态构造正式日初态。利润入口不接受 `--scenario`；其中 `--network ptdf --congestion tight` 对应 C3。更完整的数值、局限和后续检验见 [PILOT_EVIDENCE.md](PILOT_EVIDENCE.md)，复现命令见 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)。旧文献可比性见 [REFERENCE_2021_AUDIT.md](REFERENCE_2021_AUDIT.md)。

## 检查与输出

```powershell
python -m pytest -q tests
python tests/check_chp_integration.py
```

前者不需要许可证；后者需要有效 COPT 许可证，验证默认报价兼容性、逐小时报价、绝对斜率加数、C0 的跨小时零响应、C2N/C3 拥塞配对及利润会计恒等式。利润入口要求 UC、自调度和 CHP 均证明最优，否则拒绝该网格点。输出放在 `results/`；正式论文结果应另存案例配置、COPT/垫片版本和原始表。

当前 30 节点 P0 的主结果只认 `full_case30_C3_relative_twostep_copt/`、`full_case30_C3_absolute_twostep_copt/`、`profit_case30_C3_all_dispatched_copt.csv` 和 `copt_validation_C3/`；smoke、单步长运行和局部探针保留作审计，不再作为主实验入口。

P1 主结果为 `p1_shift23to21_r020/` 和 `p1_warmup/`；`p1_shift23to21_r005_diagnostics/` 只记录“同一活动区域，按规则停止”的负结果，不追加对应 VI 或利润。

## COPT 迁移状态

代码中已无 `gurobipy` 直接导入；现有代数模型通过全局 `gurobi_compat` 调用 COPT，矩阵 CHP 路径使用 COPT 原生的矩阵变量命名、约束方向和向量取值接口。迁移回归包括：`chp_energy` 12 项测试、上述市场力集成检查、6 节点全部定价方法 smoke，以及 6/30 节点同配置的目标、节点价、结算量和 UC 数值对照。30 节点比较中 UC 目标差 $5.82\times10^{-11}$ 美元、CHP 定价目标差 $2.13\times10^{-6}$ 美元，详细判据见 [PILOT_EVIDENCE.md](PILOT_EVIDENCE.md)。COPT 的 `auto/simplex/barrier+crossover` 审计只检查算法选择敏感性，不证明对偶唯一。
