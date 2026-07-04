"""
benchmarks — 凸包定价基准对比方法包

包含与 CHP 原空间精确求解框架对比的定价方法：
  - lmp_pricing.py         : 方法一：传统边际电价（固定启停 LP）
  - lagrangian_relaxation.py: 方法二：plain 拉格朗日次梯度基准
  - level_method_pricing.py : 方法二扩展：level method 对偶迭代基准
  - mirp_pricing.py        : 方法三：M-IRP（整数松弛定价，LP 松弛）
  - dantzig_wolfe_pricing.py: Dantzig-Wolfe column-generation CHP
  - xiao_explicit_pricing.py: Xiao et al. 状态转移 two-LP M-CHP
  - comparison_runner.py   : 对比驱动器，统一调用并输出对比表（含 FTR 分解）

详细说明见同目录 AGENTS_benchmarks.md。
"""
