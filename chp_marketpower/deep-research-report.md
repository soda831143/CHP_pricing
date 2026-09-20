# 凸包定价市场力研究的文献脉络、最近邻工作与可主张创新空间

## 核心判断：你们的方向不是空白领域，而是几个成熟研究分支尚未真正汇合的交叉点

结合截至 **2026 年 9 月 17 日**对凸包定价（CHP/eLMP）、非凸电力市场激励、市场力监测、节点价格敏感度、网络约束市场力、战略竞价以及最新 CHP 求解文献的检索，我认为我们前面提出的判断基本成立，但现在可以说得更准确：

> **不能把“CHP 下有市场力”“用利润分析战略报价”“用 Jacobian 分析报价对价格的影响”“考虑网络”“精确计算 CHP”中的任何一个单独拿来作为创新。它们分别都已有文献。**

真正仍然比较清晰的研究缺口，是把这些此前分散的研究线统一到：

\[
\boxed{
\text{full-trajectory exact CHP}
+
\text{network}
+
\text{intertemporal UC/ramping}
+
\text{bid-to-price sensitivity}
+
\text{uplift-aware profitable market power}
}
\]

这一框架中，并进一步回答：

\[
\boxed{
\text{price vulnerability 到底什么时候会、什么时候不会转化为 profitable market power？}
}
\]

在本次检索覆盖的公开文献中，我没有找到一篇论文同时完成上述整条链条。这个判断不是“已经证明我们是 first”，而是说明**这确实是一个可以认真经营的 novelty intersection**。更重要的是，你们现在的研究方案已经恰好沿这个交叉区域展开：以 exact DAG-CHP 为基础，研究报价到节点 CHP 的时空传播，再通过 UC、CHP、自调度、uplift 和真实成本验证实际利润。fileciteturn0file0

从投稿目标看，这个定位和 **IEEE Transactions on Energy Markets, Policy and Regulation（T-EMPR）** 非常匹配。该刊官方 scope 直接列出 *market participation, market power and market monitoring, bidding strategies, pricing and settlement, congestion management*，同时特别强调论文应具有详细的 engineering、economic 和 policy analysis；反过来，如果主要贡献只是优化算法，而市场只是附带应用，则明确属于不推荐的方向。citeturn10search0turn16view5

因此，对你们而言，**解析 Jacobian 应当是 enabling methodology，而不是论文最终目的；真正的论文中心应该是 CHP market monitoring 和 economic market power。**

一个最有用的文献地图可以概括成：

| 文献分支 | 已经解决了什么 | 没有解决什么 | 对你们的直接启示 |
|---|---|---|---|
| CHP 理论与求解 | exact/approximate CHP、凸包、网络流、DW、Benders | 基本不研究战略行为 | 提供你们的 computational foundation |
| CHP/eLMP strategic bidding | 已证明存在操纵、利润分解、maximal markup、market power | 模型多为高度简化 | 不能声称首次研究 CHP 市场力 |
| CHP temporal vulnerability | \(T\times T\) Jacobian、VI、Minkowski 结构 | commitment 全时域固定，主体是 pool model | 你们最直接的理论前身 |
| 非凸定价 incentive analysis | truthful bidding、LOC/uplift、战略利润 | 多用简化市场模型 | 不能声称首次发现 uplift 影响策略收益 |
| LMP market-power sensitivity | 节点价格关于报价的 derivative matrix、网络影响 | 没有 startup/uplift/full UC convexification | 不能声称首次用价格导数监测市场力 |
| 网络市场力/博弈 | RSI、residual demand、SFE、网络拓扑效应 | 基于传统 LMP/凸清算 | 提供监管指标 benchmark |
| 你们拟做 | 上述几条真正合流 | —— | novelty 应放在“交叉”和“经济联系”上 |

下面逐条拆开。

## 凸包定价研究的第一条主线：从“什么是 CHP”走到“大规模 exact CHP 怎么算”

CHP 的经典研究首先关心的是一个定价问题：由于 startup、no-load、minimum output 等非凸成本存在，传统边际价格不能完整支持 UC 调度，CHP 通过凸化系统非凸性得到 minimum-uplift price。Schiro、Zheng、Zhao、Litvinov 的 2016 年 TPWRS 文章是这一脉络的重要代表，它既解释 CHP 与基本市场出清的联系，也特别展示了一些 CHP 的 counterintuitive properties；但它的核心仍是定价理论、性质和实现挑战，而不是 strategic market power。citeturn13search0

随后相当大的文献集中到“如何把 CHP 精确而且足够快地算出来”。Hua 和 Baldick 将机组可行域凸包与成本凸包络显式写入 primal formulation；在 PWL 成本下得到 LP，并在 transmission-constrained 多时段实例上展示了计算可行性。citeturn12academia8 Yu、Guan、Chen 又针对 MISO 机组特性建立 integral formulations 和迭代算法，并报告了含、无输电约束的 exact CHP。citeturn11academia1

