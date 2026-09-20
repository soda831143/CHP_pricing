# chp_core/ — 图论与多面体核心组件层

## 职责

本包是项目的**数学核心层**，实现两个相互独立的基础构件：

1. **DAG 建图**（`graph_builder.py`）：为单台机组枚举所有合法的 ON 区间与 OFF 弧，构建时间展开有向无环图（Time-Expanded DAG）。
2. **广义多面体封装**（`ramping_polymatroid.py`）：在本地 **`lib/thermal_unit.py`** 的 `ConditionalGPolymatroid` 上通过子类 `CHPConditionalGPolymatroid` 修正边界，暴露 `greedy_maximize` 供 `VertexOracle` 调用。

这两个组件分别服务于 **Phase 1（LP 建模）** 和 **Phase 2（极点求解）**，在数学上共同奠基于框架文档第 2 章所描述的"广义多面体双侧边界"与"扩展列式等价性"理论。

---

## `graph_builder.py` — 时间展开 DAG 构建引擎

### 数学背景（对应框架第 3.1 节）

DAG 是整个原空间 LP 的骨架。其节点和边的含义如下：

**节点**：`t ∈ {0, 1, ..., T}` 表示"机组在时段 `t` 之前处于 OFF 状态"。
- 节点 `0`：源节点（初始状态：所有机组在 `t=0` 前关机）
- 节点 `T`：汇节点（调度期末）

**ON 弧** `e = (a, b+1)`：机组在全局区间 `[a, b]` 内持续运行。
- 携带变量：`z_{i,e} ∈ [0,1]`（流量）+ `v_{i,e,τ}`（差分出力，每时段一个自由变量）
- 携带成本：`C_fix_e = C_SU + duration × C_NL + 1_{b<T-1} C_SD`
- 合法条件：`duration ≥ MUT`，且前后停机空间满足 MDT

**OFF 弧** `(t1, t2)`：机组在区间 `[t1, t2-1]` 内持续关机。
- 携带变量：`z_{off} ∈ [0,1]`，无出力，无可变成本
- 合法条件：`t2 - t1 ≥ MDT`（或起/止于调度边界）

**图的物理解释**：流量守恒方程确保对每台机组在任意时刻，"流入某节点的总概率权重 = 流出该节点的总概率权重"，源节点流出总量 = 1（某种意义上的概率归一化），这正是框架文档定理 3 中 `M_sys` 的核心结构。

### 核心类

**`OnInterval`**（`frozen dataclass`）
- 字段：`a`（起始）、`b`（结束）、`c_fix`（固定成本）
- 属性：`node_from = a`，`node_to = b+1`，`duration`

**`OffArc`**（`frozen dataclass`）
- 字段：`t_from`、`t_to`

**`GeneratorDAG`**（`dataclass`）
- 汇总字段：`params`、`on_intervals`、`off_arcs`
- 统计属性：`n_on`、`n_off`、`n_v_vars`（所有 ON 弧差分变量总数）

**`DAGBuilder`**（静态工厂类）

```python
dag = DAGBuilder.build(params: GeneratorParams) -> GeneratorDAG
```

内部方法：
- `_enumerate_on_intervals`：按 MUT、MDT 过滤，输出所有合法 ON 区间
- `_enumerate_off_arcs`：枚举 ON 弧节点集合之间满足 MDT 的 OFF 弧

### C_fix 的完整定义（与 VertexOracle 会计口径对齐）

```python
C_fix_e = C_SU + duration × C_NL + (C_SD if b < T-1 else 0)
```

`C_SD`（停机成本）归入 ON 区间成本，而非单独挂在 OFF 弧上。若 ON 区间在
调度窗口内结束（`b < T-1`），表示发生停机事件，收取 `C_SD` 并施加
shutdown-ramp；若区间延伸至最后一个时段（`b = T-1`），表示窗口结束时
机组仍可在线，不强制停机、不收 `C_SD`、也不施加 shutdown-ramp。
这与 `ScheduleRunMILP`、`PrimalCHPLP` 和 `VertexOracle` 的会计口径一致。

---

## `ramping_polymatroid.py` — 爬坡广义多面体封装

### 数学背景（对应框架第 2.1 节 + 第 4.1 节）

根据框架文档第 2.1 节，火电机组爬坡过程中的差分变量 `v` 所属的可行域，在数学上严格等价于一个由**次模上界 `f(S)`** 和**超模下界 `g(S)`** 共同定义的广义多面体 `Q(f, g)`：

```
g(S) ≤ x(S) ≤ f(S),  ∀ S ⊆ {0,...,n-1}
```

其中 `f(S)` 对应从图源点到子集 `S` 的最小容量割（天然次模），`g(S)` 对应超模下界（托底最小出力和向下爬坡限制）。

Phase 2 在给定 `λ*` 后，需要在该广义多面体上求解：
```
max  w^T v,   v ∈ Q(f, g)
```
这是广义多面体上的线性优化问题，最优解必然落在整数物理极点上（框架定理 2 + 定理 3）。

### 实现策略：子类修正 + 复用核心

