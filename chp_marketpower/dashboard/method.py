"""Explain the implemented parametric CHP method using the selected archived case."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def method_page(s, q, node, hour, chart):
    st.subheader('固定电力系统模型，沿一个报价方向构建定价查询器')
    st.write('机组组合包含启停状态、最小开停机时间、出力上下限和爬坡约束，因而是非凸优化问题。'
        '凸包定价（CHP）使用机组可行集的凸包和相应成本凸包络，并保留系统功率平衡、线路潮流约束。'
        '当前底层复用已有的启停区间/DAG网络流表示与绝对出力坐标，不将这种表示作为本研究的新贡献。')
    st.latex(r'v(\delta)=\min_{x\in\mathcal P}(c^0+\delta d)^\top x,\qquad \delta=\rho c_{\rm ref},\quad 0\leq\rho\leq0.5')
    st.write('负荷、网络、机组物理参数及初始状态固定；只有指定机组全天或指定单小时的增量边际报价改变。'
        '这里是统一增加δ（USD/MWh），不是各成本段同时乘以1+ρ。150个方向是150个独立的一维问题，不是24维联合报价模型。')
    st.write('直觉：每个可行出力方案的申报成本都是一条直线；取所有直线的最低值，得到凹分段仿射的CHP最优目标值。'
        '目标值斜率反映凸化最优方案对该报价方向的成本暴露量，不等于实际机组组合的发电量，也不能据此断言所有物理约束的活跃状态不变。')
    st.subheader('区间最优性：先验证整段，再进行端点插值')
    st.latex(r'x^\star\in\arg\min_{x\in\mathcal P}c(a)^\top x\;\cap\;\arg\min_{x\in\mathcal P}c(b)^\top x')
    st.write('如果同一原始可行解在两端都最优，其成本直线在整段都达到最优值。'
        '在线性规划标准形式中，对偶约束为Aᵀy≤c(δ)；c(δ)也随δ仿射变化。'
        '因此要同时插值完整对偶解和对应的目标系数，而不是把不同报价下的价格视作位于同一个固定的对偶可行域。'
        '实现中包含全部等式、不等式及变量上下界乘子。')
    st.latex(r'\theta=\frac{\delta-a}{b-a},\quad y(\delta)=(1-\theta)y_a+\theta y_b,\quad \lambda^{\rm sel}(\delta)=\mathcal L y(\delta)')
    st.write('完整对偶插值保持可行，结合共同原始最优解和强对偶性，得到区间内最优性；'
        '固定线性投影ℒ再给出CHP节点电价。浮点实现采用声明容差下的数值验证。'
        '这构造了一条合法的选定电价路径，不证明价格唯一，不要求与另一直接求解返回的对偶价格逐项相等。')
    intervals = s.get('validation',{}).get('optimality_intervals',[])
    if intervals:
        k = min(np.searchsorted([r['right'] for r in intervals],q['delta'],side='right'),len(intervals)-1)
        r = intervals[k]
        st.subheader(f'真实算例：{s["id"]}，原始最优性区间 {k+1}')
        st.caption('θ只演示该归档区间内的价格计算，不改变左侧报价，也不触发新的机组组合或结算。')
        theta = st.slider('区间内相对位置 θ',0.,1.,.5,.01,key=f'theory_theta_{s["id"]}')
        a,b = r['left'],r['right']
        series = np.asarray(s['prices'])[:,node,hour]
        pa,pb = np.interp([a,b],s['price_boundaries'],series)
        delta = (1-theta)*a+theta*b
        selected = np.interp(delta,s['price_boundaries'],series)
        fig = go.Figure(go.Scatter(x=[a,b],y=[pa,pb],mode='lines+markers',name='合法选定电价'))
        fig.add_scatter(x=[delta],y=[selected],mode='markers',marker=dict(size=12,color='#BA7B25'),name='当前插值')
        fig.update_layout(title=f'节点{node+1}，第{hour+1}小时',xaxis_title='边际报价加数 δ (USD/MWh)',yaxis_title='CHP节点电价 (USD/MWh)',height=310)
        chart(fig,'theory_segment')
        st.write(f'δ∈[{a:.12g}, {b:.12g}] USD/MWh；ρ∈[{100*a/s["reference_slope"]:.9g}%, {100*b/s["reference_slope"]:.9g}%]。')
        st.code(f'λ = (1 − {theta:.2f}) × {pa:.9f} + {theta:.2f} × {pb:.9f} = {selected:.9f} USD/MWh')
        st.caption(f'该原始区间共同原始解的最大端点目标间隙：{r["common_primal_gap"]:.3e} USD。'
            '显示的是实际归档电价，不是示意数据；压缩仅合并不改变选价路径的共线段。')
    st.subheader('Bracket-and-Certify 如何寻找区间')
    st.latex(r'L_{a,b}(\delta)\leq v(\delta)\leq U(\delta)=\min_{x_i\in\mathcal P}(c^0+\delta d)^\top x_i')
    st.write('端点对偶下界的弦线给出区间下界L；已求出的原始可行方案给出上界U。'
        '算法优先细分上下界差距较大的区间，重新求解CHP并保存完整原始—对偶见证。'
        '只有共同原始最优性、完整对偶残差和全范围覆盖均通过，才允许在线查表。'
        '单纯目标值接近或两个电价点连线，都不足以建立合法价格映射。')
    st.subheader('电价、机组组合与收益结算是三层问题')
    st.latex(r'\Pi_j^{\rm true}=\sum_t\lambda_{n(j),t}^{\rm sel}p_{j,t}^{\rm UC}+LOC_j^{\rm rep}-C_j^{\rm true}')
    st.write('P：节点电价与CHP最优目标值由现有Oracle查询。U：可执行开停机和出力来自网络约束机组组合，'
        '不能用凸化出力代替。S：基于申报成本的机会成本损失（LOC）补偿需要逐机组自调度。'
        '这里采用研究中声明的LOC结算规则，不代表所有实际电力市场的补偿办法。')
    with st.expander('下一层研究：自调度最大盈余的参数化表示（尚未实现完整经济结果Oracle）'):
        st.latex(r'M_j^{\rm rep}(\delta)=\max_{z_j\in X_j}\{\lambda_j^{\rm sel}(\delta)^\top p_j(z_j)-C_j^{\rm true}(z_j)-\delta D_j(z_j)\}')
        st.write('在每个固定的电价仿射段内，可行的单机计划盈余为仿射函数；其逐点最大值为凸分段线性函数。'
            'D只计战略机组在调整时段内的增量出力暴露量，其余机组为0。结合已验证的UC区域与该盈余映射，'
            '才可用Π=M+δDᵁᶜ快速查询利润。当前利润来自直接结算或精确报价缓存，不插值利润样本。')


def validation_page(s, live, rows):
    st.subheader('当前价格映射的数值验证记录')
    v = s.get('validation',{})
    st.write(f'构建状态：{v.get("build_status","未归档")}；独立验证：{v.get("independent_status","未归档")}；'
        f'独立报价点：{v.get("independent_points",0)}。普通电价查询不重新运行这些检查。')
    st.caption('独立验证与原始见证哈希绑定：'+('已绑定' if v.get('source_bound') else '旧验证未绑定；不能仅凭旧通过标记认为已满足新目录发布条件。'))
    names = {'primal_feasibility':'原始可行性','dual_sign':'对偶乘子符号','stationarity':'对偶驻点残差',
        'duality_gap':'原始—对偶目标间隙 (USD)','row_complementarity':'约束互补残差','bound_complementarity':'上下界互补残差',
        'objective_reconstruction':'目标值重构误差 (USD)','price_projection':'节点电价投影误差 (USD/MWh)',
        'value_error_usd':'独立CHP最优目标值误差 (USD)','selector_dual_gap_usd':'选价完整对偶目标间隙 (USD)',
        'selector_stationarity':'选价完整对偶驻点残差','selector_dual_sign':'选价对偶符号残差',
        'selector_complementarity':'选价互补残差','selector_price_projection':'选价节点电价投影误差 (USD/MWh)',
        'direct_complete_dual_gap_usd':'独立求解对偶目标间隙 (USD)',
        'direct_complete_dual_stationarity':'独立求解驻点残差'}
    records = []
    for stage,key in [('原始端点','endpoint_maximums'),('独立区间内部点','independent_maximums')]:
        for metric,value in v.get(key,{}).items():
            if metric in names:
                records.append(dict(阶段=stage,指标=names[metric],最大残差=value,
                    声明上限=v.get('limits',{}).get(metric)))
    if records: st.dataframe(pd.DataFrame(records),hide_index=True,use_container_width=True)
    st.caption(f'共同原始解最大端点目标间隙：{v.get("maximum_common_primal_gap_usd")} USD。'
        '残差是浮点数值证据，不是符号精确证明；不同残差的量纲不能混为一个误差指标。')
    gap = v.get('independent_maximums',{}).get('selector_vs_direct_price_gap_usd_per_mwh')
    if gap is not None:
        st.info(f'独立求解器选价与归档选价最大差异为{gap:.6g} USD/MWh。'
            '对偶解可能不唯一；该差异不是正确性失败判据。正确性检查完整对偶可行性、最优性及电价投影。')
    st.subheader('零加价基准与跨方向比较')
    baseline = s.get('baseline_audit')
    if baseline:
        st.write(f'参考方向：{baseline["reference_scenario"]}；零加价电价最大差异：'
            f'{baseline["maximum_price_difference_usd_per_mwh"]:.6g} USD/MWh；'
            f'目标值差异：{baseline["value_difference_usd"]:.3e} USD。')
        st.warning('价格变化和利润增量均相对于本方向的零加价选价及选定UC方案。'
            '未统一基准选价、并列最优调度与结算规则之前，不将不同方向的利润增量直接排名。')
    st.subheader('机组组合与结算核对')
    if live: st.json(live.get('physical_audit',{}),expanded=False)
    elif s['physical_regions']:
        st.write(f'已归档{len(s["physical_regions"])}个共同最优UC区域；区域端点按全局MIP下界核对，不将小成本误差解读为小出力误差。')
    else: st.info('本方向尚未归档UC区域；不以电价验证代替可执行机组组合验证。')
    if rows:
        residual = max(abs(r['energy_revenue']+r['reported_uplift']-r['true_cost']-r['true_profit']) for r in rows)
        st.write(f'当前全部机组“电能量收入 + LOC补偿 − 实际运行成本 − 利润”最大残差：{residual:.3e} USD。')
    else: st.info('当前报价的机组结算尚未计算，不报告虚构的利润核对结果。')
    st.json({k:s[k] for k in ('model_sha256','price_selector_sha256','raw_witness_sha256','source_oracle','export_validation','identity_scope')},expanded=False)
