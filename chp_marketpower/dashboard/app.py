"""Run from chp_marketpower: python -m streamlit run dashboard/app.py --server.address 127.0.0.1"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.data import EXPORTS, evaluate, get_scenario, load_export, sampled_settlement
from dashboard.service import cached, solve

st.set_page_config(page_title='CHP Oracle Explorer', page_icon='⚡', layout='wide')
st.markdown('''<style>
.stApp {background:#F5F7F8;color:#203442} h1,h2,h3 {color:#203442}
[data-testid="stSidebar"] {background:#E9EFF1} .block-container {padding-top:2rem}
[data-testid="stMetricValue"] {font-family:Consolas,monospace;color:#087E8B}
</style>''', unsafe_allow_html=True)


@st.cache_data
def archive(version):
    return load_export()


def chart(fig, key):
    fig.update_layout(template='plotly_white', font=dict(family='Segoe UI, sans-serif', color='#203442'),
                      margin=dict(l=45, r=25, t=35, b=40), paper_bgcolor='#F5F7F8')
    st.plotly_chart(fig, use_container_width=True, key=key)


def heat(z, title, key, colors='Viridis', unit='$/MWh'):
    scale = max(1e-6,float(np.max(abs(np.asarray(z))))) if colors=='RdBu' else None
    fig = go.Figure(go.Heatmap(z=z, x=list(range(1, 25)), y=list(range(1, len(z)+1)),
                             colorscale=colors, colorbar=dict(title=unit),
                             zmin=-scale if scale is not None else None,zmax=scale))
    fig.update_layout(title=title, xaxis_title='小时', yaxis_title='节点 / 机组编号', height=340)
    chart(fig, key)


def exact_rows(s, q, region):
    try:
        result = cached(s, q['delta'], region)
    except ValueError as error:
        st.warning(str(error))
        result = None
    return (result['rows'], 'solved_on_demand', result) if result else (
        sampled_settlement(s, q['delta'], region), 'sampled_only', None)


def set_bid(value):
    st.session_state['bid_pct'] = float(value)
    st.session_state['bid_slider'] = float(value)


st.title('CHP Oracle Explorer')
st.caption('连续报价 · 合法选价 · 物理执行 · 申报 LOC 结算 | 本地研究工作台')
if not (EXPORTS/'manifest.json').exists():
    st.error('缺少已验证的网页数据，请先执行 python -m dashboard.export。')
    st.stop()
data, manifest = archive((EXPORTS/'manifest.json').stat().st_mtime_ns)
if 'bid_pct' not in st.session_state:
    set_bid(0.)
with st.sidebar:
    st.subheader('选择报价方向')
    case = st.selectbox('节点系统', ['30', '118'])
    model = data['models'][case]
    count = len(model['generators'])
    target = st.selectbox('战略机组', list(range(count)), index=0 if case == '30' else 10,
        key=f'target_{case}', format_func=lambda i: f'G{i+1} · 节点 {model["gen_bus_map"][i]+1}')
    direction = st.radio('报价调整时段', ['全部 24 小时', '单小时'])
    hour = st.selectbox('调整第几小时', list(range(1, 25))) if direction == '单小时' else None
    s = get_scenario(data, case, target, hour)
    st.number_input('报价加数 / 参考斜率 (%)', min_value=0., max_value=50.,
                    step=0.1, format='%.9f', key='bid_pct',
                    on_change=lambda: set_bid(st.session_state['bid_pct']))
    st.slider('拖动报价 (%)', 0., 50., step=0.1,
              key='bid_slider', on_change=lambda: set_bid(st.session_state['bid_slider']))
    st.caption('δ = ρ × reference slope；全部 PWL 增量段统一加 δ，不改变空载/启停费用。')
    st.button('真实报价 0%', on_click=set_bid, args=(0.,))
    st.button('范围上界 50%', on_click=set_bid, args=(50.,))
    if s and len(s['physical_regions']) > 1:
        roots = [r['right'] for r in s['physical_regions'][:-1]]
        root = st.selectbox('物理 UC 切换阈值', roots,
            format_func=lambda d:f'{100*d/s["reference_slope"]:.9f}%')
        st.button('跳至所选 UC 边界', on_click=set_bid, args=(100*root/s['reference_slope'],))
    st.caption('固定：tight PTDF · 24h · 3段成本 · 冷启动。未建图方向不返回其他地图。')
if s is None:
    st.warning('not_available：该机组/时段没有完整价格地图。请选择 30-G1/G2 全日、30-G1 第1小时或 118-G11 全日。')
    st.info('新增方向须单独建图和验证；本页不会启动批量实验或外推已有价格。')
    st.stop()
q = evaluate(s, st.session_state['bid_pct']/100)
base = evaluate(s, 0.)
if q['snapped_to_boundary']:
    st.caption(f'报价接近存档 UC 边界，已明确对齐：请求 δ={q["requested_delta"]:.12g} → 实际 δ={q["delta"]:.12g}。')
regions = q['physical']
if len(regions) > 1:
    st.warning('此报价有两套并列最优物理执行。分别查看两侧方案；不平均出力或利润，也不声称唯一调度。')
region = st.radio('选择物理方案', [r['region_index'] for r in regions], horizontal=True,
    format_func=lambda k:f'区域 {k+1} · '+('左侧方案' if k == regions[0]['region_index'] else '右侧方案')) if len(regions)>1 else (
    regions[0]['region_index'] if regions else None)
rows, settlement_status, live = exact_rows(s, q, region)
base_region = base['physical'][0]['region_index'] if base['physical'] else None
baseline_rows, _, baseline_live = exact_rows(s, base, base_region)
physical = next((r for r in regions if r['region_index'] == region), None)
p = np.asarray(physical['output']) if physical else np.asarray(live['output']) if live else None
u = np.asarray(physical['commitment']) if physical else np.asarray(live['commitment']) if live else None
st.caption(f'{s["id"]} | δ={q["delta"]:.9f} $/MWh | ρ={100*q["rho"]:.9f}% | '
    f'P: precomputed_verified · U: {q["uc_status"] if not live else live["uc_status"]} · '
    f'S: {settlement_status if rows else "not_available"}')
st.caption(f'Model {s["model_sha256"][:16]} · Selector {s["price_selector_sha256"][:16]} · '
    f'{s["value_regions"]} value regions / {s["price_segments"]} selected-price segments')

ruler = go.Figure()
ruler.add_scatter(x=np.asarray(s['price_boundaries'])/s['reference_slope']*100, y=[1]*len(s['price_boundaries']),
    mode='markers', marker=dict(symbol='line-ns', size=13, color='#68818E'), name='选价分段')
ruler.add_scatter(x=[r['right']/s['reference_slope']*100 for r in s['physical_regions'][:-1]],
    y=[0]*max(0,len(s['physical_regions'])-1), mode='markers', marker=dict(symbol='diamond',color='#BA7B25',size=9), name='物理 UC 切换')
ruler.add_vline(x=q['rho']*100, line_color='#087E8B', line_width=3)
ruler.update_layout(height=150, xaxis=dict(title='报价加数 / 参考斜率 (%)',range=[0,50]),
    yaxis=dict(tickvals=[0,1],ticktext=['物理执行','选定价格']), legend=dict(orientation='h',y=1.8))
chart(ruler, 'ruler')
view = st.columns(3)
node = view[0].selectbox('观察节点', list(range(len(q['price']))), index=model['gen_bus_map'][target], format_func=lambda i:f'节点 {i+1}')
observed = view[1].selectbox('观察机组', list(range(count)), index=target, format_func=lambda i:f'G{i+1}')
t = view[2].selectbox('观察小时', list(range(24)), format_func=lambda i:f'第 {i+1} 小时')
price_tab, uc_tab, money_tab, params_tab, time_tab = st.tabs(['价格响应', '物理 UC', '结算与市场力', '模型与下载', '累计计算时间'])
with price_tab:
    c = st.columns(2)
    c[0].metric('CHP 最优目标值 ($)', f'{q["value"]:,.2f}', f'{q["value"]-base["value"]:,.2f}')
    c[1].metric('当前观察节点/小时价格 ($/MWh)', f'{q["price"][node,t]:.6f}')
    st.info('价格是预先声明的一个合法最优对偶选择，不是唯一价格；价值折线不等于物理 UC 区域。')
    st.caption(f'全部节点/小时相对基准的最大价格变化：{np.max(abs(q["price"]-base["price"])):.9g} $/MWh。变化热图最小色域为 ±1e-6，避免放大浮点噪声。')
    left, right = st.columns(2)
    with left: heat(q['price'], '当前节点 × 24h CHP 价格', 'price_heat')
    with right: heat(q['price']-base['price'], '相对真实报价的价格变化', 'price_change', 'RdBu', 'Δ $/MWh')
    fig = go.Figure()
    for name, price in [('真实报价',base['price']), ('当前报价',q['price'])]:
        fig.add_scatter(x=list(range(1,25)), y=price[node], name=name)
    fig.update_layout(title=f'节点 {node+1} 的 24h 价格',xaxis_title='小时', yaxis_title='$/MWh')
    chart(fig,'day_price')
    fig = go.Figure(go.Scatter(x=np.asarray(s['price_boundaries'])/s['reference_slope']*100,
        y=np.asarray(s['prices'])[:,node,t], name='合法选价路径', line_color='#087E8B'))
    fig.add_vline(x=100*q['rho'],line_color='#BA7B25')
    fig.update_layout(title=f'节点 {node+1} · 小时 {t+1} 随报价的价格响应',xaxis_title='报价 (%)', yaxis_title='$/MWh')
    chart(fig,'bid_price')
with uc_tab:
    if p is None:
        st.info('not_available：当前方向没有全域物理 UC 地图。可在结算页显式启动当前报价的全局 UC，不能使用凸化 CHP 出力替代。')
    else:
        left,right = st.columns(2)
        with left: heat(u, '物理开停机状态', 'commitment', unit='u')
        with right: heat(p, '物理发电出力', 'dispatch', unit='MW')
        baseline_p = np.asarray(base['physical'][0]['output']) if base['physical'] else np.asarray(baseline_live['output']) if baseline_live else None
        if baseline_p is not None: heat(p-baseline_p, '物理出力相对真实报价的变化', 'dispatch_change','RdBu','Δ MW')
        fig = go.Figure(go.Scatter(x=list(range(1,25)),y=p[observed],name=f'G{observed+1}'))
        if baseline_p is not None: fig.add_scatter(x=list(range(1,25)),y=baseline_p[observed],name='真实报价',line_dash='dot')
        fig.update_layout(title=f'G{observed+1} 可执行出力',xaxis_title='小时',yaxis_title='MW')
        chart(fig,'unit_dispatch')
        fig = go.Figure()
        visible = sorted(set([observed,*np.argsort(p.sum(axis=1))[-5:].tolist()]))
        for i in visible:
            fig.add_scatter(x=list(range(1,25)),y=p[i],stackgroup='supply',name=f'G{i+1}')
        other = [i for i in range(count) if i not in visible]
        if other: fig.add_scatter(x=list(range(1,25)),y=p[other].sum(axis=0),stackgroup='supply',name='其余机组合计')
        fig.update_layout(title='物理供给构成（所选机组 + 主要供给 + 其余合计）',xaxis_title='小时',yaxis_title='MW')
        chart(fig,'supply_stack')
        if physical: st.caption(f'区域 [{physical["left"]:.9g}, {physical["right"]:.9g}]；共同方案全局间隙 {physical["common_plan_gap_usd"]:.3e} $。')
        if live: st.json(live.get('physical_audit', {}), expanded=False)
with money_tab:
    st.write('真实利润 = 能量收入 + 申报 LOC uplift − 真实运行成本。每次结算需要完整物理方案和每台机组的申报自调度最优盈余。')
    if st.button('按需计算当前报价与真实报价基准的 UC / 全部机组结算', type='primary'):
        try:
            with st.status('按需求解；不会改变价格地图或原始实验…', expanded=True) as status:
                if baseline_rows is None:
                    solve(s, 0., base_region, progress=st.write)
                solve(s, q['rho'], region, progress=st.write)
                status.update(label='直接结算完成并保存精确报价缓存', state='complete')
            st.rerun()
        except Exception as error:
            st.error(f'本次求解未完成，未生成成功缓存：{error}')
    if rows:
        table = pd.DataFrame(rows).sort_values('generator_index')
        if baseline_rows:
            bp = {r['generator_index']:r['true_profit'] for r in baseline_rows}
            table['true_profit_change'] = [r['true_profit']-bp[r['generator_index']] for r in rows]
        st.caption(f'{settlement_status}：只对应当前精确报价和选定物理方案，不对利润做插值。')
        columns = [k for k in ['unit','generation_mwh','energy_revenue','reported_uplift','reported_cost','true_cost','true_profit','true_profit_change','self_schedule_gap_usd'] if k in table]
        selection = st.dataframe(table[columns], use_container_width=True, hide_index=True,
            on_select='rerun', selection_mode='single-row')
        if selection.selection.rows:
            selected = table.iloc[selection.selection.rows[0]]
            st.write(f'所选 {selected["unit"]}：真实利润 {selected["true_profit"]:,.2f} USD；LOC {selected["reported_uplift"]:,.2f} USD。')
            if p is not None:
                fig = go.Figure(go.Scatter(x=list(range(1,25)),y=p[int(selected['generator_index'])],name=selected['unit']))
                fig.update_layout(title='所选结算行的物理出力',xaxis_title='小时',yaxis_title='MW')
                chart(fig,'selected_row_dispatch')
        st.metric(f'G{target+1} 当前真实利润 ($)',f'{table.loc[table.generator_index==target,"true_profit"].iloc[0]:,.2f}')
        st.caption(f'系统真实成本 {table.true_cost.sum():,.2f} USD；' + (f'申报成本 {table.reported_cost.sum():,.2f} USD。' if 'reported_cost' in table else '历史样本未单独保存申报成本。'))
        st.download_button('下载当前完整结算 CSV',table.to_csv(index=False).encode('utf-8-sig'),'settlement.csv','text/csv')
    else:
        st.info('not_available：此精确报价/物理方案没有全机组结算。上方按钮使用 COPT 直接求解并缓存；价格查表本身不需要求解器。')
    if s['profit_candidates']:
        candidates = pd.DataFrame(s['profit_candidates'])
        fig = go.Figure(go.Scatter(x=candidates.delta/s['reference_slope']*100,y=candidates.true_profit,
            mode='markers',marker=dict(color='#BA7B25',size=6),name='战略机组：已分析候选'))
        fig.update_layout(title='目标机组的有限报价/物理方案候选（不是插值利润曲线）',xaxis_title='报价 (%)',yaxis_title='真实利润 ($)')
        chart(fig,'profit_candidates')
with params_tab:
    st.write(data['notice'])
    st.caption(s['export_validation']+' | '+s['identity_scope'])
    st.write(f'价格验证容差 ${s["price_tolerance_usd"]:g}；价值验证容差 ${s["value_tolerance_usd"]:g}。初态：{model["initial_source"]}。')
    st.dataframe(pd.DataFrame(model['generators']).map(lambda x:json.dumps(x) if isinstance(x,(dict,list)) else x), hide_index=True)
    heat(model['demand'],'固定节点负荷','demand',unit='MW')
    st.caption('网络采用 PTDF 表示；下载包含完整 PTDF、PTDF_Gen 和线路限额，不虚构地理拓扑。')
    st.dataframe(pd.DataFrame({'线路':np.arange(len(model['F_max']))+1,'限额 MW':model['F_max']}),hide_index=True)
    st.download_button('下载完整模型参数 JSON',json.dumps(model,ensure_ascii=False),'model.json','application/json')
    st.download_button('下载价格矩阵 CSV',pd.DataFrame(q['price'],index=np.arange(len(q['price']))+1,columns=np.arange(1,25)).to_csv().encode(),'prices.csv','text/csv')
    answer = dict(scenario=s['id'],delta=q['delta'],requested_delta=q['requested_delta'],rho=q['rho'],
        model_sha256=s['model_sha256'],price_selector_sha256=s['price_selector_sha256'],
        value=q['value'],price=q['price'].tolist(),physical_region=region,
        uc_status=q['uc_status'] if not live else live['uc_status'],settlement_status=settlement_status if rows else 'not_available',settlement=rows)
    st.download_button('下载当前查询 JSON',json.dumps(answer,ensure_ascii=False),'query.json','application/json')
    st.json(manifest,expanded=False)
with time_tab:
    timing = st.selectbox('独立计时工作负载',[r['name'] for r in data['timing']])
    report = next(r for r in data['timing'] if r['name']==timing)
    direct = np.asarray(report['same_model_cumulative_seconds'])
    oracle = np.asarray(report['oracle_cumulative_online_seconds'])+report['oracle_offline_seconds_prior_run']+report.get('postprocessing_seconds',0.)+report['oracle_file_load_seconds']
    crossing = np.flatnonzero(direct >= oracle)
    fig = go.Figure()
    fig.add_scatter(x=np.arange(1,len(direct)+1),y=direct,name='持久模型重优化',line_color='#68818E')
    fig.add_scatter(x=np.arange(1,len(oracle)+1),y=oracle,name='Oracle：离线+后处理+加载+查询',line_color='#087E8B')
    if len(crossing): fig.add_vline(x=int(crossing[0]+1),line_color='#BA7B25',annotation_text=f'首次实测摊销 Q={crossing[0]+1}')
    fig.update_layout(xaxis_title='同一次固定查询流的前缀 Q',yaxis_title='累计时间 (s)',height=450)
    chart(fig,'timing')
    st.write(f'Q={len(direct)}：重优化 {direct[-1]:.3f}s；Oracle {oracle[-1]:.3f}s；累计比 {direct[-1]/oracle[-1]:.3f}×。')
    st.caption('不同 Q 的实验分别启动、不能拼接；离线时间来自先前建图。这里测的是价格查询，不包含 UC/LOC。')
    st.download_button('下载此完整计时记录',json.dumps(report),'timing.json','application/json')