这一计算路线此后继续发展。Yu 等的 network-flow-based formulation 能处理 ramping、不同 initial status、maximum start-ups，并在 IEEE 118-bus 上测试；这说明“**用网络流描述复杂热机组轨迹再求 CHP**”本身已经不是新的研究主题。citeturn11search0 Andrianesis、Bertsimas、Caramanis、Hogan 使用 Dantzig–Wolfe decomposition 和 column generation 给出 exact、finite-convergence 的 CHP 计算框架，并用真实 ISO 数据讨论可扩展性。citeturn13academia44turn13search4 Knueven、Ostrowski、Castillo、Watson 则以 Benders/先进单机 convex-hull formulations 为基础，目标同样是 industrial-scale CHP computation。citeturn13search2turn13search3

而且这条“怎么更高效算 CHP”的线截至 2025–2026 年仍然活跃。例如 2025 年有 fully distributed ADMM CHP，2026 年 EJOR 又出现 adaptive hybrid primal/row/column-generation 方法，继续针对大规模 CHP 计算效率。citeturn8search0turn8search1

老师最近的 Jiang–Wu 工作则走向另一种“decipher CHP”路线：不只是求解，而是利用 desired-generation sets 与近似 Minkowski sum，把 demand space 划分后直接建立 demand-to-CHP mapping。该论文自己也把相关文献分成 computation 和 structural decipher 两大类。fileciteturn0file7 citeturn8search4

这组文献对你们有两个很重要的含义。

第一：

\[
\boxed{\text{“我们有 exact network-flow CHP”不能单独成为下一篇市场力论文的创新。}}
\]

第二，却也是更重要的：

> **这些强大的 exact CHP formulations 基本都停在“如何形成价格”，并没有进一步问“战略报价怎样通过这个复杂 convexified UC 结构传播并转化成市场力”。**

所以你们的 DAG-flow 应被定位为：

\[
\boxed{
\text{the computational and structural enabler of market-power analysis}
}
\]

而不是新的 market-power contribution 本身。

这里还有一个必须牢记的理论警告：Schiro 等后续关于 *formulation dependence of convex hull pricing* 的研究表明，同一个 UC 经济问题如果采用不同 reformulation，得到的 CHP 在某些条件下可能发生变化，因此论文若要基于 DAG-LP 做价格导数，需要明确说明为何你们使用的 formulation 对应目标 CHP，或者证明所使用的等价变换保持价格。citeturn12search2

这会是未来解析 sensitivity theory 中很重要的一句文献连接。

## 与你们最直接重合的主线：CHP/eLMP 下的战略报价、市场力与 Temporal Vulnerability

这里必须非常仔细，因为这是你们真正的“最近邻”。

### 从可获利市场力出发的早期工作

老师团队 2020 年的 *Market Power in Convex Hull Pricing* 已经明确研究 CHP 下的战略行为。模型采用 stylized electricity pool，所有机组容量相同；战略机组可以谎报 startup/fixed cost 和 variable cost，但不允许容量持留。论文定义市场力为通过 strategic bidding 可以获得的最大额外利润，并得到：

\[
M(i)
=
c_{\{i\}}(y)-c(y)-P_i .
\]

它进一步把定义扩展到 coalition，并证明相应 market-power index 具有 supermodularity；论文最后明确把 heterogeneous capacities 和 network constraints 列为 future directions。fileciteturn0file6 citeturn7academia43

所以：

\[
\boxed{
\text{“以最大额外利润定义 CHP market power”已经存在。}
}
\]

你们下一篇不应该重新发明这个定义。

老师随后发表的中文文章给出了更完整的战略报价分析。它把谎报利润拆成影响 market price 的收益与直接和申报成本相关的收益，并分别研究“只谎报固定成本”“只谎报可变成本”“二者都可谎报”三种策略集合；它也明确指出，加入 transmission network 后，用于简单刻画 CHP 的单一 pool-balance 引理不再成立。fileciteturn0file4

这意味着，“**startup bid 与 variable bid 是不同战略维度**”也早已在老师自己的工作中出现。以后你们增加 startup/no-load bid sensitivity，应当定位成：

> 把这些 bid dimensions 放到 **full-trajectory networked CHP** 中分析其时空传播，

而不能说首次认识到 startup bid 可以用于市场操纵。

### Strategic Bidding in eLMP 已经占据了 profit decomposition

Sun、Gu、Wu 的 *Strategic Bidding in Extended Locational Marginal Price Scheme* 已发表于 IEEE Control Systems Letters。公开摘要表明，该文已经专门研究 strategic bidding 对 market prices 与 uplift payments 的操纵，提出 profit decomposition 来分析不同 bidding strategies 对 payoff 的影响，识别潜在 strategic generators，并以 maximal markup 作为 market-power index。citeturn20search0turn20search10

