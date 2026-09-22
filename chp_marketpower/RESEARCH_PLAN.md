# 网络约束凸包定价中的报价影响、时空传播与可获利市场力：研究方案（工作稿）

> 研究定位：本文不是再提出一个 CHP 求解器，而是利用已完成的 exact DAG-CHP 求解能力，研究**报价如何改变凸包价格、影响如何传播、价格影响能否变成真实利润**。本文先以火电机组的可变成本报价为可控切口；灵活性资源、容量持留、合谋和随机性属于后续拓展，不把面上项目的所有目标压入同一篇论文。

> 2026-09-22 执行门槛：底层 CHP LP 已改用 Yu/Pan 式绝对 interval 出力 \(q\)（即区间 \(p\) 坐标），不再把差分/爬坡量 \(v\) 设为决策变量。这是坐标化简，不能作为论文创新。R2 的 6 节点 G2 五段与最窄区间现已通过三档 COPT 容差下各 15 个内部点的数值检验，可按约 85% 的数值原型看待，仍非数学证明。下一问题是五段价值区间对应多少真正价格区间；本轮不扩 30 节点、不扩 \(\delta\)、不做新利润实验。

## 0. 2026-09-20 导师意见后的两篇论文分工

当前工作不推倒重来，而是把已经混在一起的“表示、算法和应用”拆开。

| 论文线 | 核心问题 | 现有成果如何处理 | 当前代码归属 |
|---|---|---|---|
| CHP 会议稿 | 既有 interval/DAG-CHP 实验中是否存在可重复、可解释的反直觉现象 | 弱化“新 formulation”主张，冻结方法，不追加大规模算法框架；只从现有结果筛选一个有物理解释的 counter-intuitive finding，面向 PES General Meeting 或 CDC | `../chp_energy` 的 `master` 检查点 `49b26de` |
| Market-power 新稿 | 网络约束、多时段 CHP 中，局部价格影响何时切换 regime，以及它为何不等于可获利市场力 | 继续复用已经完成的 Jacobian、利润会计、活动集诊断和 P1 holdout；加入一维 parametric price-impact regime，而不是再发明 network-flow CHP | 分支 `research/market-power-parametric-regimes` |

导师所说的 oracle 可分为两层，不能混为一谈：

1. **local value oracle**：对某个 ON interval、arc 或离散状态，给定连续参数后返回条件最小成本；它回答 DP/network-flow 的 edge cost 如何快速查询。
2. **system-level value/price oracle**：先对整个 CHP LP 重构与基选择无关的系统最优值区间，再在这些区间内部识别节点价格子区间；第二层才直接回答 market power 的价格传播问题。

本稿先做第二层。原因是当前 exact CHP、节点价、利润重结算和 finite-difference baseline 已经齐备，可以用最少新代码检验核心命题。只有当系统级 critical-region 枚举确实过重时，才回到导师提出的 local oracle + DAG/master 分解。绝不机械地为所有 $2^{G\times T}$ commitment pattern 建 oracle；已有 interval DAG 继续负责压缩离散轨迹，parametric region 负责压缩重复连续求解。

### 与最近邻工作的安全边界

- Pan/Yu 一线已经给出 interval/network-flow extended representation；因此“把 CHP 写成图”不是新贡献。
- Sun–Wu (2021) 已经研究多时段报价到 CHP 的 Jacobian/VI；因此“计算 derivative 或把 $T\times T$ 扩成 $N_BT\times T$”不能单独成为主贡献。
- Sun–Gu–Wu (2020) 已经用策略报价后的利润定义 CHP 市场力；因此“第一次研究利润型 CHP market power”也不能宣称。
- 本稿的候选贡献是：**network-constrained exact CHP 的 price-impact regimes、regime 阈值与 congestion/ramping/interval 切换的对应，以及 price leverage 与真实可获利润的系统性分离。**

### 第一维参数为什么选绝对报价加数

导师用需求 $D$ 说明 RHS parametric LP；market power 更自然的参数是报价。当前相对乘数在 max-of-lines PWL epigraph 中会改变约束矩阵，不适合作为第一版固定矩阵问题；这只是当前表示的选择，不代表相对参数在增量段表示下不可能 objective-only。第一版对同一机组、全部 PWL 段统一增加绝对边际报价 $\delta_g$。因为变动成本定义在高于最小出力的电量上，正确新增项是：

$$
\widehat C_g(p,u;\delta_g)=C_g(p,u)+\delta_g\sum_t(p_{g,t}-P_g^{\min}u_{g,t}).
$$

exact CHP 可写为

$$
\min_x\;(c^0+\delta_g d_g)^\top x
\quad\text{s.t.}\quad Ax=b,\;Gx\le h,
$$

其中 $d_g^Tx=\sum_t(p_{g,t}-P_g^{\min}u^{\rm ch}_{g,t})$，且 $A,G,b,h$ 与 $\delta_g$ 无关。该接口已在 `../chp_energy/chp_solver/chp_master_lp.py` 实现；回归不仅检查矩阵不变，还检查目标方向、凸化暴露和物理 UC 段填充三者恒等。全局分析先用最优值函数的凹分段线性结构，避免把高度退化 LP 中的任意基切换误当成经济断点。

### 分阶段路线与停止门槛

| 阶段 | 目的 | 最小产出 | Go / No-Go |
|---|---|---|---|
| R0 最近邻对齐 | 防止再次与 Sun–Wu/Yu 撞车 | `REFERENCE_2021_AUDIT.md`；能取得原始需求时复现 pool/3-period，否则只做定性退化关系 | 说清楚 derivative/VI、profit 和 graph representation 已有到什么程度 |
| R1 参数接口 | 建立真正固定 $A,b,G,h$ 的一维 cost parameter | objective-only 绝对报价加数及暴露恒等式 | 目标方向等于 $p-P_{\min}u^{\rm ch}$；物理 UC 段填充一致；矩阵不变 |
| R1.5 基/对偶审计 | 判断 price continuation 是否有良好定义 | `PARAMETRIC_FORMULATION.md`、`run_basis_dual_audit.py` | 区分下界/上界/自由变量的 reduced-cost 条件；量化退化和算法价格差异 |
| R2 价值 regime | 从离散网格升级到全局价值区间 | 最优面左右导数、支撑线递归、确定性内部验证与三档 COPT 容差 | 每区间 25%/50%/75% 查询的值与斜率均和 direct COPT 一致，窄段在容差变化下保留 |
| R3 价格子区间 | 在已数值验证价值区间内识别价格规律 | solver-assisted 基候选、全节点原始价格直接查询、相同价格线合并 | 不把基事件冒充价格/经济事件；退化价格有明确处理规则 |
| R4 机制解释 | 解释 breakpoint 而非只画折线 | 切换前后线路对偶、活动爬坡、ON/OFF interval、PWL segment | 切换能稳定对应至少一种物理/定价活动集变化，或明确报告负结果 |
| R5 可获利市场力 | 区分 potential price leverage 与 exercisable market power | 复用真实成本利润重结算；比较 leverage、最近 regime 距离和利润渠道 | 能量收入、uplift、真实成本和调度渠道闭环 |
| R6 计算价值 | 回答导师“多少空间换多少时间” | cold/warm direct solve、offline construction、query time、存储和 break-even $Q^\star$ | 只有 $Q^\star$ 合理才主张加速；否则 regime 结构是主贡献 |

