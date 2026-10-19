# 统一符号与结算定义

|符号|英文术语|定义/单位|
|---|---|---|
|δ|Offer price adder|G1全日增量成本段的统一绝对加数，USD/MWh；不是价格涨幅或利润率|
|p_g,t^UC|Cleared generation|满足完整整数启停与网络约束的ISO出清，MW|
|p_g,t^SS|Unit best-response generation|给定价格及申报成本下单机最佳自调度，MW；集合不要求满足系统平衡|
|p_g,t^CHP|Convexified pricing point|CHP LP的凸化定价点，MW；一般不能执行，不作为结算出力|
|λ_n,t^CHP|Nodal convex hull price|节点CHP，USD/MWh|
|λ_t^E|System energy-price component|同一选价规则下系统平衡乘子，USD/MWh|
|λ_n,t^C|Congestion-price component|−Σ_l H_l,n(μ_l,t^+−μ_l,t^−)，USD/MWh|
|Q_g|Generation subject to the offer increase|Σ_t(p_g,t−Pmin_g u_g,t)Δt，MWh；本案例Δt=1h|
|R_g|Energy revenue|Σ_t λ_n(g),t^CHP p_g,t^UC Δt，USD|
|U_g|Uplift payment|当前模型的完整申报lost-opportunity-cost补偿，USD；不替换为任意ISO的make-whole规则|
|C_g|Actual generation cost|按真实成本核算实际UC轨迹，包括增量电量、最低出力/在线成本、真实启停，USD|
|Ĉ_g|Offered generation cost|战略机组为C_g+δQ_g，其他机组如实报价，USD|
|Π_g|Actual profit|R_g+U_g−C_g，USD|
|ΔΠ_g|Additional profit|Π_g(δ)−Π_g(0)，同一市场条件下各自真实报价为基线，USD|
|Π̂_g^SS|Best offered self-scheduling profit|max_s{Σλp−Ĉ_g(s)}，USD|
|Δ^TX|Transmission-side settlement adjustment|Σ_l,t[μ^+(F−f^UC)+μ^−(F+f^UC)]≥0，USD；不等于拥塞电价或机组uplift|

U_g=Π̂_g^SS−(R_g−Ĉ_g^UC)，Π_g=Π̂_g^SS+δQ_g^UC。局部共同方案区间内，dΠ_g/dδ=Σ_t p_g,t^SS dλ_t^E/dδ+Σ_t p_g,t^SS dλ_n(g),t^C/dδ+Q_g^UC−Q_g^SS。价格/物理出清切换时另计真实利润跳变；各项为同一路径的会计分解，不是独立因果处理。

沿用旧稿拉格朗日正乘子μ^±≥0；COPT保存的≤型行乘子非正，读取时转换μ^±=−row_dual^±。线路流量采用f=H(p−D)，节点价格λ^CHP=λ^E−Hᵀ(μ^+−μ^−)。主结果始终保留原bus 1参考。

战略报价下网络恒等式为Σ_g U_g+Δ^TX=Ĉ_sys^UC−Ĉ_sys^CHP，两侧目标均用申报成本。机组Π_g仍用真实C_g。本目录不将旧稿的真实报价数值基线与当前战略报价档案合并。