因此下面几个表述以后都应该避免：

\[
\boxed{\text{“首次研究 CHP/eLMP strategic bidding”——不成立}}
\]

\[
\boxed{\text{“首次进行 CHP strategic-profit decomposition”——不成立}}
\]

\[
\boxed{\text{“首次研究 uplift manipulation”——风险很高}}
\]

你们真正可以推进的是：

> **在完整 network + multi-period physical trajectory 下，这些 profit channels 怎样与 spatio-temporal price leverage 发生联系？**

这是不同的问题。

### Temporal Vulnerability 是你们 Jacobian 方向最直接的理论前身

2021 年 *Temporal Vulnerability Assessment for Convex Hull Pricing* 已经把 CHP market-power discussion 从单时段“最大额外利润”推进到多时段“报价影响价格”的角度。论文通过 equivalent characterization、desired-generation sets 和 convex/Minkowski structure 建立 generator bidding 与 CHP 的联系，然后计算：

\[
V_i
=
\frac{\partial\mathbf p^*}
{\partial\mathbf b_i},
\]

即一个 \(T\times T\) 的 bid-to-CHP Jacobian，并据此构造 Vulnerability Index。论文的三项核心贡献就包括 decipher CHP、揭示 bidding influential mechanism、计算 Jacobian 并进行 vulnerability assessment。fileciteturn0file5

所以：

\[
\boxed{
\text{“首次提出 CHP bid-to-price Jacobian”不能作为创新。}
}
\]

甚至“利用 Jacobian 做 CHP market monitoring”本身也已经存在。

但这篇论文同时留下了非常明确的模型边界。主体采用 electricity pool model；每台机组在整个研究 horizon 中只存在一个 commitment state：

\[
u_i=1
\Rightarrow
\text{整个 horizon 在线},
\]

或者

\[
u_i=0
\Rightarrow
\text{整个 horizon 离线},
\]

即不能表示真实的

\[
0\to1\to1\to0\to1
\]

这类启停轨迹。它虽然在 online 状态下考虑 capacity 和 ramp constraints，却明确采用这一 strong assumption 来简化组合结构。fileciteturn0file5 老师在科普文章中也直白说明了这一点，并明确说该工作主体“没有考虑网络约束，且机组在 \(t=1\) 决定开停、后续不能变化”。fileciteturn0file3

这就是你们与其最关键的差异：

\[
\boxed{
\text{old: temporal price vulnerability under simplified commitment}
}
\]

对比

\[
\boxed{
\text{yours: spatio-temporal vulnerability under full commitment trajectories}
}
\]

而且你们还有第二层：

\[
\boxed{
\text{vulnerability}
\rightarrow
\text{actual profitable deviation}.
}
\]

这在 2021 temporal paper 里并不是它的主要分析对象。

### 2023 年的非凸市场 incentive analysis 是必须新增到 Related Work 的强近邻

Yi Wang、Zhifang Yang、Juan Yu 2023 年在 IJEPES 发表的 *Pricing incentive analysis under non-convexity in electricity market* 非常值得你们认真引用，因为它比我们最初讨论时注意到的还要接近。

该文专门区分：

\[
\text{dispatch-following}
\]

和

\[
\text{truthful bidding},
\]

比较 LMP、ConvHP 以及带 compensation/LOC 情况下的 incentive properties，并讨论 strategic bidding 带来的利润空间。一个重要结论是：加入 compensation 可以改善 dispatch following，却可能扩大 strategic-bidding profit space、恶化 truthful-bidding incentive；论文还比较了 LMP 与 ConvHP 下战略报价的利润改善。citeturn17search0turn17search1

这直接告诉我们：

> **“CHP 减少 uplift 但不消除战略激励”“uplift 会改变战略利润”也不能作为单独 novelty。**

但 Wang–Yang–Yu 的目的是建立 simplified analytical framework 比较不同 nonconvex pricing schemes 的 incentive compatibility；它没有建立 full networked UC trajectory 下的节点—时间 bid-price Jacobian，也没有以 exact CHP extended formulation 为基础建立大规模 monitoring framework。citeturn17search0turn17search1

因此，你们应该引用它来强化论文背景，而不是回避它：

> Previous studies establish that non-convex pricing and compensation affect truthful-bidding incentives; our question is how such incentives can be **monitored and attributed in realistic network-constrained multi-period CHP**.

### 另一个不能忽略的近邻：学习型战略行为

Byers 和 Eldridge 的 *Auction designs to increase incentive compatibility and reduce self-scheduling in electricity markets* 从完全不同的方法论方向研究 non-convex electricity pricing 下的战略行为。他们让 agents 通过 reinforcement learning 学会 self-commit/self-schedule，并在 multi-period commitment setting 中比较不同 nonconvex pricing schemes；在约 1000 台机组的现实规模系统中，他们发现 CHP 能降低参与者偏离中央调度的激励。citeturn16view2turn8academia16