当前已完成 R1、R1.5 和 6 节点 G2 的 R2 数值试点。网格 baseline 曾把 $\delta=0.05$ 美元/MWh 标为候选切换，但 value oracle 发现价值断点约为 0.017679、0.018044、0.043396、0.084123；0.05 位于同一价值区间内部。三档 COPT 容差均得到五段且各有 15 个内部查询通过，最窄段保留；默认最优面目标带宽为 $10^{-10}$ 美元，压到 $10^{-11}$ 美元会让交点附近辅助 LP 不可行。首个 R3 探针在五段各取 3 个内部点、比较两种算法的完整原始价格向量，观测到至少五条局部仿射且相邻斜率不同的价格线；这不排除隐藏价格子段。下一步只在这五个外层区间内用基/reduced-cost 信息生成候选事件并在右侧重求，不预设 canonical dual，也不自写 pivot。

learning-to-optimize/神经网络不是当前任务。只有当一维 exact region 数量爆炸，或研究问题必须升到二维以上而显式枚举不可行时，才以 exact 1D oracle 作为 ground truth 考虑 learned extension。

## 1. 背景、问题和本文与已有工作的关系

常规节点电价通常在给定机组组合后定价，难以直接反映启动、停机和最小运行时间等非凸成本。CHP 将价格与机组的非凸可行域联系起来，并以最小化总 uplift 为主要设计目标。然而，**最小 uplift 并不是策略报价激励相容性证明**：机组依然可能通过申报成本改变调度、价格和结算收入。

已有工作提供了两条互补线索：

1. [Sun、Gu、Wu (2020)](../../../../primal/Market%20Power%20in%20Convex%20Hull%20Pricing.pdf)及[吴辰晔、孙健 (2021)](../../../../primal/凸包定价模式下的电力市场潜在市场力分析方法.pdf)在简化模型中研究谎报后的利润增量及其市场力指标。中文论文还给出了网络下的 6 节点数值例子，所以本文不能宣称“首次考虑 CHP 网络市场力”。其一般性理论结论建立在较强的单时段、同容量或特定策略集合假设上。
2. [Sun、Wu (2021)](../../../../primal/Temporal%20Vulnerability%20Assessment%20for%20Convex%20Hull%20Pricing.pdf)定义了按小时报价到按小时 CHP 的 $T\times T$ Jacobian，并以列范数平均构造 temporal vulnerability index。该论文的主体是简化 pool 模型，附录讨论网络推广，但尚未在完整启停、爬坡、异质机组和网络共同存在时系统解析其时空图像。[作者的科普解释](../../../../references/凸包定价-zhihu吴辰晔.pdf)也明确说明了当时为了分析而采用的开停机简化。
3. [面上项目正文，研究内容三](../../1.面上项目-正文-final.md)希望解释策略报价对 CHP、调度和 uplift 的联动，并研究多时空网络约束下的监管指标。本文可作为其中一条可检验、可逐步扩展的火电机组研究线，而非整个项目计划的替代品。

当前 `../chp_energy/` 已有 exact DAG-CHP Phase 1、物理 UC、单机自调度和 uplift 会计口径。因此本文的机会不是“现实模型从零搭建”，而是把过去分开的**价格脆弱性**与**可获利操纵**放在同一市场流程下检验。

### 一句话科学问题

> 在含启停、爬坡和网络拥塞的 exact CHP 中，一个机组某小时改变可变成本报价，价格影响会出现在哪里、持续多久；哪些价格影响能转化为按真实成本计算的额外利润？

### 候选贡献，而非事先承诺的结论

- **经济现象**：识别具有稳定证据的 CHP 跨时段或跨节点报价影响，并说明其适用条件。
- **机制解释**：用控制实验区分启停/最小开停机、连续爬坡和输电拥塞通道，而不只呈现热图。
- **监管筛查**：在旧文献 VI 的基础上，形成能够区分时间溢出和拥塞贡献的价格脆弱性描述，并检验其对利润增量的预测力。
- **计算方法（条件性）**：若数值图像稳定且重复求解成本成为瓶颈，再研究 DAG-LP 的局部解析敏感度或临界区域。没有实证加速优势时，这部分不承担主要贡献。

创新定位必须避开两种过宽说法：“首次研究 CHP 市场力”和“首次考虑网络”。更可支持的定位是**在 exact 多时段网络 CHP 下，建立从局部报价冲击到价格传播、物理调度和真实利润的可核验链条**。

## 2. 市场流程与数学定义

### 2.1 基本对象与真实/申报信息

令 $\mathcal G,\mathcal N,\mathcal T,\mathcal L$ 分别表示机组、节点、小时和线路集合。$n(g)$ 是机组 $g$ 所在节点，$D_{n,t}$ 是固定需求。机组物理轨迹 $(u_g,p_g)$ 属于可行域 $X_g$，其约束包括容量、启停、最小开停机时间、正常爬坡、启动/停机爬坡和初始状态。网络按现有 PTDF 口径满足

$$
\sum_g p_{g,t}=\sum_n D_{n,t},\qquad
-F_l\le\sum_g H_{l,n(g)}p_{g,t}-\sum_n H_{l,n}D_{n,t}\le F_l.
$$

真实成本 $C_g^{\mathrm{true}}(u_g,p_g)$ 由 startup、shutdown、no-load 和 $P_{\min}$ 以上的 PWL 可变成本组成。研究初期只让机组申报可变成本斜率：

