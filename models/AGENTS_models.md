# models/ — 物理参数与网络拓扑层

## 职责

1. **`generator.py`**：`GeneratorParams`（单段 / 分段线性成本）及 `load_all_case6ww_generators` 等工厂函数。
2. **`network.py`**：`NetworkModel` 抽象类 + **`SingleNodeNetwork`** + **`PTDFNetwork`**（多节点直流 PTDF 已实现，非占位）。

本层无优化算法，仅数据与接口。

---

## `generator.py`

### `GeneratorParams`（摘要）

| 字段 | 含义 |
|------|------|
| `P_max, P_min, R_up, R_down, SU_ramp, SD_ramp` | MW 或 MW/h |
| `T_on_min, T_off_min` | MUT/MDT |
| `cost_var, cost_su, cost_sd, cost_nl` | 与 MILP/LP 一致；`cost_nl` 常取 `C(P_min)` |
| `pwl_slopes, pwl_widths` | 可选；非空则 `is_single_segment == False` |

**`__post_init__`**：`SD_ramp = max(SD_ramp, P_min)`，`SU_ramp = max(SU_ramp, P_min)`，避免透视约束矛盾。

**工厂**：`load_all_case6ww_generators(T)` 读 `data/cases/case_6ww.py` 中 `build_case_6ww()`，无需外部 engine。

---

## `network.py`

### 抽象接口 `NetworkModel`

| 属性/方法 | 说明 |
|-----------|------|
| `T`, `N_bus` | 时段数、节点数 |
| `demand` | `(N_bus, T)` MW |
| `sys_demand` | `(T,)` 各时段总负荷 |
| `is_single_node` | `N_bus == 1` |
| `gen_bus_idx(i)` | 机组 `i` 的 **0-based** 节点索引 |
| `F_max`, `line_rhs()` | 仅 `PTDFNetwork`：容量 `(N_line,)` 与 PTDF 右端 `(N_line,T)×2` |

### `SingleNodeNetwork`

- `demand` 可为 `(T,)` 或 `(1,T)`；`sys_demand` 即总负荷。
- 所有机组视为同一节点：`gen_bus_idx(i)=0`。

### `PTDFNetwork`

- **线路潮流**（仅发电机注入形式）：  
  `f_{l,t} = (PTDF_Gen @ p)_l,t − (PTDF @ demand)_l,t`  
  约束：`-F_max ≤ f ≤ F_max` → 对 `p` 的线性不等式由 `line_rhs()` 给出右端。
- **`PTDF_Gen`**：`(N_line, N_gen)`，可由 `PTDF[:, gen_bus_map]` 生成。
- **节点价格口径**：本项目采用 PTDF reduced form。优化模型中保留全系统平衡，
  节点注入位置通过 `PTDF_Gen` 与 `PTDF @ demand` 进入线路约束；定价后由
  系统平衡对偶和线路容量对偶恢复 nodal LMP。这与显式 DC-OPF 节点平衡
  对偶等价，但代码中不是直接建立 `N_bus × T` 个节点平衡约束。
- **工厂**：
  - `build_ptdf_network_from_case6ww(T, congestion=...)`
  - `build_ptdf_network_from_case30ww(T, congestion=...)`
  - `build_ptdf_network_from_case118ww(T, congestion=...)`
  - `fmax_scale` 非空时覆盖 `congestion`，直接按原始 `rateA` 缩放。

### 拥塞场景

| case | `tight` | `moderate` | `relaxed` |
|------|---------|------------|-----------|
| 6-bus | `0.8 × rateA`，可行且产生节点价差 | `1.0 × rateA` | 2000 MW |
| 30-bus | `1.3 × rateA`，接近可行边界 | `2.0 × rateA` | 2000 MW |
| 118-bus | `case_118ww_branch_map` 中关键线路限值 | `1.5 × tight` | 5000 MW |

这些场景只用于控制网络拥塞程度，不改变机组成本或 UC 约束。主论文对比中，
`relaxed` 用于无阻塞退化验证，`tight` 用于观察拥塞/FTR 项和节点价格变化。

### 用法

```python
from models.network import (
    build_single_node_from_case6ww,
    build_ptdf_network_from_case6ww,
)

net = build_single_node_from_case6ww(T=24)
# 或
net = build_ptdf_network_from_case6ww(T=24)

from chp_solver.schedule_run import ScheduleRunMILP
from chp_solver.chp_master_lp import PrimalCHPLP
milp = ScheduleRunMILP(generators, net)
lp   = PrimalCHPLP(generators, net)
```

兼容旧写法：`ScheduleRunMILP(gens, demand_ndarray)` 会自动包装为 `SingleNodeNetwork`。

---

## 与框架文档的对应

机组参数对应框架 §3.1；`SU_ramp` 对应透视约束 1 的上界（**非**全程用 `SU_ramp` 替换 `R_up`，见 `chp_core` 文档）。

网络层对应 **全局平衡 + PTDF** 的 DC 近似；更大系统只需构造同类 `PTDFNetwork` 实例。