这说明一个非常重要的事实：

\[
\boxed{
\text{“realistic multi-period nonconvex pricing + strategic behavior”本身也已有文献。}
}
\]

但它研究的是 auction incentive compatibility 与 learned deviations，不是：

\[
\frac{\partial\lambda_{n,t}^{CHP}}
{\partial b_{g,\tau}}
\]

这种结构化 market monitoring，也不是利用 exact networked CHP representation 去解释 commitment/ramping/congestion 如何产生价格传播。

因此它是一个很好的“同问题、不同方法”的 related work。

## 传统 LMP 市场力研究给出的重要先例：价格 Jacobian、空间传播和 critical regions 都不能单独算新

这一部分对你们未来的理论创新表述尤其重要。

### 节点价格关于报价的导数矩阵早已有直接文献

Piotr Pałka 2017 年在 *Energy Economics* 发表的 *Derivatives of the nodal prices in market power screening* 几乎就是“LMP 版本的你们某一部分思想”。

论文直接计算：

\[
\frac{\partial\lambda_n}
{\partial b_g}
\]

形成 nodal-price derivatives matrix，以此分析 market participants 和 firms 对节点价格的影响，并用于 market-power screening；论文还做了 profit theoretical analysis 和波兰 balancing-market case study。其模型基于 DC OPF，并考虑 transmission network；公开正文摘要还指出市场模型包括 ramp constraints。citeturn9search0

更关键的是，它已经讨论了报价空间中：

> derivative vectors 在特定区域保持常值，

以及这些区域的结构性质。citeturn9search0

这和我们现在设想的：

\[
\boxed{
\text{fixed active basis}
\Rightarrow
J \text{ constant}
}
\]

以及：

\[
\boxed{
\text{critical-region / basis switching}
}
\]

有明显数学亲缘关系。

因此以后千万不要写：

> “We are the first to use analytical nodal-price sensitivities for market-power screening.”

这显然站不住。

真正区别在于 Pałka 的 price formation 基于传统的 convex/DCOPF-LMP，而你们研究：

\[
\boxed{
\text{convexified full UC opportunity sets}
}
\]

形成的 CHP，其中报价影响会通过 startup、minimum up/down、ramping、DAG path、uplift 等传统 LMP 中不存在的结构传播。

换句话说：

\[
\boxed{
\text{Pałka is not a threat; it is the exact conceptual bridge you need cite.}
}
\]

你们可以把论文讲成：

> LMP literature has shown the regulatory value of bid-to-nodal-price derivatives; CHP literature has shown temporal vulnerability under simplified nonconvex models; **we bridge these two ideas under exact network-constrained full-trajectory CHP.**

这个叙事非常自然。

### 网络市场力的“空间传播”本身也已经很成熟

传统市场力理论早已知道 network topology 会改变 market power。Lin 和 Bitar 在 transmission-constrained LMP 市场中研究战略发电商的 supply-function competition，推导 Nash equilibrium 下 welfare loss 和 LMP markup 的上界，并说明 market share、Residual Supply Index 等结构变量可用于 ex ante market-power monitoring。citeturn19academia0

更新的研究甚至已经把“一个地点的行为影响多个地点价格”明确结构化。Graf 和 Wolak 2025 年提出 **residual demand hypersurface**，将单节点 residual demand curve 推广到网络市场，直接量化某供应商在一个地点改变 output 对**所有地点价格**的影响，并利用意大利 locational-pricing market 数据解释企业报价。citeturn9search1turn18search11

因此：

\[
\boxed{
\text{“市场力具有 spatial propagation”不是你们首次发现。}
}
\]

真正新意应该是：

> **传统 spatial market power 来自 transmission network；CHP 下 spatial propagation 还与 intertemporal nonconvex opportunity sets 相耦合。**

也就是传统研究关注：

\[
\text{network}
\rightarrow
\text{locational price leverage},
\]

而你们研究：

\[
\text{network}
+
\text{commitment}
+
\text{ramping}
\rightarrow
\text{spatio-temporal CHP leverage}.
\]

这才是正确差异。

### 传统 strategic bidding 已有非常成熟的 bilevel/game 范式

传统电力市场 strategic bidding 大量采用 bilevel/MPEC、supply-function equilibrium、Cournot、Stackelberg 或 learning。比如 networked supply-function equilibrium 文献已经直接研究网络拓扑如何影响战略供应商造成的效率损失；另有大量 strategic bidding 工作把 generator 作为 upper-level profit maximizer、ISO clearing 作为 lower level。citeturn19academia1turn18academia39