$$
\widehat s_{g,t,k}=(1+\beta_{g,t})s_{g,k},\qquad \beta_{g,t}>-1.
$$

PWL 段宽、$P_{\min}$、物理参数及固定成本保持不变。每小时所有段斜率同倍数变化，段间截距随之调整以保持连续。因 $P_{\min}$ 处的 no-load 成本未变化，**这不是“整条总成本曲线统一加价”**；固定成本的战略申报以后单独研究。MVP-1 令 $\beta_{g,t}=\beta_g$（整台机组整日同加价），MVP-2 则只让一个 $(g,\tau)$ 非零。

为避免相同百分比冲击天然给高成本机组更大的 $\$/MWh$ 变化，正式筛查还要并行采用**绝对斜率扰动** $\widehat s_{g,t,k}=s_{g,k}+\delta_{g,t}$，其中 $\delta$ 的单位是 $\$/MWh$。它使同一机组所有 PWL 段斜率增加同一个绝对量，截距保持原值，因而整条超出 $P_{\min}$ 的曲线增加 $\delta(p-P_{\min})$，保持连续和凸性。相对 $\beta$ 适合百分比战略情景；绝对 $\delta$ 适合跨机组比较和与旧文献按绝对 bid 的 Jacobian 对齐。两种导数单位不同，不能混排。

### 2.2 两种实验模式不能混用

**模式 A：价格脆弱性。** 固定 $D,F$、其他机组申报、初始状态和物理约束，只改变一个报价参数，重新求 Phase 1 CHP。它回答“价格形成如何响应”，**不重求 UC，也不计算实际利润**。

**模式 B：战略获利验证。** 对每个候选申报，重新运行物理 UC、CHP 和规定的 uplift 结算；最后以不变的真实成本计算利润。它回答“机组是否真的能多赚”。模式 A 的结果只用于选择模式 B 的少量测试机组，不能替代模式 B。

### 2.3 物理 UC、exact CHP 与价格

给定申报成本 $\widehat C$，实际执行轨迹由现有 UC 引擎求解：

$$
(u^{\rm UC},p^{\rm UC})\in\arg\min_{(u,p)\in X(D,F)}\sum_g\widehat C_g(u_g,p_g).
\tag{1}
$$

CHP 则对每台机组的成本-出力可行集合取凸包，在相同需求与网络约束下求系统最小凸化成本：

$$
Q(\widehat C;D,F)=\min_{x_g\in\operatorname{conv}(X_g)}\sum_g\widehat C_g^{\rm ch}(x_g)
\quad\text{s.t. balance and PTDF line limits.}
\tag{2}
$$

`chp_energy` 用合法 ON/OFF interval 的 DAG flow、透视容量/爬坡约束和 PWL 上镜图实现式 (2)，而非枚举全部 UC 轨迹。系统平衡对偶给出能量分量 $\lambda^E_t$；线路约束对偶通过 PTDF 形成节点 CHP：

为使式 (1) 可直接复算，令 $u_{g,t},v_{g,t},w_{g,t}\in\{0,1\}$ 分别为开机、启动、停机，$p_{g,t}\ge0$ 为出力，$x_{g,k,t}\ge0$ 为 PWL 第 $k$ 段填充。现有 UC 的机组约束可写成（$t=1$ 的上期量取给定初始状态/初始出力）：

$$
\begin{aligned}
v_{g,t}-w_{g,t}&=u_{g,t}-u_{g,t-1},&v_{g,t}+w_{g,t}&\le1,\\
P_g^{\min}u_{g,t}&\le p_{g,t}\le P_g^{\max}u_{g,t},&
p_{g,t}&=P_g^{\min}u_{g,t}+\sum_k x_{g,k,t},\\
0\le x_{g,k,t}&\le W_{g,k}u_{g,t},&
p_{g,t}-p_{g,t-1}&\le R_g^\uparrow u_{g,t-1}+SU_gv_{g,t},\\
p_{g,t-1}-p_{g,t}&\le R_g^\downarrow u_{g,t}+SD_gw_{g,t}.&&
\end{aligned}
\tag{2a}
$$

最短开/停机时间在现有代码中按前向窗口施加：$\sum_{h=t}^{\min(t+U_g-1,T)}u_{g,h}\ge U_gv_{g,t}$ 与 $\sum_{h=t}^{\min(t+D_g-1,T)}(1-u_{g,h})\ge D_gw_{g,t}$，并施加由初始已开/已停时长决定的剩余窗口。这个有限时域末端约定会排除末尾不足 $U_g$ 或 $D_g$ 的新启停；跨论文比较时必须保持同一约定。申报总成本为

$$
\widehat C_g=\sum_t\left(C_g^{NL}u_{g,t}+C_g^{SU}v_{g,t}+C_g^{SD}w_{g,t}
+\sum_k(1+\beta_{g,t})s_{g,k}x_{g,k,t}\right).
\tag{2b}
$$

系统还要满足式 (2) 的逐时平衡和 PTDF 线限。这里的 $x$ 是按递增斜率填充的凸 PWL 段；若将来采用非凸成本段，必须重新核实凸化口径，不能直接沿用上式。

Phase 1 不是把式 (2a) 中的 $u$ 简单放松到 $[0,1]$。它对每台机组构造所有满足启停时长逻辑的 ON/OFF interval DAG：弧权 $z_{g,a}\ge0$ 满足源点单位流与中间节点流守恒；一条 ON 弧 $a=[r,s]$ 上有加权出力 $q_{g,a,t}$，其容量、启动/停机和相邻小时爬坡均乘弧权作透视约束，例如 $P_g^{\min}z_{g,a}\le q_{g,a,t}\le P_g^{\max}z_{g,a}$、$q_{g,a,t}-q_{g,a,t-1}\le R_g^\uparrow z_{g,a}$。汇总出力 $p_{g,t}=\sum_{a\ni t}q_{g,a,t}$ 进入系统平衡/线路约束。PWL 情形对每个 ON 弧-小时设置 $c_{g,a,t}$，并对每段施加

$$
c_{g,a,t}\ge(1+\beta_{g,t})\left[s_{g,k}\big(q_{g,a,t}-P_g^{\min}z_{g,a}\big)+b_{g,k}z_{g,a}\right],\quad\forall k,
\tag{2c}
$$

