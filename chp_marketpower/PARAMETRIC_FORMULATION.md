# 一维报价参数化 CHP：理论规格、审计门槛与实施路线

## 1. 研究问题与边界

本文不再把“用图表示单机凸包”作为贡献。`chp_energy` 已经给出 interval/DAG 扩展表示和系统 CHP 定价 LP；本分支要回答的是：当机组统一抬高边际报价时，CHP 节点价在什么参数区间内按同一规律变化，何时发生机制切换，以及这种价格影响是否会变成按真实成本核算的额外利润。

第一阶段只研究一个战略机组、一个标量参数和固定网络/负荷。容量持留、合谋、二维以上参数、神经网络以及 IEEE-118 都不进入当前实现。这样可以先把“导数—断点—活动机制—利润”这条因果链做严谨，再决定是否需要更复杂的 oracle。

## 2. 报价参数与等价重写

对战略机组 \(g\) 的全部时段和全部 PWL 段施加同一个绝对边际报价加数 \(\delta\)：

\[
\widehat C_g(q;\delta)=C_g(q)+\delta q,
\qquad \delta\in[\underline\delta,\overline\delta].
\]

若基准 PWL 成本为

\[
C_g(q)=\max_k\{s_{gk}q+b_{gk}\},
\]

则

\[
\max_k\{(s_{gk}+\delta)q+b_{gk}\}
=\delta q+\max_k\{s_{gk}q+b_{gk}\}.
\]

因此 \(\delta q\) 可以直接加入目标函数，而不改动 PWL 上镜图、DAG 流守恒、爬坡透视约束、系统平衡或 PTDF 线路约束。代码中的参数化定价问题具有固定可行域：

\[
P(\delta):\quad
\min_x\ (c^0+\delta d_g)^\top x
\quad\text{s.t.}\quad
Ax=b,\;Gx\le h,\;\ell\le x\le u.
\tag{1}
\]

其中 \(d_g^\top x\) 是战略机组在 CHP 扩展变量下的总报价出力。`chp_energy/chp_solver/chp_master_lp.py` 负责这一 objective-only 重写；矩阵不变测试负责防止以后误把 \(\delta\) 放回约束系数。

这里选择绝对加数而不是相对乘数，是为了固定式 (1) 的矩阵。相对乘数仍可作为经济稳健性口径，但它同时缩放 PWL 斜率和截距，不应冒充当前的一维固定矩阵参数 LP。

## 3. 固定基区间内成立的结论

把式 (1) 通过松弛变量和界移位写成标准形式

\[
\min_z\ (\bar c^0+\delta\bar d)^\top z,
\qquad \bar A z=\bar b,\quad z\ge0.
\tag{2}
\]

在参数点 \(\delta_0\) 选择一个非奇异最优基 \(B\)，并把非基本列记为 \(N\)。只要该基在一个开区间 \(I_B\) 内保持原始可行和对偶可行，就有

\[
z_B(\delta)=B^{-1}\bar b,
\tag{3}
\]

\[
\pi_B(\delta)
=B^{-\top}(\bar c_B^0+\delta\bar d_B),
\tag{4}
\]

\[
r_N(\delta)
=\bar c_N^0+\delta\bar d_N-N^\top\pi_B(\delta).
\tag{5}
\]

**命题 1（固定基下的仿射结构）。** 若 RHS 和约束矩阵与 \(\delta\) 无关，并且一个非退化最优基 \(B\) 在开区间 \(I_B\) 内不变，则：

1. 原始基本解和 CHP 出力在 \(I_B\) 内不随 \(\delta\) 变化；
2. 等式/活动不等式对偶以及由其恢复的 CHP 节点价关于 \(\delta\) 仿射；
3. 最优目标值关于 \(\delta\) 仿射，且
   \[
   \frac{dv}{d\delta}=\bar d_B^\top z_B=d_g^\top x^*;
   \]
4. 区间端点由某个非基本变量的对偶可行性首次失效给出。

