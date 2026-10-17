"""Dashboard contract checks: independent P/U/S layers and no phantom direction/profit."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from dashboard.data import (load_export, get_scenario, evaluate, sampled_settlement, cache_key,
                            profit_summary, bid_response, parameter_rows)
from dashboard.service import solve, cached
from price_vulnerability.oracle_compression import query_compact


@pytest.fixture(scope='module')
def exported():
    return load_export()[0]


def test_export_integrity_and_no_solver_import_needed(exported):
    assert len(exported['scenarios']) == 4
    assert {s['id'] for s in exported['scenarios']} == {'30-G1-all','30-G2-all','118-G11-all','30-G1-h1'}
    assert all(len(s['raw_witness_sha256']) == 64 for s in exported['scenarios'])
    assert max(s.get('maximum_settlement_reconciliation_usd',0.) for s in exported['scenarios']) < 1e-5


def test_export_checksum_rejects_changed_payload(tmp_path):
    (tmp_path/'data.json').write_text('{}')
    (tmp_path/'manifest.json').write_text(json.dumps({'data_sha256':'0'*64}))
    with pytest.raises(ValueError,match='checksum'): load_export(tmp_path)


@pytest.mark.parametrize('rho',[0., .123456789, .31451766098802286, .5])
def test_exported_price_query_matches_existing_compact(exported,rho):
    for s in exported['scenarios']:
        q = evaluate(s,rho)
        value,price = query_compact(q['delta'],*[np.asarray(s[k]) for k in ('value_boundaries','values','price_boundaries','prices')])
        assert q['value'] == pytest.approx(value, abs=1e-8)
        assert np.allclose(q['price'],price,atol=1e-12,rtol=0)


def test_no_extrapolation_or_wrong_direction(exported):
    s = get_scenario(exported,'30',0)
    for rho in (-1e-12,.500000001,np.nan,np.inf):
        with pytest.raises(ValueError): evaluate(s,rho)
    assert get_scenario(exported,'30',0,2) is None
    assert get_scenario(exported,'118',0) is None
    with pytest.raises(ValueError): evaluate(None,.1)


def test_root_keeps_two_physical_and_profit_choices(exported):
    s = get_scenario(exported,'30',0)
    q = evaluate(s,.31451766098802286)
    assert len(q['physical']) == 2
    profits = [sampled_settlement(s,q['delta'],r['region_index'])[0]['true_profit'] for r in q['physical']]
    assert sorted(profits) == pytest.approx([43713.520424,45100.867417],abs=1e-5)
    assert sampled_settlement(s,1.23456789,0) is None
    assert evaluate(get_scenario(exported,'118',10),.1)['uc_status'] == 'not_available'


def test_hourly_map_zero_price_response_but_two_uc_regions(exported):
    s = get_scenario(exported,'30',0,1)
    a,b = evaluate(s,0.),evaluate(s,.5)
    assert np.max(abs(a['price']-b['price'])) < 1e-6
    assert len(s['physical_regions']) == 2
    root = s['physical_regions'][0]['right']/s['reference_slope']
    assert len(evaluate(s,root)['physical']) == 2
    baseline = sampled_settlement(s,a['delta'],0)[0]
    endpoint = sampled_settlement(s,b['delta'],1)[0]
    assert endpoint['true_profit']-baseline['true_profit'] == pytest.approx(-106.41524348,abs=1e-5)


def test_cache_key_binds_exact_bid_direction_and_physical_plan(exported):
    s = get_scenario(exported,'30',0)
    keys = [cache_key(s,1.,0,'code'),cache_key(s,1.+1e-12,0,'code'),cache_key(s,1.,1,'code'),
            cache_key(s,1.,0,'new-code'),cache_key(get_scenario(exported,'30',0,1),1.,0,'code')]
    assert len(set(keys)) == len(keys)


def test_precompute_preview_skips_published_directions_and_checks_scope(exported):
    from dashboard.precompute import tasks, discovery_budget
    queue = tasks(exported,'30',[1,2,3],['all','1'])
    assert len(queue)==6 and sum(r['status']=='skip_exported_map' for r in queue)==3
    assert any(r['id']=='30-G3-all' and r['status']=='pending' for r in queue)
    for g,h in [([7],['all']),([1],['0']),([1],['25']),([1],['bad'])]:
        with pytest.raises(ValueError): tasks(exported,'30',g,h)
    for total in (3,4,399,400):
        n = discovery_budget(total)
        assert n+n-1 <= total
    with pytest.raises(ValueError): discovery_budget(2)


def test_live_all_unit_settlement_and_exact_cache(exported,tmp_path):
    s = get_scenario(exported,'30',0)
    rho = .123456789
    result = solve(s,rho,0,directory=tmp_path)
    assert result['status'] == 'solved_on_demand' and len(result['rows']) == 6
    assert max(result['physical_audit']['residuals'].values()) < 1e-6
    for r in result['rows']:
        assert r['energy_revenue']+r['reported_uplift']-r['true_cost'] == pytest.approx(r['true_profit'],abs=1e-6)
        assert r['self_schedule_gap_usd'] < 1e-5
    assert solve(s,rho,0,directory=tmp_path) == result
    assert cached(s,1.23456789,0,tmp_path) is None


def test_stale_live_cache_cannot_bypass_current_model_identity(exported,tmp_path,monkeypatch):
    from dashboard.service import engine_sha
    import price_vulnerability.model_identity as identity
    s = get_scenario(exported,'30',0)
    key = cache_key(s,1.,0,engine_sha())
    (tmp_path/f'{key}.json').write_text(json.dumps(dict(cache_key=key,status='solved_on_demand')))
    monkeypatch.setattr(identity,'model_identity',lambda gens,net:{'model_sha256':'changed'})
    with pytest.raises(ValueError,match='Current model changed'):
        cached(s,1.,0,tmp_path)


def test_on_demand_uc_when_no_physical_map_exists(exported,tmp_path):
    s = get_scenario(exported,'30',1)
    result = solve(s,.123456789,directory=tmp_path)
    assert result['uc_status']=='solved_on_demand' and len(result['rows'])==6
    info = result['physical_audit']['uc_solve_info']
    assert info['requested_mip_gap']==0. and abs(info['objective']-info['lower_bound'])<1e-5
    assert max(result['physical_audit']['residuals'].values())<1e-6


def test_monetary_row_must_match_exported_physical_plan_and_price(exported):
    from dashboard.export import reconcile_settlements
    from engine import load_case
    original = get_scenario(exported,'30',0,1)
    changed = dict(original,settlements=[dict(original['settlements'][0],energy_revenue=1.)])
    gens,net = load_case('30','ptdf',24,3,'tight')
    with pytest.raises(ValueError,match='does not reconcile'):
        reconcile_settlements(changed,gens,net)


def test_q500_is_one_independent_measured_stream(exported):
    r = next(r for r in exported['timing'] if r['name']=='118-G11 Q500')
    old = next(r for r in exported['timing'] if r['name']=='118-G11 Q200')
    a,b = r['same_model_cumulative_seconds'],r['oracle_cumulative_online_seconds']
    assert len(a)==len(b)==len(r['query_deltas'])==r['n_queries']==500
    assert np.all(np.diff(a)>0) and np.all(np.diff(b)>=0)
    assert r['query_deltas'][:200] != old['query_deltas']
    assert a[-1] == r['same_model_reoptimization_batch_seconds']
    assert b[-1] == r['oracle_online_batch_seconds']
    assert r['max_value_discrepancy_usd'] < 1e-6


def test_streamlit_boundary_and_unavailable_direction():
    from streamlit.testing.v1 import AppTest
    path = Path(__file__).resolve().parents[1]/'dashboard/app.py'
    app = AppTest.from_file(str(path),default_timeout=30).run()
    assert not app.exception
    app.number_input(key='bid_pct').set_value(31.451766098802286).run()
    assert not app.exception
    assert app.slider(key='bid_slider').value == pytest.approx(31.451766098802286)
    assert any('物理方案' in r.label and len(r.options)==2 for r in app.radio)
    app.sidebar.selectbox(key='target_30').set_value(5).run()
    assert not app.exception
    assert any('CHP电价' in m.label for m in app.metric)
    app.sidebar.selectbox(key='target_30').set_value(1).run()
    assert not app.exception
    app.sidebar.selectbox[0].set_value('118').run()
    assert not app.exception
    assert app.sidebar.selectbox(key='target_118').value == 10
    app.sidebar.selectbox(key='target_118').set_value(0).run()
    assert any('not_available' in w.value for w in app.warning)


def test_standalone_has_no_external_script_or_data_fetch():
    from html.parser import HTMLParser
    class Assets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts,self.ids,self.views = [],[],[]
        def handle_starttag(self,tag,attrs):
            a = dict(attrs)
            if tag=='script': self.scripts.append(a)
            if 'id' in a: self.ids.append(a['id'])
            if tag=='section' and a.get('class')=='view': self.views.append(a)
    html = (Path(__file__).resolve().parents[1]/'dashboard/exports/explorer.html').read_text(encoding='utf-8')
    parser = Assets(); parser.feed(html)
    assert len(parser.scripts)==2 and all('src' not in a for a in parser.scripts)
    assert len(parser.ids)==len(set(parser.ids))
    assert len(parser.views)==6 and sum('hidden' not in a for a in parser.views)==1
    assert '/*EXPORTED_DATA*/' not in html and '/*PLOTLY_BUNDLE*/' not in html


def test_profit_summary_distinguishes_missing_zero_and_boundary_plans(exported):
    s = get_scenario(exported,'30',0)
    base = sampled_settlement(s,0.,0)
    q = evaluate(s,.31451766098802286)
    a,b = [profit_summary(sampled_settlement(s,q['delta'],r['region_index']),base,0) for r in q['physical']]
    assert a['baseline']==pytest.approx(37289.312315)
    assert a['additional']==pytest.approx(7811.555102)
    assert a['percent']==pytest.approx(20.948511922,abs=1e-5)
    assert a['current']-b['current']==pytest.approx(1387.346993,abs=1e-5)
    assert profit_summary(None,None,0)==dict(baseline=None,current=None,additional=None,percent=None)
    assert profit_summary([dict(generator_index=0,true_profit=1.)],[dict(generator_index=0,true_profit=0.)],0)['percent'] is None


def test_bid_response_contains_knots_and_matches_analytic_selector(exported):
    for s in exported['scenarios']:
        x,time,space = bid_response(s,0,18)
        assert time.shape==(24,len(x)) and space.shape==(int(s['case']),len(x))
        assert np.allclose(time[:,0],0.) and np.allclose(space[:,0],0.)
        knots = np.asarray(s['price_boundaries'])/s['reference_slope']*100
        assert all(np.min(abs(x-k))<1e-12 for k in knots)
        for k in [0,len(x)//2,len(x)-1]:
            _,price = query_compact(x[k]*s['reference_slope']/100,*[np.asarray(s[name]) for name in ('value_boundaries','values','price_boundaries','prices')])
            assert np.allclose(time[:,k],price[0]-np.asarray(s['prices'][0])[0],atol=1e-8)
            assert np.allclose(space[:,k],price[:,18]-np.asarray(s['prices'][0])[:,18],atol=1e-8)


def test_parameter_tables_keep_all_units_and_cost_segments(exported):
    for case in ['30','118']:
        model = exported['models'][case]
        physical,costs = parameter_rows(model)
        assert len(physical)==len(model['generators'])
        assert len(costs)==3*len(physical)
        assert physical[0]['initial_status']==0 and costs[0]['slope_usd_mwh']>0


def test_lazy_pages_share_unit_bus_and_profit_selection():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'dashboard/app.py'),default_timeout=30).run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==3
    app.selectbox(key='observe_unit').set_value(2).run()
    assert app.selectbox(key='observe_node').value==21
    app.radio(key='page').set_value('结算与市场力').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    assert app.radio(key='profit_mode').value=='利润增量'
    app.number_input(key='bid_pct').set_value(31.451766098802286).run()
    assert any(m.value=='45,100.87' for m in app.metric)
    plan = next(r for r in app.radio if r.label=='选择物理方案')
    plan.set_value(3).run()
    assert any(m.value=='43,713.52' for m in app.metric)
    app.radio(key='page').set_value('价格响应').run()
    assert not app.exception and len(app.get('plotly_chart'))==5
    app.selectbox(key='case').set_value('118').run()
    assert not app.exception and app.selectbox(key='observe_unit').value==10
    assert any(m.value=='待计算' for m in app.metric)