其中 $b_{g,k}$ 是相对 $P_{\min}$ 出力的 PWL 截距。相对乘数 $\beta$ 采用式 (2c)，会改变上镜图系数。令 $y=q-P_g^{\min}z$，统一绝对加数利用
$\max_k\{(s_{g,k}+\delta)y+b_{g,k}z\}=\delta y+\max_k\{s_{g,k}y+b_{g,k}z\}$，
保持式 (2c) 的基准斜率不变，只把 $\delta(q-P_g^{\min}z)$ 加入目标。目标仍为弧上的固定费用、$\sum c_{g,a,t}$ 与绝对报价线性项。单段成本采用等价的稀疏目标表达。其余透视约束（初始状态、启停边界）见共享求解器；这一区分保证绝对参数的 LP 矩阵固定，同时保留相对乘数作为经济稳健性口径。

$$
\lambda_{n,t}^{\rm CHP}=\lambda^E_t+\sum_l H_{l,n}\mu_{l,t},
\tag{3}
$$

其中 $\mu$ 的符号与上、下线路约束的对偶约定一致。研究代码直接复用求解器返回的 nodal price，并保存其 energy component；不另写一个近似定价模型。

### 2.4 从标量敏感度到时空 Jacobian

MVP-1 可在整段同一扰动下计算 $j_g^{\rm scalar,rel}=\partial\operatorname{vec}(\lambda)/\partial\beta_g$ 或 $j_g^{\rm scalar,abs}=\partial\operatorname{vec}(\lambda)/\partial\delta_g$，用于便宜的全机组快筛；它们均不能称为旧文献的 hourly VI，且两种分数单位不同。核心对象是

$$
J_{g;(n,t),\tau}=\frac{\partial\lambda_{n,t}^{\rm CHP}}{\partial\beta_{g,\tau}},
\qquad J_g\in\mathbb R^{(N_BT)\times T}.
\tag{4}
$$

pool 系统退化为 $T\times T$。第 $\tau$ 列回答“一小时的报价变化影响哪些地点和小时”。数值第一版用中央差分

$$
\widehat J_{g;(n,t),\tau}(\epsilon)=
\frac{\lambda_{n,t}(+\epsilon e_{g,\tau})-\lambda_{n,t}(-\epsilon e_{g,\tau})}{2\epsilon},
\quad\epsilon\in\{0.01,0.005,0.001\}.
\tag{5}
$$

式 (5) 的 $\epsilon$ 是**相对斜率乘子**，不是美元/MWh 的绝对变化。绝对口径另定义 $J^{\rm abs}_{g;(n,t),\tau}=\partial\lambda_{n,t}/\partial\delta_{g,\tau}$，并用 $\delta=\pm h$（单位：美元/MWh）中央差分；两种口径各自报告 $V_g$ 与排序。单段成本且同一基础斜率时可作链式换算，多段 PWL 的 $J^{\rm rel}$ 与 $J^{\rm abs}$ 通常不能用一个统一斜率互换。若可行申报集合仅允许正加价，中央差分仍可用作数学局部诊断，但可获利策略实验只能使用允许的报价；必要时报告右侧差分。价格可能有不唯一对偶或基切换，因此有限差分有时只是跨区间响应，不能未经检查就称为处处存在的导数。

### 2.5 三种描述量与一个反误判修正

继承旧论文的总体 vulnerability：

$$
V_g=\frac1T\sum_{\tau=1}^T\|J_g[:,\tau]\|_2.
\tag{6}
$$

为跨不同节点数比较，可另报 $V_g/\sqrt{N_B}$；原始 $V_g$ 仍用于与文献定义对齐。时间溢出比例：

$$
S_g^{\rm time}=\frac{\sum_{\tau,t\ne\tau,n}|J_{g;(n,t),\tau}|}{\sum_{\tau,t,n}|J_{g;(n,t),\tau}|}.
\tag{7}
$$

分母为零时约定为零并标记“near-zero influence”。空间解释不能简单统计“其他节点的响应”：无拥塞且所有节点同价时，这个比例仍可能接近 $(N_B-1)/N_B$。由式 (3) 令 $J^E_{g;t,\tau}=\partial\lambda^E_t/\partial\beta_{g,\tau}$、$J^{\rm cong}_{g;(n,t),\tau}=J_{g;(n,t),\tau}-J^E_{g;t,\tau}$，再报告

$$
S_g^{\rm cong}=\frac{\|J_g^{\rm cong}\|_1}{\|\mathbf 1_{N_B}\otimes J_g^E\|_1+\|J_g^{\rm cong}\|_1}.
\tag{8}
$$

它表示响应中节点差异/线路对偶通道的规模，而不是“本地以外有多少节点受到共同系统价影响”。这些量先叫 vulnerability / price-influence descriptors；只有获利验证后才讨论“market-power screening”的有效性。

式 (8) 中 $\lambda^E$ 是所选 PTDF 参考节点下的能量分量，故 **$S_g^{\rm cong}$ 随参考节点/分解口径变化**，不能单独用于跨网络比较。另报参考节点不变的节点离散度：令 $\bar J_{g;t,\tau}=N_B^{-1}\sum_nJ_{g;(n,t),\tau}$，$M_g=\sum_{n,t,\tau}|J_{g;(n,t),\tau}-\bar J_{g;t,\tau}|$，定义 $S_g^{\rm spatial}=M_g/(\|J_g\|_1+M_g)$（分母零时取零）。它只说明节点响应不一致；把不一致归因于输电拥塞，还需要线路达到限额、线路对偶非零以及 C2/C3 的配对证据。

### 2.6 获利定义、uplift 会计与因果边界

在模式 B 中，机组 $g$ 的能量收入为 $R_g(\beta)=\sum_t\lambda_{n(g),t}(\beta)p_{g,t}^{\rm UC}(\beta)$。按照现有结算口径，机组 uplift 是**基于申报成本**的自调度最大利润与执行调度申报利润之差，记为 $U_g^{\rm rep}(\beta)$。研究要衡量的真实利润必须另用不随申报改变的 $C_g^{\rm true}$：

$$
M_g^{\rm rep}(\lambda,\beta)=\max_{(u_g,p_g)\in X_g}\left\{\sum_t\lambda_{n(g),t}p_{g,t}-\widehat C_g(u_g,p_g;\beta)\right\},\quad
U_g^{\rm rep}=\max\!\left\{0,M_g^{\rm rep}-\left[R_g-\widehat C_g(u_g^{\rm UC},p_g^{\rm UC};\beta)\right]\right\}.
\tag{9a}
$$

