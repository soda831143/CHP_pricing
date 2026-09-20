# 2021 Temporal Vulnerability 基准对齐记录

目标是检验新 DAG-CHP 在旧论文的简化条件下能否重现 Jacobian 形态与 VI 排名；**当前 `case6ww` 不能充当这项复现**。参数来自 [Sun、Wu (2021), Table 3，PDF 第 10 页](../../../../primal/Temporal%20Vulnerability%20Assessment%20for%20Convex%20Hull%20Pricing.pdf)。原文功率单位 MWh、成本单位美元，方括号表示三个时段均采用相同参数。

| 机组 | 初始出力 | 上爬坡 | 下爬坡 | 启动费 | 线性可变成本 | 最小出力 | 最大出力 |
|---|---:|---:|---:|---:|---:|---:|---:|
| G1 | 200 | 20 | 20 | 300 | 2.1 | 20 | 800 |
| G2 | 0 | 60 | 40 | 80 | 3.0 | 20 | 550 |
| G3 | 0 | 40 | 70 | 109 | 3.7 | 0 | 560 |
| G4 | 80 | 100 | 100 | 125 | 4.5 | 50 | 400 |
| G5 | 100 | 100 | 150 | 50 | 2.7 | 100 | 300 |
| G6 | 0 | 200 | 200 | 10 | 5.7 | 0 | 200 |

直接宣称“复现”还缺两项关键信息／口径对齐：

1. 论文 Figure 5 的四类三时段需求只作为曲线展示，正文未给出用于 Figure 6 VI 曲线的逐点精确需求向量。读图数字化只能形成近似情景，不能据此要求逐点重现 VI。
2. 原模型令每台机组在整个三时段窗口内**始终 ON 或始终 OFF**，启动费至多收一次；本项目 DAG 模型允许窗口内 ON/OFF 转换，并显式区分启动／停机爬坡。即使录入同一张参数表，也不是同一可行域。

因此下一步应先取得原始需求数组或作者计算脚本，再把“整段 ON/OFF”限制作为**基准专用模式**实现并检验成本/初始状态，随后比较原论文的 $T\times T$ Jacobian 与 VI。若只能读图得到近似负荷，结果只能标记为 *paper-inspired qualitative check*，不能标记为 exact replication。当前不向正式代码库注入猜测的需求数据。

## 对新稿创新边界的直接影响

这篇最近邻工作已经覆盖“报价参数 $\rightarrow$ CHP 价格 Jacobian $\rightarrow$ temporal VI”及其高效计算。因此当前项目已有的 finite-difference Jacobian 是复现/验证基线，不是论文终点；把输出从 $T\times T$ 扩到 $N_BT\times T$ 也不足以单独构成主贡献。

新稿必须至少推进到两个层次：一是给出 derivative 在多大报价区间内有效、何处因 congestion/ramping/interval 活动集变化而切换，即 price-impact regimes；二是把价格影响与重新结算后的真实利润比较，解释为什么高 leverage 不必然对应高 exercisable market power。严格复现所缺数据不阻止这两项工作，但投稿前必须把本文件中的“精确复现缺口”保留为清楚边界。