**证明。** 式 (3) 只含固定的 \(B\) 和 \(\bar b\)，故原始基本解为常数。式 (4) 是 \(\delta\) 的仿射函数；节点价是相关对偶的固定线性变换，因此也仿射。把常数 \(z_B\) 代入目标函数即可得到目标值及其导数。最后，原始可行性在固定 RHS 下不变，故离开当前最优基区间只能由式 (5) 的 reduced cost 到达相应界状态的临界值引起。证毕。

这条命题解释了一个容易忽视的现象：**同一 regime 内出力可以不变，但价格仍可随报价变化。** 因而本文把两种潜在市场力渠道分开：

- 区间内价格杠杆：\(\partial\lambda/\partial\delta\)，描述固定 regime 内价格如何被推动；
- regime 切换杠杆：距离最近断点的 \(\Delta\delta\) 以及断点两侧的活动机制变化，描述多小的报价变化会改变最优基或价格规律。

两者均不能替代完整重结算后的真实利润增量。

## 4. 有界变量的正确 reduced-cost 条件

当前 CHP LP 含下界变量、上界变量和自由的 interval 出力变量，不能假设所有非基本变量都位于零下界。对最小化问题，采用 COPT 的基状态时应分别检查：

| 非基本状态 | 当前基保持对偶可行的条件 |
|---|---|
| 位于下界 | \(r_j(\delta)\ge0\) |
| 位于上界 | \(r_j(\delta)\le0\) |
| 自由/超基本 | \(r_j(\delta)=0\) |
| 固定变量 | 不能仅靠一个 reduced-cost 符号判断，需保留上下界乘子解释 |

令

\[
r_j(\delta_0+\eta)=r_j^0+\eta\dot r_j.
\]

向参数增大方向推进时，下界非基本变量仅在 \(\dot r_j<0\) 时产生候选步长 \(-r_j^0/\dot r_j\)；上界非基本变量仅在 \(\dot r_j>0\) 时产生候选步长。取所有严格正候选中的最小值，才是当前基的下一个候选端点。自由/超基本变量若已处于零 reduced cost，说明简单的单基 continuation 可能只有零长度，需要先处理退化，而不能硬选一个 pivot。

## 5. 退化与价格不唯一：先审计，后选择规则

CHP 扩展表示存在大量等价弧流分解，退化是结构性可能，不是异常。以下证据必须区分：

1. 非基本变量 reduced cost 为零，说明存在替代最优基风险，但**单独不能证明对偶不唯一**；
2. 基本变量落在界上，说明原始退化；
3. simplex 与 barrier+crossover 的目标一致而节点价不同，才是当前求解器价格选择依赖算法的直接数值证据；
4. 两种算法价格一致仍只是必要检查，不构成唯一性证明。

`run_basis_dual_audit.py` 在 \(\delta=0,0.04,0.06,0.10\) 上报告上述前三类信号，并验证下界、上界和超基本变量的 reduced-cost 符号。决策规则如下：

- 若差异只出现在孤立断点：报告左右极限，并把断点价格视为集合值；不为一个零测集点发明 canonical price；
- 若开区间内部的算法价格存在实质差异：暂停 price continuation，针对论文实际使用的节点—小时在对偶最优面上求价格上下界，或预先声明一个可复现的词典序二级选择；
- 若开区间内部价格稳定、只有替代基：可以继续追踪目标/活动 regime，但每个解析区间仍需由 direct COPT 随机点验证。

因此当前代码没有实现一个武断的 canonical dual。是否需要该规则由审计结果决定。

## 6. Solver-assisted continuation，而非自写单纯形法

精确一维 oracle 的目标输出是按 \(\delta\) 排序的区间表：

\[
[\delta_k,\delta_{k+1}],\quad
v(\delta)=a_k^v+b_k^v\delta,\quad
\lambda(\delta)=a_k^\lambda+b_k^\lambda\delta,
\]

并附带当前基签名、活动线路/爬坡/interval 机制以及端点审计状态。最小实施路线是：