$$
\Pi_g^{\rm true}(\beta)=R_g(\beta)+U_g^{\rm rep}(\beta)
-C_g^{\rm true}\!\left(u_g^{\rm UC}(\beta),p_g^{\rm UC}(\beta)\right).
\tag{9}
$$

因此 $\Delta\Pi_g=\Delta R_g+\Delta U_g^{\rm rep}-\Delta C_g^{\rm true}$。报告三项而非一个净数字，才能区分价格、uplift 和出力/成本通道。系统层面的 FTR/拥塞结算与**单机利润**分开记录，不能把全系统 FTR 项加到该机组收入上。

利润渠道还需进一步按事实命名：若 $\Delta U_g^{\rm rep}$ 为主要正项，应解释为**申报成本与 uplift 结算渠道**；若能量收入增加但真实成本也变化，要看净效应，而非只称“抬高价格获利”。当前入口只模拟**单一机组、向上可变成本加价**，其余机组如实报价；`--bid-cap` 是本研究网格上限，不是已核实的市场法规上限；offer mitigation **未建模**。后续任何全局最优利润主张都必须先明确真实制度中的报价约束和结算规则。

给定有限策略网格 $\mathcal B_g^{\rm grid}$，$\max_{\beta\in\mathcal B_g^{\rm grid}}\Delta\Pi_g(\beta)$ 仅是“观察到的最大增益”，是完整策略集合上最优市场力的**下界**；没有解双层最优化就不声称得到全局最大值。候选网格从 $\{0,0.02,0.05,0.10,0.15,0.20\}$ 开始，并明确报价上限、其他机组不变、单方操纵和是否允许负加价等制度假设。

### 2.7 条件性的理论方法

相对乘数 $\beta$ 在当前 3 段 PWL 上镜图中进入约束矩阵；若直接对它求导，在一个唯一、非退化且最优基不变的局部区域，活动基 $B(\beta)$ 与对偶 $y(\beta)$ 满足 $B(\beta)^\top y(\beta)=c_B(\beta)$，从而

$$
B^\top\frac{\partial y}{\partial\beta}
=\frac{\partial c_B}{\partial\beta}
-\left(\frac{\partial B}{\partial\beta}\right)^\top y.
\tag{10}
$$

本分支第一版不用式 (10) 追踪相对乘数，而采用第 0 节定义的统一绝对加数 $\delta$。先利用 $v(\delta)=\min_{x\in\mathcal P}(c^0+\delta d)^Tx$ 的全局凹分段线性结构：在数值最优面上最小化/最大化 $d^Tx$ 近似右/左导数，再用支撑线交点递归重构价值区间。这个对象与基选择无关。只有进入某个已数值验证价值区间后，才使用具体基的对偶与 reduced-cost 关系识别价格子区间。相对乘数未来也可通过增量段表示尝试 objective-only；式 (10) 只是当前 epigraph 下的完整局部导数，不是“不可能参数化”的证明。

## 3. 实验设计：每个对照只承担一个解释任务

### 3.1 五个机制场景与一条干净的网络配对

| 场景 | 保留/放松的机制 | 预期用来排除的替代解释 |
|---|---|---|
| C0：时段可分 | pool；MUT/MDT=1；无启停费用；正常与启停爬坡均放宽 | 非对角元素应不高于求解数值噪声，验证 Jacobian 维度、小时索引和对偶口径。 |
| C1：启停耦合 | 恢复启停费用、MUT/MDT 和启停爬坡；正常运行爬坡放宽 | 对比 C0，辨认 commitment/startup/shutdown 带来的时间联系。 |
| C2：正常爬坡 | 在 C1 基础上恢复原正常爬坡参数；仍为 pool | 对比 C1，只有新增的稳定差异才能归因于正常爬坡。若无差异，应继续调整 ramp/负荷场景，而非宣称 ramp 机制已验证。 |
| C2N：无拥塞网络 | **相同 C2 机组**，在原 6/30 节点负荷及 PTDF 上使用 relaxed 线限 | 节点与网络表示已经存在，但线限不约束价格；作为 C3 的直接对照。 |
| C3：拥塞网络 | 与 C2N 的机组、逐节点负荷、PTDF 完全相同；只收紧线限 | 仅当线路达到限额且对偶非零时，比较 C2N→C3 的节点差异，才归因于网络拥塞。 |

五个场景使用相同机组基础参数和同一总负荷轨迹。**C2→C2N 是 pool 与 PTDF 的无拥塞一致性检查；网络机制的因果配对是 C2N→C3，而不是 C2→C3。**短时段 toy 用于验证索引，但机制判断必须选约束真正活动的负荷窗口。现有 `case6ww` 是 3 台机组的 Wood–Wollenberg 数据，不是 Sun–Wu 2021 年 6 台机组实例，也不同于中文论文经过改编的 IIT 6-bus；旧论文复现需单独核对参数、负荷和整段 ON/OFF 假设。

对应的可证伪预期是：H1，C0 的非对角响应低于数值阈值；H2，若启停/最短开停机确实起作用，C1 相对 C0 出现稳定非对角项；H3，只有当 Phase-1 正流 ON 区间的正常爬坡约束活动时才预期 C2 相对 C1 发生可解释变化；H4，只有当线路拥塞成为有效约束时才预期 C3 相对 C2N 出现可重复的节点差异。$V_g$ 高的机组是否更能获利**不是先验假设**，而是模式 B 要检验的开放问题：正关联、零关联或系统性背离都应报告。

### 3.2 可信结果的五道检查