所以你们**暂时不做 global optimal strategic bidding 并不等于论文不完整**。

因为你们的问题实际上和传统 bilevel paper 不同：

> 传统战略竞价论文问“一个 price-maker 应该怎么报才能赚最多？”；

你们拟做的是：

> **监管者如何快速发现谁能够影响 CHP、这种影响通过什么时空机制传播，以及这种 leverage 是否真的能够转化成利润？**

前者是：

\[
\boxed{\text{strategy optimization}}
\]

后者是：

\[
\boxed{\text{market monitoring}}
\]

这是两个非常不同的 research questions。

## 当前最值得重视的文献缺口：不是单个模块空白，而是三个接口没有被连接起来

把上面的文献真正放到同一个矩阵中，差异会非常清楚。

| 代表研究 | CHP / 非凸定价 | 真实多时段启停 | ramp | network | bid-price sensitivity | profit/uplift strategic analysis |
|---|---|---|---|---|---|---|
| Sun–Gu–Wu, Market Power in CHP | ✓ | ✗ | ✗ | ✗ | ✗ | **✓** |
| Sun–Gu–Wu, Strategic Bidding in eLMP | ✓ | 简化 | — | 非核心 | ✗ | **✓** |
| Sun–Wu, Temporal Vulnerability | **✓** | **✗：全 horizon ON/OFF** | ✓ | 主模型 ✗ | **✓ \(T\times T\)** | 非核心 |
| Wang–Yang–Yu, Pricing Incentive Analysis | **✓** | 简化分析模型 | 非核心 | 非核心 | ✗ | **✓** |
| Byers–Eldridge | ✓ | **✓ multi-period** | 市场模型内 | 非研究核心 | ✗ | **✓ learned deviation** |
| Pałka, nodal-price derivatives | ✗，LMP | ✗ | ✓ | **✓** | **✓** | ✓ |
| Graf–Wolak | ✗，locational pricing | 非核心 | 非核心 | **✓** | residual-demand hypersurface | ✓ |
| Yu et al. network-flow CHP | **✓** | **✓** | **✓** | IEEE network test | ✗ | ✗ |
| Andrianesis et al. / Knueven et al. | **✓** | realistic UC | 可包含 | scalable clearing | ✗ | ✗ |
| 你们拟议框架 | **✓ exact** | **✓ DAG full trajectory** | **✓** | **✓** | **✓ spatio-temporal** | **✓ settlement-aware validation** |

上表中的各个已有能力分别有明确文献支撑：CHP market-power/profit 路线来自老师团队的 2020–2021 工作；temporal Jacobian 来自 *Temporal Vulnerability*；传统 LMP derivative screening 来自 Pałka；full-trajectory/ramping exact CHP 可见 Yu 等 network-flow formulations；exact scalable pricing 可见 Andrianesis 和 Knueven；network spatial market power 则可见 Graf–Wolak。fileciteturn0file6 fileciteturn0file5 citeturn9search0turn11search0turn13academia44turn13search2turn9search1

所以真正的 gap 不宜写：

> Existing studies do not consider networks.

这会被反例击穿。

也不宜写：

> Existing studies do not analyze strategic bidding under CHP.

更不宜写：

> No study uses price sensitivity to screen market power.

最稳健的 gap 应该写成：

> **Existing studies have separately developed strategic-bidding analysis for simplified CHP models, temporal price-vulnerability measures under restricted commitment structures, and exact CHP formulations for realistic unit constraints and transmission networks. However, these strands remain largely disconnected: market-power monitoring has not yet been systematically developed on top of an exact network-constrained CHP representation that retains full commitment trajectories and intertemporal operating constraints, nor has the resulting price vulnerability been systematically connected to settlement-aware profitable deviations.**

这个表述经过目前的文献检索，是明显比“首次考虑 network”稳健得多的。

而且这和老师的面上项目本身高度吻合。项目书当时就把“复杂网络、多时空约束下的市场力形成机理”“报价对价格、dispatch、uplift 的共同影响”和基于 Jacobian 的监管指标放在同一条研究主线里。fileciteturn0file2

## 解析 Jacobian 的文献定位：值得做，但创新必须落在 CHP 特有结构，而不是 parametric LP 本身

这里需要特别给你们未来方法部分“降预期但升精度”。

如果你们证明在 fixed active set / basis 内：

\[
\lambda^{CHP}(\theta)
\]

关于报价参数是 affine，因而：

\[
J
=
\frac{\partial\lambda^{CHP}}
{\partial\theta}
\]

可以用一次 basis factorization 加多个 RHS solves 得到，这当然是很有用的方法结果。

但：

\[
\boxed{
\text{“LP 在固定 basis 内做 sensitivity analysis”本身不可能是论文创新。}
}
\]

而且在 electricity market 中，Pałka 已经利用节点价格关于 offer prices 的 derivative matrix 做市场力 screening，并研究 derivative-constant regions。citeturn9search0