1. 在 \(\delta_k+\varepsilon\) 用 COPT simplex/crossover 取得一个最优基；
2. 用基矩阵线性方程计算对偶斜率和每个 reduced cost 的斜率；
3. 按第 4 节的状态条件求最近正候选步长；
4. 在候选端点和端点右侧 \(\varepsilon\) 重新调用 COPT，让成熟求解器选择新基；
5. 若遇到零步长、多个同时入界或算法价格分歧，标记退化事件并按第 5 节处理；
6. 每个区间抽取至少一个内部点，以 direct solve 核对目标、节点价和活动机制。

这里不实现 pivot、anti-cycling 或完整参数单纯形法。COPT 负责稳定求解和换基；本项目只负责解析计算下一断点、组织区间及验证。这是当前研究问题需要的最小算法增量。

## 7. 实验链条与可证伪门槛

| 阶段 | 目的 | 输入/代码 | 必须通过的门槛 |
|---|---|---|---|
| R1 参数合法性 | 保证 \(\delta\) 只进目标 | `PrimalCHPLP`、矩阵不变测试 | \(A,G,b,h,\ell,u\) 逐元素不变；定价等价 |
| R1.5 基/对偶审计 | 判断 exact price continuation 是否有定义 | `run_basis_dual_audit.py` | reduced-cost 符号正确；量化退化；报告算法价格差异 |
| R2 direct baseline | 定位候选区间并提供真值 | `run_parametric_regime_scan.py` | 只称网格候选，不称 exact breakpoint |
| R2 exact continuation | 计算并认证一维临界区间 | 待审计通过后实现 | 每区间随机点的目标/所选价格与 direct COPT 一致 |
| R3 机制解释 | 把断点映射为经济/物理事件 | `run_pricing_diagnostics.py` | 线路、爬坡、interval 或 PWL 活动集有可复核变化 |
| R4 利润验证 | 区分 price leverage 与 exercisable power | `run_profit_validation.py` | 按真实成本，且 UC/CHP/自调度均为最优 |
| R5 计算价值 | 判断 oracle 是结构贡献还是加速贡献 | cold/warm solve 与 query 计时 | 报告 offline 时间、存储、query 时间及 break-even 查询数 |

任何一个关键命题都允许被否证：若区间数量爆炸、价格在区间内部广泛不唯一、断点不能映射到稳定机制，或 offline 构造无法由合理查询量摊销，就不声称“快速精确价格 oracle”。此时仍可保留有证据支持的较弱结论，例如报价—价格的局部集合值结构或反直觉的利润背离。

## 8. 当前状态与下一步

目前 R1 已完成，R2 的网格真值入口已完成，R1.5 的四点 COPT 审计已运行。在 6 节点 G2、\(\delta\in\{0,0.04,0.06,0.10\}\) 上，simplex 与 barrier+crossover 的最大节点价差均不超过 \(7.45\times10^{-13}\)，目标差均不超过 \(6.55\times10^{-11}\)，reduced-cost 状态符号违规数均为 0；但每次求解有 278–611 个零 reduced-cost 非基本变量和 3993–5268 个落在界上的基本变量。这说明四个检查点的**价格选择数值稳定但基高度退化**：目前没有证据要求立即设计 canonical price，却必须让 COPT 辅助处理换基，不能假设唯一非退化基。

下一步顺序固定为：

1. 实现当前基的对偶/reduced-cost 斜率与精确下一候选断点；
2. 在断点右侧调用 COPT 选取新基，不自写 pivot 或 anti-cycling；
3. 用区间内部随机 direct solve 验证目标和所选价格；
4. 用 \(\delta\approx0.05\) 候选两侧的现有诊断解释线路、爬坡、PWL 和 interval 机制；
5. 最后把 regime 指标与已有真实利润表连接。

在精确区间通过 direct-solve 验证前，不增加 local arc oracle、二维参数、学习模型或新大系统实验。