1. **同案重复与对偶选择警示**：相同 CHP 两次求解的节点价格、目标和状态；再比较 simplex、barrier 与 crossover 的价格。仅 `OPTIMAL` 进入导数计算。重复或算法一致性**均不证明对偶唯一**；理论部分要限制于价格唯一/非退化情形，或明确价格选择规则。共享求解器沿用旧项目的对偶符号/非负清理约定；正式实验还必须检查该清理没有截断原始平衡对偶。
2. **C0 对角性**：比较最大非对角响应与价格重复噪声放大后的阈值。显著非对角先查约束、索引、对偶选择。
3. **无拥塞退化与线限配对**：先检查 C2/C2N 的共同系统价，再比较同一 PTDF 下 C2N/C3 的线路潮流、限额、对偶和节点价。没有正的线路对偶，就不声称测试了拥塞机制。
4. **多 $\epsilon$ 稳定性**：当前自动标签按超过噪声门槛的 Jacobian **逐元素**比较步长响应；正式分析再人工核对 VI 排名、弱非对角项和热图形态，不用自动标签代替这些检查。强烈依赖步长的单元标为 `critical_or_degenerate`，不取平均掩盖。
5. **经济可比性与定价层诊断**：相对/绝对报价各自排序；利润样本默认要求基线已发电，并记录报价上限、未建模的 mitigation、三项利润变化。每个利润网格点的物理 UC、单机最优自调度及 CHP 均须由求解器证明 `OPTIMAL`，否则该点报错而非纳入 $\Delta\Pi$；共享求解器的其他用途仍可允许 `SUBOPTIMAL`。跨时段机制解释须引用 **Phase-1 LP 正流 ON/OFF 弧与活动透视爬坡约束**，不能以 physical UC 在线时长代替。物理 UC 轨迹另表保存。对不同网络规模的 $V_g$ 另报按 $\sqrt{N_B}$ 归一化版本。

当前实现的 10% 相对步长稳定性门槛与 $10^{-6}$ 最低噪声阈值只是**预警规则**，并非统计置信区间或对偶唯一性的证明。正式结果还应查看各求解的 primal violation、不同 LP 算法/交叉设置下的对偶敏感性，以及必要时的单侧差分。

### 3.3 预期图表及每张图的论证职责

1. **图 1：$T\times T$ 热图**，横轴报价小时、纵轴价格小时，颜色 $|J|$；C0 作诊断，C1/C2 作时间机制对照。
2. **图 2：bus $\times$ time 热图**，固定机组和报价小时；与 $J^{\rm cong}$ 或能源/拥塞分解图配对。单独的节点价绝对变化不足以证明网络通道。
3. **表 1：机组筛查排序**，给出 $V_g,S_g^{\rm time},S_g^{\rm cong},S_g^{\rm spatial}$，以及三个 $\epsilon$ 的稳定标签。
4. **图 3：机制配对**，C0→C1、C1→C2、C2→C2N、C2N→C3 的差分图或同刻度并排图，并配活动弧/爬坡和线路对偶表。
5. **图 4：真实利润曲线**，高/中/低 vulnerability 机组的有限加价网格；配三项收入/成本分解。它检验指标是否有经济筛查意义。
6. **表 2：解析法可选验证**，仅理论方法成立后，报告与 finite difference 的价格/Jacobian 一致性、退化例外和时间成本。

## 4. 可执行路线、判断门槛与预期结果

| 顺序 | 工作与主要输出 | 继续/调整条件 |
|---|---|---|
| 第 1–2 天：基线与 scalar | 固定市场口径；重复求解；3 段 PWL 的全机组 scalar 排名与三步长表。 | 不稳定先修对偶/场景；不把数值噪声当市场影响。 |
| 第 3–4 天：hourly | 6-bus pool 的完整 $T\times T$ Jacobian、C0 对角性和第一张图。 | 有可重复的非对角结构再继续机制研究；无结构先核对负荷和启停约束。 |
| 第 5–6 天：机制 | C1/C2 比较的同时输出 Phase-1 正流 ON 弧及活动正常爬坡；不以物理 UC 的在线时长代替凸包定价层证据。 | 活动约束与价格差异必须在同一负荷窗口对应；若逐元素差分随步长突变，标为临界区而非局部导数。 |
| 第 7–8 天：空间与指标 | 同一 PTDF/负荷/机组下比较 C2N 宽松线限与 C3 收紧线限，并联看潮流、线限、对偶、节点价及 bus-time Jacobian。 | 只有正线路对偶和稳健节点异质响应同时出现，才解释为拥塞传导；不能拿 C2 pool 对 C3 网络直接归因。 |
| 第 9–10 天：初步经济验证与 memo | 对基线已发电机组做受上限约束的单方上调报价网格；重求 UC/CHP/申报 uplift，报告 $\Delta R+\Delta U-\Delta C^{\rm true}$。 | 区分能量、uplift 和出力/成本渠道；只报告有限网格观察增益，不称全局最优或已模拟缓解规则。 |
| 后续 2–4 周：系统化 | 相对/绝对 Jacobian 各自排序、多个步长、负荷/初态/PWL 扰动；取得旧文献缺失负荷与约束资料后才做严格复现，随后扩到 IEEE-30。 | 强响应需要跨步长与案例复现；筛查指标必须在独立利润样本上检验，不能用同一算例拟合后自证。 |
| 之后：解析与扩展 | 参数 LP、临界区域和加速；再视论文需要研究 startup bid、灵活性资源、IEEE-118。 | 只有可靠且显著的计算收益才主张算法优势。容量持留与合谋另立问题。 |

**四个研究门槛**：G1 价格响应高于求解器/对偶噪声，排序对步长及相对/绝对报价口径保持稳定；G2 至少一种时间/空间传播随明确的定价 LP 活动约束出现，并在相应控制配对中可复现；G3 价格筛查与真实利润之间存在可解释的关系或系统性背离；G4 解析方法相对重复求解有清晰收益。G1/G2 不成立时先改善实验设计，不提前写理论贡献；G3 的“背离”也是有价值的 CHP 经济结论；G4 不成立时论文仍可由机制与经济验证支撑。

**24 小时 pilot 已取代先前 3–6 小时窗口的机制判断。** 6 节点 C2N/C3 同 PTDF、同负荷、同机组，仅 C3 收紧线限；C2N 无正线路对偶，C3 在第 7、19 小时有 3 个达限且正对偶的线路—小时。相对与绝对两种报价口径各取两档步长，全机组 $V_g$ 排序均为 G2 > G3 > G1；但把相对两步长放进同一次全矩阵检查后，三台机组都触发逐元素 `critical_or_degenerate` 预警，**排序稳定不等于局部导数处处存在**。选取的强拥塞响应单元经更小步长及单侧差分复核；C2 的定价层正流 ON 弧也有活动正常爬坡，但完整 ramp 因果图像尚须核查。