因此你们真正的方法创新要至少达到下面这一层：

\[
\boxed{
\text{parametric sensitivity of an exact full-trajectory CHP extended formulation}
}
\]

而不是普通 OPF sensitivity。

更具体地说，应该解决三个 CHP-specific 问题。

第一，你们当前 PWL perspective/epigraph 表达使报价参数可能不仅进入 objective，还进入 constraint matrix。因此一般 sensitivity 不是简单：

\[
B^{-T}c'_B,
\]

而是：

\[
B^\top y'
=
c_B'
-
B'^\top y.
\]

这个问题是你们自身 formulation 产生的。

第二，需要明确 price-selection / degeneracy。你们现在 finite-difference 实验已经显示 dominant signals 稳定，而许多弱信号靠近 critical boundaries；这恰好意味着最终理论更可能是：

\[
\boxed{
\text{piecewise-affine price sensitivity within critical regions}
}
\]

而在边界使用 directional/generalized sensitivity，而不是假设 global smoothness。你们现有研究计划已经意识到这一点。fileciteturn0file0

第三，也是最重要的：

\[
J_g
\]

必须有市场监管意义。

也就是不能到：

> “我们把 1000 次 LP solve 减成一次 factorization”

就结束。

需要继续到：

\[
\boxed{
\text{fast screening}
\rightarrow
\text{profit-aware validation}.
}
\]

这正好符合 T-EMPR 的 scope。官方明确欢迎 market power、market monitoring、bidding strategies、pricing/settlement，但明确警告不能把 optimization technique 本身作为主要贡献、市场问题只是 incidental application。citeturn10search0turn16view5

所以最好的论文关系是：

\[
\text{analytic sensitivity}
=
\text{regulatory tool},
\]

而不是：

\[
\text{market power}
=
\text{optimization algorithm application}.
\]

## Price vulnerability 与 profitable market power 的关系，可能是最重要的经济创新，但必须避开已有 incentive literature

目前你们实验发现的：

\[
VI_g\text{ 高}
\not\Rightarrow
\Delta\Pi_g\text{ 高},
\]

确实很有意思。

但相关文献告诉我们，不能把它包装成泛泛的：

> “价格影响不等于利润”。

因为传统市场力定义本来就强调**profitably** influence price；Pałka 已经同时讨论 price derivatives 和 participant/group profits；非凸市场 incentive 文献也已经研究 strategic bidding 对利润、LOC 和 compensation 的影响。citeturn9search0turn17search0

你们真正值得推到理论层的，是 CHP 下这个区别**为什么结构性地更重要**。

对于 generator \(g\)：

\[
\Pi_g
=
\lambda_{n(g)}^\top p_g
+
U_g
-
C_g^{true}.
\]

局部变化可写成：

\[
d\Pi_g
=
p_g^\top d\lambda_{n(g)}
+
\lambda_{n(g)}^\top dp_g
+
dU_g
-
dC_g^{true}.
\]

而 VI 本质上只量化：

\[
d\lambda.
\]

所以它缺失：

\[
dp_g,\qquad
dU_g,\qquad
dC_g^{true},
\]

甚至还把大量发生在 generator 不暴露的 bus/hour 上的价格变化纳入 norm。

这使得你们的当前实验——G5 price influence 很大但 observed profit gain 较小；空间 load redistribution 后局部 VI 下降而利润上升；warm-up 改变 commitment opportunity 后又产生反向变化——可以被组织成一个**机制性问题**：

\[
\boxed{
\text{When does system-wide CHP price leverage translate into generator-specific economic leverage?}
}
\]

这比单纯说：

> VI 和利润相关性不高

强得多。

而且它自然连接老师过去两项工作：

\[
\text{2020: maximal profitable market power}
\]

和

\[
\text{2021: temporal price vulnerability}.
\]

你们可以把新论文理解为：

\[
\boxed{
\text{linking the two notions under realistic CHP}.
}
\]

这是我认为目前最值得经营的一条 intellectual contribution。

Wang–Yang–Yu 2023 的文章则应该作为这里的重要前置文献：它已经表明 nonconvex pricing、compensation、dispatch-following 和 truthful bidding 之间存在复杂关系。你们不是首次发现“补偿会影响战略收益”，而是进一步揭示：

> **在完整多时空 CHP 中，price-based screening 和 settlement-aware profitable market power 为什么可能系统性背离，以及监管上该如何处理这种背离。**

citeturn17search0turn17search1

这就足够不同。

## 面向 T-EMPR 的 Related Work 应该怎么写，以及哪些论文是“必须正面回应”的

