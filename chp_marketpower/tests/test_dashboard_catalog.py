"""Verified, scope-exact lazy publication and readable mathematical explanations."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from dashboard.catalog import seed, publish, register, ROOT
from dashboard.data import load_export, load_catalog, get_scenario, evaluate


def test_catalog_startup_is_lazy_and_payload_is_hash_checked(tmp_path,monkeypatch):
    data = load_export()[0]
    seed(data,tmp_path)
    original = Path.read_bytes
    accessed = []
    def observe(path):
        accessed.append(path)
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',observe)
    lazy,catalog = load_catalog(tmp_path)
    assert not any('scenarios' in p.parts for p in accessed)
    s = get_scenario(lazy,'30',0)
    assert s['id']=='30-G1-all'
    assert sum('scenarios' in p.parts for p in accessed)==1
    entry = next(r for r in catalog['scenarios'] if r['id']==s['id'])
    (tmp_path/entry['payload']).write_text('{}')
    with pytest.raises(ValueError,match='checksum'): get_scenario(lazy,'30',0)


def test_payload_escape_and_model_mismatch_are_rejected(tmp_path):
    data = load_export()[0]
    seed(data,tmp_path)
    lazy,_ = load_catalog(tmp_path)
    lazy['scenarios'][0]['payload']='../outside.json'
    with pytest.raises(ValueError,match='escapes'): get_scenario(lazy,'30',0)
    s = copy.deepcopy(data['scenarios'][0])
    s['model_sha256']='wrong'
    with pytest.raises(ValueError,match='model'): publish(s,tmp_path)


def test_baseline_audit_discloses_nonunique_selection_without_rewriting_prices(tmp_path):
    data = load_export()[0]
    seed(data,tmp_path)
    s = copy.deepcopy(data['scenarios'][1])
    s['prices'][0][0][0]+=1.
    original = copy.deepcopy(s['prices'])
    entry = publish(s,tmp_path)
    assert not entry['baseline_audit']['shared_price_baseline']
    assert s['prices']==original


def test_registration_checks_all_residuals_not_just_status(tmp_path):
    import shutil
    source = ROOT/'results/dashboard_precompute/30-G4-all'
    if not source.exists(): pytest.skip('Native extension witnesses not present')
    directory = tmp_path/'source'
    shutil.copytree(source,directory)
    validation = json.loads((directory/'validation.json').read_text())
    validation['direct_checks'][0]['selector_stationarity']=1.
    (directory/'validation.json').write_text(json.dumps(validation))
    with pytest.raises(ValueError,match='residuals'): register(directory,tmp_path)
    validation['direct_checks'][0]['selector_stationarity']=0.
    validation['source_sha256']='wrong'
    (directory/'validation.json').write_text(json.dumps(validation))
    with pytest.raises(ValueError,match='source-bound'): register(directory,tmp_path)


def test_all_day_price_and_uc_maps_are_queryable_without_settlement_interpolation():
    data,_ = load_catalog()
    for g in range(6):
        s = get_scenario(data,'30',g)
        assert s is not None
        assert s['baseline_audit']['maximum_price_difference_usd_per_mwh']<1e-6
        assert s['physical_regions']
        q = evaluate(s,.123456789)
        assert q['physical'] and np.asarray(q['price']).shape==(30,24)


def test_theory_validation_and_uc_pages_render_real_archived_evidence():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT/'dashboard/app.py'),default_timeout=30).run()
    app.radio(key='page').set_value('方法与理论依据').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    theta = next(s for s in app.slider if 'θ' in s.label)
    theta.set_value(.35).run()
    assert not app.exception and any('0.35' in c.value for c in app.code)
    app.radio(key='page').set_value('数值验证').run()
    assert not app.exception and any('独立验证当前报价' in b.label for b in app.button)
    app.radio(key='page').set_value('机组组合与出力').run()
    assert not app.exception and len(app.get('plotly_chart'))>=4


def test_complete_checkpoint_cannot_be_reused_as_another_bid_direction():
    from dashboard.precompute import check_task_scope
    audit = dict(scope=dict(case='30',generator_index=3,network='ptdf',T=24,segments=3,congestion='tight'),
        intervals=[dict(left=0.,right=20.)])
    task = dict(case='30',generator=4,hour=None)
    check_task_scope(audit,task,40.)
    for changed,reference in [(dict(task,generator=5),40.),(dict(task,hour=1),40.),(task,50.)]:
        with pytest.raises(ValueError,match='Checkpoint'): check_task_scope(audit,changed,reference)


def test_stale_uc_publication_cannot_rollback_a_new_selector(tmp_path):
    data = load_export()[0]
    seed(data,tmp_path)
    s = get_scenario(load_catalog(tmp_path)[0],'30',1)
    expected = dict(price_selector_sha256=s['price_selector_sha256'])
    newer = dict(s,price_selector_sha256='new-selector')
    publish(newer,tmp_path)
    with pytest.raises(ValueError,match='stale'): publish(s,tmp_path,expected=expected)


def test_job_rerun_recovers_widget_cleanup_without_losing_observation():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT/'dashboard/app.py'),default_timeout=30)
    app.session_state['observation_context']=('30',0,None)
    app.session_state['observation_values']=(2,21,5)
    app.run()
    assert not app.exception
    assert app.selectbox(key='observe_unit').value==2
    assert app.selectbox(key='observe_node').value==21
    assert app.selectbox(key='observe_hour').value==5


def test_complete_interval_coverage_is_not_rejected_by_float_summation_roundoff():
    from dashboard.catalog import check_validation
    directory = ROOT/'results/dashboard_precompute/30-G5-h21'
    if not directory.exists(): pytest.skip('Native hourly witness not present')
    audit = json.loads((directory/'audit.json').read_text(encoding='utf-8'))
    audit['price_coverage_fraction']=.9999999999999999
    validation = json.loads((directory/'validation.json').read_text(encoding='utf-8'))
    assert check_validation(directory,audit,validation['model_sha256'])['status']=='passed'
    audit['intervals'][0]['price_ready']=False
    with pytest.raises(ValueError,match='complete'): check_validation(directory,audit,validation['model_sha256'])


def test_published_thirty_bus_catalog_covers_all_150_scalar_directions():
    data,_ = load_catalog()
    entries = [s for s in data['scenarios'] if s['case']=='30']
    expected = {(g,h) for g in range(6) for h in [None,*range(1,25)]}
    assert len(entries)==150
    assert {(s['generator_index'],s['bid_hour_1based']) for s in entries}==expected
    for entry in entries:
        s = get_scenario(data,'30',entry['generator_index'],entry['bid_hour_1based'])
        assert s['validation']['source_bound'] and s['validation']['full_price_coverage']
        assert s['validation']['independent_status']=='passed'
        assert evaluate(s,.123456789)['price'].shape==(30,24)