进一步的控制实验中，6 节点负荷同比例变动 $\pm2\%$ 不改变“C2N 无拥塞、C3 有拥塞且强节点异质响应”的定性结论；line limits 从 relaxed、moderate 到 tight 时活动线路—小时为 0、1、3，响应**并不单调随线限变紧而放大**。独立 30 节点案例的 C2N/C3 配对则为 0/7 个正对偶线路—小时，G3/G5 的选定拥塞小时节点响应在两档步长间近似一致；三种 LP 算法的基线节点价格最大差约 $1.73\times10^{-6}$，只能作为算法一致性警示，不能证明唯一性。30 节点完整相对 hourly VI、预筛后绝对 hourly VI 和全部基线发电机组利润网格均已完成；两种报价口径的主排序均为 G5 > G1 > G3 > G6，而正观察利润为 G1 > G3 > G5、G2/G6 近零。**这是完整 hourly VI 下的候选机制背离，但尚无样本外效度。** 原始数值、失败单元与判断边界见 [PILOT_EVIDENCE.md](PILOT_EVIDENCE.md)。

## 5. 研究链条与代码库的明确对应

| 学术任务 | 已有/新增实现 | 当前状态与下一个动作 |
|---|---|---|
| 原始机组与网络案例 | `../chp_energy/models/`、`../chp_energy/data/cases/`；[REFERENCE_2021_AUDIT.md](REFERENCE_2021_AUDIT.md) | 直接复用当前 3 机组 `case6ww`；2021 六机组参数已审计，但精确负荷及原模型整段 ON/OFF 假设尚未可比，不能宣称复现。 |
| 物理 UC 与 exact Phase 1 CHP | `../chp_energy/chp_solver/schedule_run.py`、`chp_master_lp.py` | 单一求解器；Phase 1 已支持可选逐机组-小时报价乘子和绝对斜率加数，默认参数保持旧实验不变。 |
| 基线与 C0–C3 | `engine.py`、`price_vulnerability/diagnostics.py`、`run_pricing_diagnostics.py` | C2N/C3 控制相同 PTDF 下的线限差异；`--load-scale` 对全部节点负荷施加相同比例变化而不改网络拓扑；分别导出定价 LP 正流 ON/OFF 弧、活动爬坡、线路潮流/对偶与物理 UC。 |
| scalar 快筛 | `price_vulnerability/scalar_markup.py`、`run_price_vulnerability.py` | 整段相对/绝对报价扰动用于便宜的全机组初筛；其分数是 scalar response，**不是**旧文献 hourly VI。 |
| hourly Jacobian、指标和图 | `price_vulnerability/hourly.py`、`run_hourly_vulnerability.py` | 已实现相对/绝对斜率扰动、双侧重求、时间/空间描述量、长表、全矩阵和按报价小时的步长预警；30 节点相对全机组及绝对预筛机组双步长 VI 已完成，下一步只在独立场景复算预注册对象。 |
| 获利验证 | `run_profit_validation.py`、`strategic_market_simulation/profit_sweep.py`，复用 `../chp_energy/chp_solver/schedule_run.py`、`benchmarks/unit_self_schedule.py` | 有限**标量**网格逐点重求 UC/CHP/申报 uplift，三者在此入口都要求证明最优；默认仅选基线发电机组，约束上调报价上限，并按真实成本分解增益；未实现 mitigation、全局最优和样本外指标检验。 |
| 参数区间与解析敏感度 | `PARAMETRIC_FORMULATION.md`、`../chp_energy/chp_solver/chp_master_lp.py`、`run_basis_dual_audit.py`、`price_vulnerability/value_oracle.py`、`run_value_oracle.py` | R1 恒等式、R1.5 退化审计和 R2 value oracle 原型已实现；先完成容差压力测试，再进入价格子区间。 |

### 当前可复现命令

在 `chp_marketpower/` 下执行（求解使用 COPT 8，需要有效 COPT 许可证及全局 `gurobi_compat`）：

```powershell
python tests/check_chp_integration.py
python -m pytest -q tests -p no:cacheprovider
python run_pricing_diagnostics.py --case 6 --scenario C1 --T 24 --segments 3 --out-dir results/diagnostics_C1
python run_pricing_diagnostics.py --case 6 --scenario C2 --T 24 --segments 3 --out-dir results/diagnostics_C2
python run_pricing_diagnostics.py --case 6 --scenario C2N --T 24 --segments 3 --out-dir results/diagnostics_C2N
python run_pricing_diagnostics.py --case 6 --scenario C3 --T 24 --segments 3 --dual-audit --include-uc --out-dir results/diagnostics_C3
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization relative --epsilon 0.005 --out-dir results/full_C3_relative_eps0005
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization relative --epsilon 0.001 --out-dir results/full_C3_relative_eps0001
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization absolute --epsilon 0.1 --out-dir results/full_C3_absolute_eps01
python run_hourly_vulnerability.py --case 6 --scenario C3 --T 24 --segments 3 --parameterization absolute --epsilon 0.05 --out-dir results/full_C3_absolute_eps005
python run_profit_validation.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generators 0 1 2 --beta 0 0.05 0.10 --bid-cap 0.10 --out results/profit_c3_24h_pilot_strict.csv
python run_parametric_regime_scan.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --grid 0 0.025 0.05 0.075 0.10 --out-dir results/regime_G2_direct
python run_basis_dual_audit.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --deltas 0 0.04 0.06 0.10 --out results/basis_dual_G2.json
python run_value_oracle.py --case 6 --network ptdf --congestion tight --T 24 --segments 3 --generator 1 --lower 0 --upper 0.1 --out-dir results/value_oracle_G2
```

30 节点 P0 的最小复算集合如下；历史负荷缩放、单小时 probe 和 scalar 预筛命令不再列入主入口：

```powershell
python run_pricing_diagnostics.py --case 30 --scenario C2N --T 24 --segments 3 --out-dir results/diagnostics_case30_C2N
python run_pricing_diagnostics.py --case 30 --scenario C3 --T 24 --segments 3 --include-uc --out-dir results/diagnostics_case30_C3
python run_hourly_vulnerability.py --case 30 --scenario C3 --T 24 --segments 3 --parameterization relative --epsilon 0.005 0.001 --out-dir results/full_case30_C3_relative_twostep_copt
python run_hourly_vulnerability.py --case 30 --scenario C3 --T 24 --segments 3 --generators 0 2 4 5 --parameterization absolute --epsilon 0.1 0.05 --out-dir results/full_case30_C3_absolute_twostep_copt
python run_profit_validation.py --case 30 --network ptdf --congestion tight --T 24 --segments 3 --beta 0 0.05 0.10 --bid-cap 0.10 --out results/profit_case30_C3_all_dispatched_copt.csv
```