T-EMPR 自 2023 年创刊以来已经发表大量“市场机制 + 数学模型 + numerical economic analysis”的文章，而不都是纯经济理论。例如 *Uncertainty-Informed Renewable Energy Scheduling* 使用 scalable bilevel framework 设计 VRES day-ahead bids，并在 1576-bus NYISO 系统上分析 system cost 和 market-price volatility；*Operating Strategy of LNG Terminal* 则采用 leader–follower bilevel/game framework 分析战略参与者对耦合电气市场的影响。citeturn14search0turn14search4

这说明 T-EMPR 的研究范式并不要求“必须有五个定理”。真正重要的是：

\[
\boxed{
\text{important market question}
+
\text{defensible methodology}
+
\text{economic mechanism}
+
\text{policy/monitoring implication}.
}
\]

这也与该刊官方 scope 的措辞完全一致。citeturn10search0

你们文章如果最终形成：

\[
\text{exact CHP model}
\rightarrow
\text{analytic market-monitoring sensitivity}
\rightarrow
\text{mechanism decomposition}
\rightarrow
\text{profitable-deviation validation},
\]

其实会比纯 bilevel strategic-bidding paper 更贴合“market monitoring”。

### 推荐的 Related Work 结构

Related Work 不建议按照年份流水账，而应该分成三个段落。

第一段写 **Non-convex pricing and CHP computation**。

可以从 Schiro 等的 CHP formulation/implementation challenge 开始，然后引用 Hua–Baldick 的 convex primal、Yu 等的 integral/network-flow formulations、Andrianesis 的 DW exact method、Knueven 等的 scalable algorithm。最后一句收束：

> 这些研究显著提升了复杂 UC 条件下 CHP 的计算能力，但主要关注 price formation 和 computational tractability，而非 strategic market monitoring. citeturn13search0turn12academia8turn11search0turn13academia44turn13search2

第二段写 **Strategic behavior and incentive properties under non-convex pricing**。

这里必须放：

- Sun–Gu–Wu, *Strategic Bidding in eLMP*；
- Sun–Gu–Wu, *Market Power in CHP*；
- Sun–Wu, *Temporal Vulnerability*；
- Wang–Yang–Yu, *Pricing Incentive Analysis*；
- Byers–Eldridge, auction incentive compatibility/self-scheduling。

这一段最后收束：

> 现有工作已经证明 CHP 不消除 strategic incentives，并分别从 maximal profit、markup、truthful bidding、temporal Jacobian 和 learned deviations 等角度研究风险；但其 analytical market-power models 通常依赖简化的 commitment/network structure，而较真实 multi-period studies 又没有建立 CHP bid-to-price 的可解释时空监管结构。fileciteturn0file6 fileciteturn0file5 citeturn20search0turn17search1turn16view2

第三段写 **Market-power monitoring in networked electricity markets**。

这里放 Pałka、Lin–Bitar、Graf–Wolak 等：

> LMP literature has developed structural indices, network equilibrium models, nodal-price derivatives, and residual-demand approaches for monitoring spatial market power. However, these approaches are built around convex dispatch/LMP price formation and therefore do not capture the startup/uplift/intertemporal nonconvex channels intrinsic to CHP. citeturn9search0turn19academia0turn9search1

然后才是你们的 gap sentence：

> **Our work connects these previously separate strands by developing market-power monitoring on an exact network-constrained CHP representation with full commitment trajectories, thereby enabling spatio-temporal bid-impact analysis and settlement-aware validation of whether price vulnerability translates into profitable unilateral deviations.**

这句话目前是我认为最稳的 related-work landing point。

### 投稿前最需要精读并正面比较的文献

下面这些不是“可以引用”，而是我认为**审稿人很可能期待你们知道**的核心集合。

| 文献 | 为什么必须读 | 你们需要回答它什么 |
|---|---|---|
| Schiro et al., 2016, TPWRS | CHP structure/counterintuitive properties | 你们不是又做 CHP property case study |
| Hua & Baldick, 2017, TPWRS | primal exact CHP foundation | DAG sensitivity 相比标准 primal formulation 多了什么 |
| Yu et al., 2022, TPWRS | network-flow CHP + ramp + initial status + startup limit | DAG/full trajectory 的具体结构差异 |
| Andrianesis et al., 2022, TPWRS | exact DW CHP | 为什么你们的 direct LP 更适合 repeated monitoring |
| Knueven et al., 2022 | industrial-scale CHP | 不要夸大“过去 CHP 算不了” |
| Sun–Gu–Wu, 2020/21 | strategic bidding/profit/market power | 你们不是首次 CHP strategic analysis |
| Sun–Wu, 2021 | temporal Jacobian/VI | **这是最直接 predecessor** |
| Wang–Yang–Yu, 2023 | nonconvex pricing incentive/truthful bidding | 你们的 profit-VI link 有何新增机制 |
| Byers–Eldridge, 2022/24 | strategic self-scheduling under nonconvex prices | 你们不是首次 realistic multi-period strategic behavior |
| Pałka, 2017 | nodal-price derivative screening | **解析 Jacobian 绝不能泛泛声称首次** |
| Lin–Bitar | structural network market power | 与 RSI/structural screening 的关系 |
| Graf–Wolak, 2025 | spatial network market power | 你们 spatial propagation 有何 CHP-specific 新意 |
| Jiang–Wu, 2026/27 | 最新 CHP structural decipher | 与老师当前 CHP structural research chain 对齐 |