**关键工程决策**：`RampingPolymatroid` 通过 `CHPConditionalGPolymatroid`（`ConditionalGPolymatroid` 的子类）来修正两处边界，然后委托给已验证的 `greedy_maximize` 方法。

```python
class CHPConditionalGPolymatroid(ConditionalGPolymatroid):
    def _build_v_bounds(self):
        u_min, u_max = super()._build_v_bounds()
        u_max[0] = self._SU_ramp   # 修正点 1：只改 τ=0，保留其他时段的 R_up
        return u_min, u_max

    def _build_prefix_bounds(self):
        x_min, x_max = super()._build_prefix_bounds()
        if self._include_shutdown:
            x_max[self._n - 1] = min(x_max[self._n - 1], self._SD_ramp)
            x_min[self._n - 1] = min(x_min[self._n - 1], x_max[self._n - 1])
        return x_min, x_max

class RampingPolymatroid:
    def __init__(self, params: GeneratorParams, a: int, b: int, include_shutdown=True):
        self._gpoly = CHPConditionalGPolymatroid(
            tp, a, b, SU_ramp=params.SU_ramp, SD_ramp=params.SD_ramp,
            include_shutdown=include_shutdown
        )
```

### 两处修正的数学必要性

**修正点 1：SU_ramp 只约束启动时段 τ=0**

- `u_max[0] = SU_ramp`（启动时段）；`u_max[τ] = R_up`（τ > 0，正常运行，不变）
- 对应 Phase 1 透视约束 1：`v_0 ≤ z·SU_ramp`
- **错误做法**（修正前）：全局用 `SU_ramp` 替换 `R_up`，导致正常运行段爬坡能力被错误限制

**修正点 2：SD_ramp 仅在区间后发生停机时约束末尾总出力 x_max[n-1]**

- `include_shutdown=True` 时，`x_max[n-1] = min(x_max[n-1], SD_ramp)` ← 对应 Phase 1 透视约束 4
- `include_shutdown=False` 时，区间延伸到调度末端，不施加 shutdown-ramp。
- **错误做法**（原 `ConditionalGPolymatroid`）：`x_max[n-1] = min(..., R_down)`，比 Phase 1 更严苛，导致极点落在凸包内部而非边界，收益被低估
- `GeneratorParams.__post_init__` 只保证 `SD_ramp ≥ P_min`，避免停机前最后在线时段与最小出力矛盾；`SD_ramp` 不应被理解为全局下爬坡率。

### 贪心算法：b* 机制（关键理论）

`greedy_maximize(w)` 底层使用 **`b*` 算法（Extended Base Polyhedron）**。该算法通过引入**哑元 `t*`（权重 = 0）**将广义多面体转化为标准基多面体，然后执行 Edmonds 贪心：

- **正权重 `w_k > 0`**：分配方向贴合**次模上界 `f`**（最大化正向贡献）
- **零/负权重 `w_k ≤ 0`**：分配方向贴合**超模下界 `g`**（最小化负向惩罚）

整个过程集合 `S` 单向从 `∅` 增长，正确处理正负混合权重，无需手动实现双向分支逻辑。

**为何不用框架文档中给出的双向贪心伪代码**：框架文档 4.1 节中展示的"负权重从全集反向删减"实现存在理论偏差（"全集 `B`"的定义不精确），已在专家审查中被指出。直接复用底层已验证的 `b*` 实现是正确且唯一稳妥的方案。

### 接口说明

```python
poly = RampingPolymatroid(params, a=3, b=7, include_shutdown=True)
w = np.array([...])  # Abel 变换后的 v 空间目标系数（后缀和）
v_star = poly.greedy_maximize(w)  # 最优差分出力 (b-a+1,)
p_star = np.cumsum(v_star)        # 还原绝对出力
```

### SU_ramp 的处理（勿与「全局替换 R_up」混淆）

- **正确做法**（当前代码）：在 `CHPConditionalGPolymatroid._build_v_bounds` 中仅令 **`u_max[0] = SU_ramp`**，其余时段 **`u_max[τ] = R_up`**，与 Phase 1 透视约束 `v_0 ≤ z·SU_ramp`、管内 `v_τ ≤ z·R_up` 一致。
- **错误做法**：把整个机组的 `R_up` 全局改成 `SU_ramp`，会错误限制正常爬坡。

---

## 与框架文档的对应关系

| 代码组件 | 框架文档节号 | 对应理论 |
|----------|------------|---------|
| `DAGBuilder.build()` | § 3.1 | 有向无环图 `G_i = (V_i, E_i)` 的构建 |
| `OnInterval.c_fix` | § 3.1 | `C_fix_e = C_SU + C_SD + duration × C_NL` |
| `RampingPolymatroid.greedy_maximize` | § 4.1 | Edmonds 广义多面体贪心法则 + Bach (2013) b* 算法 |
| `f_eval(S)` | § 2.1 | 次模上界（爬坡容量最小割） |
| `g_eval(S)` | § 2.1 | 超模下界（向下爬坡 + P_min 托底） |
