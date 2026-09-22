# chp_solver/ — 优化求解器层

## 职责

实现双轨制的三个求解引擎：

| 文件 | 轨道 | 核心输出 |
|------|------|---------|
| `schedule_run.py` | Track 1 | `p_dispatch (N×T)`, `u_dispatch (N×T)`, `obj_val` |
| `chp_master_lp.py` | Track 2 Phase 1 | `lmp_matrix (N_bus×T)`, `lp_obj`；多节点另存 `_ptdf_alpha`, `_ptdf_beta_` |
| `vertex_oracle.py` | Track 2 Phase 2 | `u*`, `p*`, `max_profit`, `compute_uplift` |

均通过 `GeneratorParams` + `NetworkModel`（或 `np.ndarray` 自动包装为单节点）取数。

---

## `schedule_run.py` — UC MILP（Track 1）

### 模型要点

- **单节点与多节点**均使用**全局功率平衡**：`Σ_i p[i,t] = sys_demand[t]`。
- **多节点**追加 **PTDF 线路约束**：`rhs_neg ≤ PTDF_Gen @ p_{·,t} ≤ rhs_pos`（与 `PTDFNetwork.line_rhs()` 一致）。
- **成本**：PWL 段变量 `x` + `C_NL·u + C_SU·su + C_SD·sd`，与定价 LP / Oracle 口径一致。

### 变量（摘要）

`u, su, sd` 为二进制；`p` 连续；`x[i,k,t]` 为分段填充。

### COPT（经 `gurobi_compat`）

```text
OutputFlag = 0
MIPGap     = 1e-6
```

### 输出

```python
p_dispatch, u_dispatch, obj_val = ScheduleRunMILP(generators, network).solve()
```

---

## `chp_master_lp.py` — 原空间凸包 LP（Phase 1）

### 变量布局

`x = [z_on | z_off | q_vars | (PWL 时) cvar_vars | (可选) p_vars]`；`q_{e,t}` 是 ON 弧的绝对出力（Yu/Pan interval `p` 坐标），底层 LP 不再设差分出力 `v` 决策变量。

### 等式约束（行块顺序）

1. DAG **内部节点**流量守恒（每台机、每个 `t=1…T−1`）
2. **源点**流出总和 = 1（每台机）
3. **全局功率平衡**（`T` 行）：对偶为能量分量 `λ_t`

### 不等式

- 四类 **ON arc 透视约束**：
  - 启动上限：`q_0 <= SU_ramp*z_e`；初始在线弧改按 `initial_power ± R_up/down` 约束
  - 正常爬坡：`-R_down*z_e <= q_tau−q_(tau−1) <= R_up*z_e`
  - 容量：`P_min*z_e <= q_tau <= P_max*z_e`
  - 停机上限：仅当 ON arc 在日内结束（`b<T-1`）时加入 `q_last <= SD_ramp*z_e`；在线到末时不强制关机
- **PWL**：上镜图 `cvar ≥ slope·q + (b−s·Pmin)·z`
- **多节点**：PTDF 上下界（排在不等式矩阵尾部，便于提取对偶）

### 目标

- 单段：`C_fix·z + C_var·Σ_t(q_t−P_min·z)`
- 分段：`C_fix·z + Σ cvar`

### COPT 与对偶

- `Method=2`, `Crossover=0`
- 平衡行固定为 `Σ_g p[g,t] = D[t]`。原始 RHS 对偶直接为能量价 `raw_energy_dual`；`raw_nodal_price` 用未经裁剪的线路对偶经 PTDF 变换构造，供参数价格分析。旧 `energy_price` / `lmp_matrix` 仍保留历史清理口径。
- **多节点 LMP**：代码采用 PTDF reduced form，不显式建立 `N_bus×T` 个节点平衡等式；节点价格由 `lmp[n,t] = λ_t + Σ_l PTDF[l,n](α_{l,t} − β_{l,t})` 恢复，其中 `α,β` 为 PTDF 两行不等式的 `Pi`（≤0）。这与显式 DC-OPF 节点平衡对偶等价
- 求解后赋值 **`_ptdf_alpha`, `_ptdf_beta_`**（形状 `(N_line,T)`），供 `benchmarks/comparison_runner` 计算 **FTR 成本**（论文公式 34 第二行）

---

## `vertex_oracle.py` — 极点神谕（Phase 2）

### 单段线性

- Abel 权重 → `RampingPolymatroid.greedy_maximize` → `cumsum(v)` → 区间利润 `W_e`
- 外层 `DPShortestPath`（`lib/dp_shortest_path.py`）选最优 ON/OFF 路径

### 分段线性（PWL）

- 区间内用 **COPT 凸 LP** 最大化 `Σ_t (λ_t p_t − PWL(p_t))`  subject to 爬坡多面体（与 Groenevelt 块级贪心等价）

### `compute_uplift`

与 MILP 一致：`revenue − PWL/var − C_NL·Σu − C_SU·#su − C_SD·#sd`；`uplift = max(0, max_profit − dispatch_profit)`。

### 数值与时间统计

- 近零 `max_profit` 时强制全天 OFF 轨迹，避免 DP 泄漏非零 `p*`
- `run_experiments.py` 的 `method_time` 对本文方法取 `PrimalCHPLP.solve()` 的 `chp_time`；`oracle_time` 单独记录 Phase 2 结算时间。论文报告速度时应同时说明这两个口径

---

## 与框架文档的对应（简表）

| 代码 | 理论 |
|------|------|
| `ScheduleRunMILP` | 双轨制 Track 1 |
| `PrimalCHPLP` 等式/不等式 | DAG + 透视 + （可选）PWL + PTDF |
| `PrimalCHPLP` 对偶后处理 | 多节点 CHP-LMP |
| `VertexOracle` | Phase 2 极点 + Uplift |