这些工作的核心信息分别可由原始/出版来源核实。citeturn13search0turn12academia8turn11search0turn13academia44turn13search2turn17search1turn16view2turn9search0turn19academia0turn9search1turn8search4

## 对你们当前论文最实际的结论：创新点应该收敛到这四层，而不是继续扩研究范围

综合整个文献地图，我现在会把潜在 contribution 明确分成四层。

**第一层是 market-modeling gap。**

不是“首次有 network”，而是：

\[
\boxed{
\text{unilateral market-power monitoring under exact full-trajectory network-constrained CHP}.
}
\]

这里的关键词必须连在一起才有意义。

**第二层是 methodological gap。**

不是：

\[
\text{首次计算 Jacobian},
\]

而是：

\[
\boxed{
\text{从 exact DAG-CHP 的 parametric LP structure 直接获得 spatio-temporal CHP sensitivities}
}
\]

并处理：

- full commitment trajectories；
- network duals；
- PWL bid parameters；
- active-region changes；
- degeneracy。

如果最终确实能实现：

\[
\text{one CHP solve}
+
\text{one factorization}
+
\text{multiple RHS solves},
\]

并显著快于 finite differences，那么它会是一个扎实的 **market-monitoring algorithmic contribution**。但必须和 Pałka 的 LMP derivative framework 正面比较，而不能把“derivative screening”本身写成新思想。citeturn9search0

**第三层是 economic-mechanism gap。**

这一层我认为甚至比算法更有价值：

\[
\boxed{
\text{CHP price vulnerability}
\neq
\text{exercisable profitable market power}.
}
\]

但贡献应当写成“解释二者为什么在 realistic CHP 下分离”，而不是只报告一个相关系数。

你们需要利用：

\[
d\Pi
=
\underbrace{p^\top d\lambda}_{\text{price exposure}}
+
\underbrace{\lambda^\top dp}_{\text{dispatch channel}}
+
\underbrace{dU}_{\text{uplift channel}}
-
\underbrace{dC^{true}}_{\text{true-cost channel}}
\]

解释现在 P0、load-shift、warm-up 中已经观察到的 divergence。相关 nonconvex incentive 文献已经证明 compensation 与 strategic profits 的关系复杂，因此你们的新意必须来自 **full spatio-temporal mechanism attribution**。citeturn17search0turn17search1

**第四层是 regulatory contribution。**

最终最适合 T-EMPR 的落点不是一个新 VI，而是：

\[
\boxed{
\text{Stage I: fast price-leverage screening}
}
\]

\[
\Downarrow
\]

\[
\boxed{
\text{Stage II: settlement-aware profit validation}.
}
\]

这相当于承认：

> Jacobian/VI 很适合回答“谁能影响 CHP”，但不能独立回答“谁能利用这种影响获利”。

这种结论从监管角度反而比声称“VI 就是市场力”更成熟，也更符合 T-EMPR 对 market power、market monitoring、bidding、pricing 与 settlement 的明确定位。citeturn10search0

因此，我会把现在的文献综述最终浓缩成一句论文级定位：

> **The CHP literature has separately advanced exact pricing formulations, strategic-bidding analysis, and temporal vulnerability assessment, while the broader electricity-market literature has developed network-based and sensitivity-based market-power monitoring under LMP. What remains missing is an integrated framework that exploits an exact network-constrained, full-trajectory CHP representation to characterize how strategic bids propagate across both time and location and to determine when such price leverage translates into profitable market power through energy, dispatch, and uplift channels.**

这比“我们首次研究 CHP market power”安全得多，也比“我们把 Jacobian 扩展到 network”明显更有力度。

更关键的是，它与我们一路讨论下来的研究方案**没有偏离**：你们此前已经完成的 finite-difference experiments 不是走错路，而是在为第三个“生死问题”——

\[
VI_i\uparrow
\stackrel{?}{\Longrightarrow}
\Delta\Pi_i\uparrow
\]

——积累现象证据；现在文献调研反而进一步说明，**下一步最应该补的确实是第一个生死问题：exact DAG-CHP 下的解析 parametric sensitivity**，而不是继续新增 scenario、合谋、capacity withholding 或其他报价产品。这样最终才能把现有“现象发现”升级为一条完整的 **theory → screening method → mechanism → profit validation → market-monitoring implication** 研究链。