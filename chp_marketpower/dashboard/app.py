"""Local CHP workbench: immutable price maps and explicit, bounded UC/LOC jobs."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.data import (EXPORTS, evaluate, get_scenario, load_export, sampled_settlement,
                            profit_summary, bid_response, parameter_rows)
from dashboard.service import cached
from dashboard.jobs import SolveJob

st.set_page_config(page_title='CHP Oracle Explorer',page_icon='⚡',layout='wide')
st.markdown('''<style>
.stApp{background:#F5F7F8;color:#203442}h1,h2,h3{color:#203442}
[data-testid="stSidebar"]{background:#E9EFF1}.block-container{padding:1.4rem 2rem 3rem;max-width:1600px}
@media(min-width:900px){[data-testid="stSidebar"]{min-width:270px;max-width:270px}}
[data-testid="stMetricValue"]{font-family:Consolas,monospace;font-size:1.65rem;color:#087E8B}
.capability{padding:12px 14px;background:#E4F0F1;border-left:4px solid #087E8B;min-height:124px;border-radius:0 6px 6px 0;font-size:14px}
.capability.wait{background:#F8F0E2;border-color:#BA7B25}.capability small{color:#526A77}
[data-testid="stHorizontalBlock"]{gap:1.2rem}button:focus-visible{outline:3px solid #BA7B25!important}
</style>''',unsafe_allow_html=True)


@st.cache_data
def archive(version):
    return load_export()


def chart(fig,key):
    fig.update_layout(template='plotly_white',font=dict(family='Segoe UI, Microsoft YaHei, sans-serif',color='#203442'),
        margin=dict(l=55,r=25,t=55,b=45),paper_bgcolor='#F5F7F8',legend=dict(orientation='h',y=-.23))
    st.plotly_chart(fig,use_container_width=True,key=key,config={'displaylogo':False})


def heat(z,title,key,*,yaxis='节点编号',unit='$/MWh',difference=False,x=None,xaxis='小时'):
    z = np.asarray(z)
    bound = max(1e-6,float(np.max(abs(z)))) if difference else None
    fig = go.Figure(go.Heatmap(z=z,x=list(range(1,25)) if x is None else x,
        y=list(range(1,len(z)+1)),colorscale='RdBu_r' if difference else 'Viridis',
        zmin=-bound if bound else None,zmax=bound,colorbar=dict(title=unit),
        hovertemplate='%{x}<br>%{y}<br>%{z:.6f}<extra></extra>'))
    fig.update_layout(title=title,xaxis_title=xaxis,yaxis_title=yaxis,height=350)
    if x is not None: fig.add_vline(x=100*q['rho'],line_color='#BA7B25',line_dash='dot')
    chart(fig,key)


def exact_rows(s,q,region):
    try:
        result = cached(s,q['delta'],region)
    except (ValueError,OSError,json.JSONDecodeError) as error:
        st.warning(f'实时缓存未采用：{error}')
        result = None
    return (result['rows'],'solved_on_demand',result) if result else (
        sampled_settlement(s,q['delta'],region),'sampled_only',None)


def set_bid(value):
    st.session_state.bid_pct = float(value)
    st.session_state.bid_slider = float(value)


def unit_changed(gen_bus_map):
    st.session_state.observe_node = gen_bus_map[st.session_state.observe_unit]


def table_selected(key,table,gen_bus_map):
    selected = st.session_state[key]['selection']['rows']
    if selected:
        st.session_state.observe_unit = int(table.iloc[selected[0]]['generator_index'])
        unit_changed(gen_bus_map)


active_job = st.session_state.get('solve_job')
poll_job = active_job is not None and active_job.state()['status']=='running'


@st.fragment(run_every=1 if poll_job else None)
def job_panel():
    job = st.session_state.get('solve_job')
    if job is None: return
    state = job.state()
    plan_name = f'区域 {state["region"]+1}' if state['region'] is not None else '直接 UC 选取方案'
    st.caption(f'计算任务：{state["scenario"]} · {100*state["rho"]:.9f}% · {plan_name} · 已用 {state["elapsed_seconds"]:.1f}s / {job.seconds:g}s')
    if state['status']=='running':
        st.info(state['message']+'；可以继续浏览，结果只写回该任务的原报价缓存。')
        if st.button('取消当前计算',key='cancel_job'):
            job.stop()
            st.rerun()
    else:
        (st.success if state['status']=='complete' else st.warning)(state['message'])
        if st.session_state.get('job_notified') is not job:
            st.session_state.job_notified = job
            st.rerun()


st.title('CHP Oracle Explorer')
st.caption('改变报价后，价格、物理执行和真实利润分别发生什么？')
if not (EXPORTS/'manifest.json').exists():
    st.error('缺少导出数据，请执行 python -m dashboard.export。'); st.stop()
data,manifest = archive((EXPORTS/'manifest.json').stat().st_mtime_ns)
if 'bid_pct' not in st.session_state: set_bid(0.)
with st.sidebar:
    st.subheader('选择报价方向')
    case = st.selectbox('节点系统',['30','118'],key='case')
    model = data['models'][case]
    count = len(model['generators'])
    target = st.selectbox('战略机组',list(range(count)),index=0 if case=='30' else 10,key=f'target_{case}',
        format_func=lambda i:f'G{i+1} · 节点 {model["gen_bus_map"][i]+1}')
    direction = st.radio('报价调整时段',['全部 24 小时','单小时'],key='direction')
    hour = st.selectbox('调整第几小时',list(range(1,25)),key='bid_hour') if direction=='单小时' else None
    s = get_scenario(data,case,target,hour)
    st.number_input('报价加数 / 参考斜率 (%)',min_value=0.,max_value=50.,step=.1,format='%.9f',key='bid_pct',
        on_change=lambda:set_bid(st.session_state.bid_pct))
    st.slider('拖动报价 (%)',0.,50.,step=.1,key='bid_slider',on_change=lambda:set_bid(st.session_state.bid_slider))
    st.caption('δ = ρ × 参考斜率。全部增量成本段统一加 δ；空载及启停费用不变。')
    buttons = st.columns(2)
    buttons[0].button('真实报价 0%',on_click=set_bid,args=(0.,))
    buttons[1].button('范围上界 50%',on_click=set_bid,args=(50.,))
    if s and len(s['physical_regions'])>1:
        roots = [r['right'] for r in s['physical_regions'][:-1]]
        root = st.selectbox('物理 UC 切换阈值',roots,format_func=lambda d:f'{100*d/s["reference_slope"]:.9f}%')
        st.button('跳至所选 UC 边界',on_click=set_bid,args=(100*root/s['reference_slope'],))
    st.caption('固定：tight PTDF · 24h · 3段成本 · 冷启动。未建图方向不返回其他地图。')
job_panel()
context = (case,target,hour)
if st.session_state.get('observation_context')!=context:
    st.session_state.update(observation_context=context,observe_unit=target,observe_node=model['gen_bus_map'][target],
        observe_hour=hour-1 if hour else 0)
if s is None:
    st.warning('not_available：该机组/时段没有完整价格地图。可用：30-G1/G2全天、30-G1第1小时、118-G11全天。')
    st.info('旧场景结果已隐藏。新增方向必须单独建图，本页不会外推或自动启动批量实验。'); st.stop()
q,base = evaluate(s,st.session_state.bid_pct/100),evaluate(s,0.)
regions = q['physical']
if len(regions)>1:
    st.warning('同一报价存在两套并列最优物理执行；切换方案会同步更新出力、成本和利润，不做平均。')
region = st.radio('选择物理方案',[r['region_index'] for r in regions],horizontal=True,
    key=f'plan_{s["id"]}_{q["delta"].hex()}',format_func=lambda k:f'区域 {k+1} · '+('左侧方案' if k==regions[0]['region_index'] else '右侧方案')) if len(regions)>1 else (regions[0]['region_index'] if regions else None)
rows,settlement_status,live = exact_rows(s,q,region)
base_region = base['physical'][0]['region_index'] if base['physical'] else None
baseline_rows,_,baseline_live = exact_rows(s,base,base_region)
physical = next((r for r in regions if r['region_index']==region),None)
p = np.asarray(physical['output']) if physical else np.asarray(live['output']) if live else None
u = np.asarray(physical['commitment']) if physical else np.asarray(live['commitment']) if live else None
baseline_p = np.asarray(base['physical'][0]['output']) if base['physical'] else np.asarray(baseline_live['output']) if baseline_live else None
st.caption(f'{s["id"]} · Model {s["model_sha256"][:12]} · Selector {s["price_selector_sha256"][:12]} · {s["value_regions"]}价值 / {s["price_segments"]}选价分段')
offer = st.columns(2)
offer[0].metric('请求报价 ρ',f'{st.session_state.bid_pct:.9f}%')
offer[0].caption(f'δ = {q["requested_delta"]:.12f} $/MWh')
offer[1].metric('实际评估 ρ',f'{100*q["rho"]:.9f}%')
offer[1].caption(f'δ = {q["delta"]:.12f} $/MWh')
if q['snapped_to_boundary']:
    st.caption('已对齐最近存档 UC 边界（|Δδ| ≤ 1e-7 $/MWh）；上方同时保留请求值与评估值。')
capabilities = [('P · CHP 价格','完整地图，即时查表','precomputed_verified'),
    ('U · 物理执行','已存区域共同方案' if physical else '已直接求解本报价' if live else '待计算全局 UC',q['uc_status'] if not live else live['uc_status']),
    ('S · 逐机组结算','本报价直接结算缓存' if live else '本报价存档直接样本' if rows else '待计算全部机组申报 LOC',settlement_status if rows else 'not_available')]
for column,(title,description,status) in zip(st.columns(3),capabilities):
    column.markdown(f'<div class="capability {"wait" if status=="not_available" else ""}"><b>{title}</b><br>{description}<br><small>{status}</small></div>',unsafe_allow_html=True)
summary = profit_summary(rows,baseline_rows,target)
for column,title,key in zip(st.columns(3),['真实报价基准利润 (USD)','当前真实总利润 (USD)','相对基准额外利润 (USD)'],['baseline','current','additional']):
    value = summary[key]
    column.metric(f'G{target+1} · {title}','待计算' if value is None else f'{value:+,.2f}' if key=='additional' else f'{value:,.2f}',
        f'{summary["percent"]:+.2f}% 相对基准' if key=='additional' and summary['percent'] is not None else None,delta_color='off')
if summary['additional'] is not None and summary['percent'] is None: st.caption('基准利润接近零，额外利润百分比不定义；不显示虚假的0%。')
with st.expander(f'计算当前报价的全部经济结果 · {count}台机组',expanded=not rows):
    st.caption(f'价格不用重解。物理方案缺失时解全局 UC，再解 {count} 个单机申报自调度；必要时另算真实报价基准。结果仅属于所选物理方案。')
    seconds = st.number_input('计算时限（秒）',min_value=1.,max_value=3600.,value=600.,step=30.,key='job_seconds')
    job = st.session_state.get('solve_job')
    running = job is not None and job.state()['status']=='running'
    if st.button('计算当前报价的全部经济结果',type='primary',disabled=running):
        try:
            st.session_state.solve_job = SolveJob(s,q['rho'],region,seconds)
            st.rerun()
        except (ValueError,OSError) as error: st.error(f'任务未启动：{error}')

view = st.columns(3)
observed = view[0].selectbox('观察机组',list(range(count)),key='observe_unit',format_func=lambda i:f'G{i+1}',on_change=unit_changed,args=(model['gen_bus_map'],))
node = view[1].selectbox('观察节点',list(range(len(q['price']))),key='observe_node',format_func=lambda i:f'节点 {i+1}')
t = view[2].selectbox('观察小时',list(range(24)),key='observe_hour',format_func=lambda i:f'第 {i+1} 小时')
page = st.radio('研究视图',['总览','价格响应','物理 UC','结算与市场力','模型与下载','累计计算时间'],horizontal=True,key='page')

if page=='总览':
    ruler = go.Figure()
    ruler.add_scatter(x=np.asarray(s['price_boundaries'])/s['reference_slope']*100,y=[1]*len(s['price_boundaries']),mode='markers',marker=dict(symbol='line-ns',size=14,color='#68818E'),name='选价分段')
    ruler.add_scatter(x=[r['right']/s['reference_slope']*100 for r in s['physical_regions'][:-1]],y=[0]*max(0,len(s['physical_regions'])-1),mode='markers',marker=dict(symbol='diamond',color='#BA7B25',size=9),name='物理 UC 切换')
    ruler.add_vline(x=100*q['rho'],line_color='#087E8B',line_width=3)
    ruler.update_layout(height=210,xaxis=dict(title='报价加数 / 参考斜率 (%)',range=[0,50]),yaxis=dict(tickvals=[0,1],ticktext=['物理执行','选定价格'],range=[-.5,1.5]))
    chart(ruler,'ruler')
    st.caption('价格影响、物理执行变化与可获利性是三个不同对象；CHP价格为一个合法最优对偶选择，不声称唯一。')
    heat(q['price']-base['price'],'相对真实报价的节点价格变化','overview_change',difference=True,unit='Δ $/MWh')
    st.write(f'CHP最优目标值：{q["value"]:,.2f} USD；最大节点/小时价格变化：{np.max(abs(q["price"]-base["price"])):.6g} $/MWh。')

elif page=='价格响应':
    st.caption('Δλ = 当前选定价格 − 真实报价选定价格。红色上涨，蓝色下降；最小色域±1e-6 $/MWh，避免放大浮点噪声。')
    left,right = st.columns(2)
    with left: heat(q['price'],'当前节点 × 小时价格','price_heat')
    with right: heat(q['price']-base['price'],'相对真实报价的价格变化','price_change',difference=True,unit='Δ $/MWh')
    fig = go.Figure()
    for name,price in [('真实报价',base['price']),('当前报价',q['price'])]: fig.add_scatter(x=list(range(1,25)),y=price[node],name=name)
    fig.update_layout(title=f'节点{node+1}的24小时价格',xaxis_title='小时',yaxis_title='$/MWh'); chart(fig,'daily_price')
    fig = go.Figure(go.Scatter(x=np.asarray(s['price_boundaries'])/s['reference_slope']*100,y=np.asarray(s['prices'])[:,node,t],name='合法选价路径',line_color='#087E8B'))
    fig.add_vline(x=100*q['rho'],line_color='#BA7B25')
    fig.update_layout(title=f'节点{node+1} · 小时{t+1}的报价响应',xaxis_title='报价 (%)',yaxis_title='$/MWh'); chart(fig,'bid_price')
    st.subheader('报价—时空价格响应')
    mode = st.radio('响应维度',['固定节点：报价 × 小时','固定小时：报价 × 节点'],horizontal=True,key='response_mode')
    x,time,space = bid_response(s,node,t)
    heat(time if mode.startswith('固定节点') else space,f'节点{node+1}的跨小时价格变化' if mode.startswith('固定节点') else f'小时{t+1}的跨节点价格变化',
        'bid_response',yaxis='小时' if mode.startswith('固定节点') else '节点编号',unit='Δ $/MWh',difference=True,x=x,xaxis='报价加数 / 参考斜率 (%)')
    st.caption(f'绘图网格含全部选价折点及均匀采样，共{len(x)}个报价。只用于显示已有仿射路径，不是新建图或机制区域的额外证明。')

elif page=='物理 UC':
    if p is None: st.info('待计算全局物理 UC；价格地图不提供可执行调度。请使用上方显式计算按钮。')
    else:
        left,right = st.columns(2)
        with left: heat(u,'物理开停机状态','commitment',yaxis='机组编号',unit='u')
        with right: heat(p,'可执行物理出力','dispatch',yaxis='机组编号',unit='MW')
        if baseline_p is not None: heat(p-baseline_p,'相对基准的物理再调度','dispatch_change',yaxis='机组编号',unit='Δ MW',difference=True)
        fig = go.Figure(go.Scatter(x=list(range(1,25)),y=p[observed],name=f'G{observed+1}'))
        if baseline_p is not None: fig.add_scatter(x=list(range(1,25)),y=baseline_p[observed],name='真实报价',line_dash='dot')
        fig.update_layout(title=f'G{observed+1}的可执行出力',xaxis_title='小时',yaxis_title='MW'); chart(fig,'unit_dispatch')
        fig = go.Figure()
        visible = sorted(set([observed,*np.argsort(p.sum(axis=1))[-5:].tolist()]))
        for i in visible: fig.add_scatter(x=list(range(1,25)),y=p[i],stackgroup='supply',name=f'G{i+1}')
        other = [i for i in range(count) if i not in visible]
        if other: fig.add_scatter(x=list(range(1,25)),y=p[other].sum(axis=0),stackgroup='supply',name='其余机组合计')
        fig.update_layout(title='所选机组、主要供给及其余合计',xaxis_title='小时',yaxis_title='MW'); chart(fig,'supply_stack')
        if physical: st.caption(f'区域[{physical["left"]:.9g}, {physical["right"]:.9g}]；共同方案间隙{physical["common_plan_gap_usd"]:.3e} USD。')
        if live: st.json(live.get('physical_audit',{}),expanded=False)

elif page=='结算与市场力':
    st.write('真实利润 = 能量收入 + 申报 LOC uplift − 真实运行成本。利润样本不插值；切换并列方案时单独结算。')
    if rows:
        table = pd.DataFrame(rows).sort_values('generator_index').reset_index(drop=True)
        if baseline_rows:
            bp = {r['generator_index']:r['true_profit'] for r in baseline_rows}
            table['true_profit_change'] = table.apply(lambda r:r.true_profit-bp[r.generator_index],axis=1)
        columns = [k for k in ['unit','generation_mwh','energy_revenue','reported_uplift','reported_cost','true_cost','true_profit','true_profit_change','self_schedule_gap_usd'] if k in table]
        key = f'settlement_{s["id"]}_{q["delta"].hex()}_{region}'
        st.caption(f'{settlement_status}：当前精确报价/物理方案。点击结算行会更新全局观察机组及其所在节点。')
        st.dataframe(table[columns],use_container_width=True,hide_index=True,key=key,
            on_select=lambda:table_selected(key,table,model['gen_bus_map']),selection_mode='single-row',
            column_config={'energy_revenue':'能量收入 USD','reported_uplift':'申报 LOC USD','reported_cost':'申报成本 USD',
                'true_cost':'真实成本 USD','true_profit':'真实利润 USD','true_profit_change':'额外利润 USD','generation_mwh':'发电 MWh'})
        st.caption(f'系统真实成本{table.true_cost.sum():,.2f} USD；申报成本{table.reported_cost.sum():,.2f} USD。')
        st.download_button('下载当前完整结算 CSV',table.to_csv(index=False).encode('utf-8-sig'),'settlement.csv','text/csv')
    else: st.info('待计算：当前报价/物理方案没有全机组结算；不会显示上次报价的利润。')
    if s['profit_candidates']:
        mode = st.radio('候选利润口径',['额外利润','真实总利润'],horizontal=True,key='profit_mode')
        candidates = pd.DataFrame(s['profit_candidates'])
        baseline_profit = summary['baseline']
        if mode=='额外利润' and baseline_profit is None: st.info('基准待计算，不绘制额外利润。')
        else:
            fig = go.Figure(go.Scatter(x=candidates.delta/s['reference_slope']*100,y=candidates.true_profit-(baseline_profit if mode=='额外利润' else 0.),mode='markers',marker=dict(color='#BA7B25',size=7),name='战略机组候选'))
            if mode=='额外利润': fig.add_hline(y=0,line_color='#68818E',line_dash='dot')
            fig.update_layout(title='已分析的有限报价 / 物理方案候选（非插值利润曲线）',xaxis_title='报价 (%)',yaxis_title=f'{mode} (USD)'); chart(fig,'profit_candidates')

elif page=='模型与下载':
    physical_rows,cost_rows = parameter_rows(model)
    st.subheader('物理参数与初态')
    st.dataframe(pd.DataFrame(physical_rows),hide_index=True,use_container_width=True,column_config={
        'unit':'机组','bus':'节点','P_min':'Pmin MW','P_max':'Pmax MW','R_up':'升坡 MW/h','R_down':'降坡 MW/h',
        'T_on_min':'最小开机 h','T_off_min':'最小停机 h','cost_su':'启动 USD','cost_sd':'停机 USD','cost_nl':'空载 USD/h',
        'initial_status':'初始开机','initial_power':'初始出力 MW','initial_up_time':'初始连续开机 h','initial_down_time':'初始连续停机 h'})
    st.subheader('增量 PWL 成本分段')
    st.dataframe(pd.DataFrame(cost_rows),hide_index=True,use_container_width=True,column_config={
        'unit':'机组','segment':'增量段','incremental_width_mw':'增量段宽 MW',
        'slope_usd_mwh':'成本斜率 $/MWh','reference_slope_usd_mwh':'参考斜率 $/MWh'})
    st.caption(f'价格容差{s["price_tolerance_usd"]:g} $/MWh；价值容差{s["value_tolerance_usd"]:g} USD。初态：{model["initial_source"]}。')
    st.caption(s['export_validation']+' | '+s['identity_scope'])
    heat(model['demand'],'固定节点负荷','demand',unit='MW')
    st.dataframe(pd.DataFrame({'线路':np.arange(len(model['F_max']))+1,'限额 MW':model['F_max']}),hide_index=True)
    st.download_button('下载完整模型参数 JSON',json.dumps(model,ensure_ascii=False),'model.json','application/json')
    st.download_button('下载价格矩阵 CSV',pd.DataFrame(q['price'],index=np.arange(len(q['price']))+1,columns=np.arange(1,25)).to_csv().encode(),'prices.csv','text/csv')
    answer = dict(scenario=s['id'],delta=q['delta'],requested_delta=q['requested_delta'],rho=q['rho'],model_sha256=s['model_sha256'],price_selector_sha256=s['price_selector_sha256'],value=q['value'],price=q['price'].tolist(),physical_region=region,uc_status=q['uc_status'] if not live else live['uc_status'],settlement_status=settlement_status if rows else 'not_available',settlement=rows)
    st.download_button('下载当前查询 JSON',json.dumps(answer,ensure_ascii=False),'query.json','application/json')
    st.json(manifest,expanded=False)

elif page=='累计计算时间':
    timing = st.selectbox('独立计时工作负载',[r['name'] for r in data['timing']])
    report = next(r for r in data['timing'] if r['name']==timing)
    direct = np.asarray(report['same_model_cumulative_seconds'])
    oracle = np.asarray(report['oracle_cumulative_online_seconds'])+report['oracle_offline_seconds_prior_run']+report.get('postprocessing_seconds',0.)+report['oracle_file_load_seconds']
    crossing = np.flatnonzero(direct>=oracle)
    fig = go.Figure()
    for values,name,color in [(direct,'持久模型重优化','#68818E'),(oracle,'Oracle：含全部离线成本','#087E8B')]: fig.add_scatter(x=np.arange(1,len(values)+1),y=values,name=name,line_color=color)
    if len(crossing): fig.add_vline(x=int(crossing[0]+1),line_color='#BA7B25',annotation_text=f'首次实测摊销 Q={crossing[0]+1}')
    fig.update_layout(xaxis_title='固定查询流前缀 Q',yaxis_title='累计时间 (s)',height=450); chart(fig,'timing')
    st.write(f'Q={len(direct)}：重优化{direct[-1]:.3f}s；Oracle{oracle[-1]:.3f}s；累计比{direct[-1]/oracle[-1]:.3f}×。')
    st.caption('独立Q200/Q500不拼接；计时只衡量固定场景的价格查询，不包含UC/LOC。合法选价可以不同，价值一致不等于价格唯一。')
    st.download_button('下载完整计时记录',json.dumps(report),'timing.json','application/json')
