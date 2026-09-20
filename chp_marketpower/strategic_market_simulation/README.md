# 有限标量报价利润检查

`profit_sweep.py` 复用 `chp_energy` 的物理 UC、exact CHP 和单机自调度。它对某机组的标量加价重新出清，并计算 `能量收入 + 按申报成本结算的 uplift − 不变真实成本`。公开入口为 `../run_profit_validation.py`；当前只做有限网格，不声称求得最优策略，也不把价格敏感度直接当成利润。