`results/` 下的 Jacobian 长表保留 `+/-` 报价、价格、目标、状态、时间和扰动单位；`vulnerability_metrics.csv` 保存逐步长指标、基线重复误差与全矩阵临界标签，`stability_by_bid_hour.csv` 逐列标记；诊断 CSV 分别保存定价 LP 和物理 UC。`delta_true_profit` 必须等于 `delta_energy_revenue + delta_reported_uplift - delta_true_cost`。默认输出被 `.gitignore` 忽略，正式论文结果应另行归档场景配置、COPT/垫片版本和原始表。迁移后的 6 节点 C3 基线及 30 节点 PTDF/tight 基线与 Gurobi 存档在目标、节点价、结算量和 UC 上达到数值容差一致；退化 LP 的弧流分解可随求解器改变，故机制结论不以单一退化弧的精确权重为跨求解器不变量。

## 6. 写作边界与最终决定

论文动机是 CHP 对非凸成本的价格设计与战略激励之间存在张力；方法是 exact DAG-CHP 支撑的**受控报价干预**；实验先证明可重复的时空传播，再问其经济含义。论文是否主打“时空传播”“vulnerability 与利润的背离”或“快速灵敏度”，由 G1–G4 的证据决定，不能由项目名称或初始设想决定。

当前已有**活动线限与正线路对偶的受控拥塞配对**、6 节点全机组相对/绝对 $V_g$、全矩阵临界预警、30 节点 hourly VI、全部基线发电机组利润分解、两个 P1 holdout，以及 6 节点 G2 的五个初步数值验证价值区间。经验层面的重复扩展已停止；下一道门槛是容差稳健性和原始对偶接口，随后才是价格子区间。凡是没有重求 UC/结算和真实成本核算的结果，统一称为 *price influence / vulnerability*，不称为可获利市场力；有限利润网格也不称最优操纵。“高 VI 与利润背离”目前是候选经验现象，不写成一般定理。

## 7. COPT 迁移后的收敛路线：做什么、停止重复什么

求解后端已统一为 COPT 8.0.6。迁移验证先后覆盖矩阵 CHP、物理 UC、单机自调度、LMP/IRP/LVM/DWP/S-CHP 共享路径，并用 6 节点 C3 及 30 节点 PTDF/tight 同配置对照迁移前的目标、节点价、结算量和 UC。后续实验不再把“换求解器”当作新的经济结论；它只改变数值实现和对偶选择警示，已有机制主张仍须通过同一套活动约束与步长检查。

接下来的执行顺序固定为：

1. **P0 已完成：30 节点完整筛查。** 相对口径覆盖 6 台机组，绝对口径按预先的相对 hourly 与绝对 scalar 信号保留 G1/G3/G5/G6；两档步长的主排序均为 G5 > G1 > G3 > G6，G2/G4 不因重复近零计算进入主排序。
2. **P0 已完成：全部基线发电机组利润样本。** 同一有限加价网格和严格最优检查得到 G1/G3/G5 正观察增益、G2/G6 近零；完整 VI 与利润出现候选背离，但有限网格仍不称为最优操纵。
3. **P1 两个 holdout 已完成。** 空间样本中 G1/G3 列范数下降而利润上升，G5 列范数近似不变而利润下降；warm-up 初态中 G1/G3 列范数近似不变而利润下降，G5 列范数下降约 24–25% 而利润上升 62.86%。两个样本都只使用冻结的 G1-23、G3-20、G5-8 和同一利润网格；P1 不再新增场景。
4. **P1：解释临界列，而非增加汇总分数。** 对双步长不稳但信号质量显著的列，记录正/负侧的 ON 弧、活动爬坡和线路对偶，区分真正的活动集切换、退化价格选择和纯数值噪声。
5. **P2/R2 价值层已完成试点，进入价格子区间。** 四点基审计显示价格数值一致但基高度退化；价值优先算法进一步找到五个区间并通过 15 个内部直接查询。下一步在每个价值区间内用基信息生成价格候选事件，由 COPT 右侧重求验证，并合并价值线和价格线均相同的相邻基；若开区间内部出现实质价格分歧，再设计二级选择或对偶价格界。local arc oracle、二维参数、NN、IEEE-118、容量持留和合谋仍不进入当前阶段。

空间 holdout 的实际执行严格遵守预注册：令 $d'_{23,t}=(1-\rho)d_{23,t}$、$d'_{21,t}=d_{21,t}+\rho d_{23,t}$，其余节点不变。5% 场景因活动集与价格几乎不变而停止；20% 场景出现正流 OFF 弧支撑变化后，才计算 **G1-第23小时、G3-第20小时、G5-第8小时** 的相对 $0.005/0.001$、绝对 $0.1/0.05$ 和三台机组的利润网格。这里不补跑全矩阵，因为研究问题是预注册列在独立空间分布下是否保持经济解释，而不是重新筛选小时。

warm-up 初态已按上述门槛执行：一日前置 UC 生成 `initial_status`、`initial_power` 和连续开/停时间，正式 24 小时负荷、网络和报价不变；诊断确认物理 UC、G5 ON 弧及一个价格形成线路—小时改变后，才复算相同三条报价列和利润网格。下一阶段转为**机制归因与写作收敛**：对两个 holdout 的三台机组并列报告 $\Delta R^{energy}$、$\Delta U^{rep}$、$\Delta C^{true}$、关键线路对偶和弧变化，解释为什么价格影响与利润方向分离。除非归因无法闭合，否则不再新增情景、全矩阵或指标。

停止重复的实验包括：6 节点 C0–C3 smoke、已由双步长全矩阵覆盖的单步长全天运行、更多接近 $\pm2\%$ 的统一负荷缩放，以及没有对应利润或活动集问题的额外热图。旧目录保留作审计证据；正式归档只指定双步长全矩阵、COPT 基线验证、完整利润表和必要的机制探针为 canonical 结果。

冗余审计结论：`smoke*`、`profit_smoke.csv`、`absolute_c0_smoke/`、`stability_by_hour_smoke/` 和 `copt_probe_*` 不是论文结果；单步长 `full_C3_*_eps*` 已被双步长运行覆盖；`profit_case30_C3_pilot.csv` 已被全基线发电机组利润表覆盖。它们暂不删除，以免丢失迁移和调试审计链。scalar 快筛及拥塞小时 probe 仍承担“预筛”与“机制复核”职责，不算重复实现。代码层也不抽取两个入口各自只有数行的 CSV 写入函数，不为一次性结果合并增加工具模块。
