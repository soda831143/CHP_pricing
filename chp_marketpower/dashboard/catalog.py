"""Publish validated maps individually; the standalone demonstration stays curated."""
import hashlib
import json
import uuid
import os
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from dashboard.data import EXPORTS, get_scenario, load_catalog

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('id', 'case', 'generator_index', 'bid_hour_1based', 'rho_lower', 'rho_upper',
          'model_sha256', 'price_selector_sha256', 'value_regions', 'price_segments')


@contextmanager
def publication_lock(output):
    # Both batch registration and curated export may publish while the UI reads.
    with (output/'catalog.lock').open('a+b') as lock:
        if lock.tell()==0: lock.write(b'0'); lock.flush()
        lock.seek(0)
        if os.name=='nt':
            import msvcrt
            deadline = time.monotonic()+10
            while True:
                try:
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                    break
                except OSError:
                    if time.monotonic()>deadline: raise
                    time.sleep(.05)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
        try: yield
        finally:
            lock.seek(0)
            if os.name=='nt': msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(lock,fcntl.LOCK_UN)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, payload):
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    pending = path.with_name(f'{path.name}.{uuid.uuid4().hex}.pending')
    pending.write_bytes(raw)
    for attempt in range(5):
        try:
            pending.replace(path)
            break
        except PermissionError:
            if attempt==4: raise
            time.sleep(.02)
    return hashlib.sha256(raw).hexdigest()


def validation_summary(directory, audit):
    path = directory/'validation.json'
    validation = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return dict(build_status=audit['status'], full_price_coverage=all(r['price_ready'] for r in audit['intervals']),
        endpoint_maximums=audit['max_full_lp_residuals'],
        maximum_common_primal_gap_usd=max((r['common_primal_gap'] for r in audit['intervals']), default=None),
        optimality_intervals=[{k:r[k] for k in ('left','right','common_primal_gap')} for r in audit['intervals']],
        independent_status=validation.get('status', 'not_available'),
        independent_points=len(validation.get('direct_checks', [])),
        independent_maximums=validation.get('maximums', {}), limits=validation.get('limits', {}),
        validation_sha256=digest(path) if path.exists() else None,
        source_bound=validation.get('source_sha256')==digest(directory/'oracle.npz'))


def publish(scenario, output=EXPORTS, expected=None):
    """Content-addressed payload first, atomic catalog last; no solver used here."""
    with publication_lock(output):
        return _publish(scenario,output,expected)


def _publish(scenario,output,expected=None):
    data, catalog = load_catalog(output)
    current = get_scenario(data,scenario['case'],scenario['generator_index'],scenario['bid_hour_1based'])
    if expected is not None and (current is None or any(current[k]!=v for k,v in expected.items())):
        raise ValueError('Published selector/UC map changed during this computation; refusing stale publication')
    if (current and current['price_selector_sha256']==scenario['price_selector_sha256']
            and current['physical_regions'] and not scenario['physical_regions']):
        scenario = dict(scenario,**{k:current[k] for k in ('physical_regions','physical_points','physical_sha256','physical_validation') if k in current})
    if scenario['model_sha256'] != data['models'][scenario['case']]['model_sha256']:
        raise ValueError('Scenario model differs from the published fixed model')
    reference = get_scenario(data, scenario['case'], 0 if scenario['case']=='30' else 10)
    if reference is None:
        raise ValueError('Missing reference selector for the zero-offer baseline audit')
    gap = float(np.max(abs(np.asarray(scenario['prices'][0])-np.asarray(reference['prices'][0]))))
    scenario['baseline_audit'] = dict(reference_scenario=reference['id'],
        reference_selector_sha256=reference['price_selector_sha256'],
        maximum_price_difference_usd_per_mwh=gap,
        value_difference_usd=abs(scenario['values'][0]-reference['values'][0]),
        shared_price_baseline=bool(gap<=1e-6),
        convention='Within-direction baseline only; no cross-direction profit ranking without a common settlement selection')
    folder = output/'scenarios'
    folder.mkdir(exist_ok=True)
    raw = json.dumps(scenario, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    sha = hashlib.sha256(raw).hexdigest()
    path = folder/f'{scenario["id"]}-{sha[:16]}.json'
    if not path.exists():
        write_json(path, scenario)
    entry = {k:scenario[k] for k in FIELDS}
    entry.update(payload=path.relative_to(output).as_posix(), sha256=sha,
                 baseline_audit=scenario['baseline_audit'],
                 offline_seconds=scenario['offline_seconds'],uc_regions=len(scenario['physical_regions']))
    catalog['scenarios'] = [s for s in catalog['scenarios'] if s['id']!=entry['id']]+[entry]
    catalog['scenarios'].sort(key=lambda s:(int(s['case']), s['generator_index'], s['bid_hour_1based'] or 0))
    write_json(output/'catalog.json', catalog)
    return entry


def seed(data, output=EXPORTS):
    """Split the curated release too, so local startup never loads all price arrays."""
    with publication_lock(output):
        _seed(data,output)


def _seed(data,output):
    existing = load_catalog(output)[0] if (output/'catalog.json').exists() else None
    shared = {k:v for k,v in data.items() if k!='scenarios'}
    raw = json.dumps(shared,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    name = f'shared-{hashlib.sha256(raw).hexdigest()[:16]}.json'
    sha = write_json(output/name, shared)
    # Preserve registered extensions on a curated re-export; recheck their model on load.
    old = json.loads((output/'catalog.json').read_text(encoding='utf-8')) if (output/'catalog.json').exists() else {}
    catalog = dict(schema=1, shared_payload=name, shared_sha256=sha, scenarios=old.get('scenarios', []))
    folder = output/'scenarios'
    folder.mkdir(exist_ok=True)
    for scenario in data['scenarios']:
        previous = get_scenario(existing,scenario['case'],scenario['generator_index'],scenario['bid_hour_1based']) if existing else None
        if (previous and previous['price_selector_sha256']==scenario['price_selector_sha256']
                and previous['physical_regions'] and not scenario['physical_regions']):
            scenario = dict(scenario,**{k:previous[k] for k in ('physical_regions','physical_points','physical_sha256','physical_validation') if k in previous})
        raw = json.dumps(scenario, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        sha = hashlib.sha256(raw).hexdigest()
        path = folder/f'{scenario["id"]}-{sha[:16]}.json'
        write_json(path, scenario)
        entry = dict({k:scenario[k] for k in FIELDS}, payload=path.relative_to(output).as_posix(), sha256=sha)
        catalog['scenarios'] = [s for s in catalog['scenarios'] if s['id']!=entry['id']]+[entry]
    write_json(output/'catalog.json', catalog)
    seeded,_ = load_catalog(output)
    for scenario in data['scenarios']:
        _publish(get_scenario(seeded,scenario['case'],scenario['generator_index'],scenario['bid_hour_1based']),output)


def check_validation(directory,audit,model_sha):
    """One release gate for both original curated maps and newly computed maps."""
    scope = audit['scope']
    validation = json.loads((directory/'validation.json').read_text(encoding='utf-8'))
    if (validation['status']!='passed' or not validation['full_price_coverage']
            or validation['scope']!=scope or validation.get('source_sha256')!=digest(directory/'oracle.npz')
            or not validation.get('direct_checks') or not all(r['price_ready'] for r in audit['intervals'])):
        raise ValueError('Registration requires a complete, source-bound independent validation')
    # Do not trust a success label alone: check every recorded numerical test.
    from validate_affine_oracle import VALIDATION_LIMITS
    limits = VALIDATION_LIMITS
    if validation.get('limits')!=limits or any(not np.isfinite(r[k]) or r[k]>limit
                         for r in validation['direct_checks'] for k,limit in limits.items()):
        raise ValueError('Independent numerical residuals exceed their declared limits')
    if {r['interval'] for r in validation['direct_checks']} != set(range(1,len(audit['intervals'])+1)):
        raise ValueError('Independent validation must sample every original interval')
    for r in validation['direct_checks']:
        interval = audit['intervals'][r['interval']-1]
        if not interval['left']<r['delta']<interval['right']:
            raise ValueError('Independent validation point must be interior to its declared interval')
    if validation.get('model_sha256')!=model_sha:
        raise ValueError('Independent validation belongs to another model')
    return validation


def register(directory, output=EXPORTS):
    """Trust boundary: raw/compact, model, scope and independent validation must agree."""
    from engine import load_case
    from price_vulnerability.model_identity import model_identity, check_model_identity
    from price_vulnerability.oracle_compression import load_matched_compact
    audit, compression, compact = load_matched_compact(directory)
    scope = audit['scope']
    gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
    if not check_model_identity(directory, gens, net, audit):
        raise ValueError('Missing model-data identity')
    validation = check_validation(directory,audit,model_identity(gens,net)['model_sha256'])
    g = scope['generator_index']
    reference = float(gens[g].pwl_slopes[len(gens[g].pwl_slopes)//2] if gens[g].pwl_slopes else gens[g].cost_var)
    if (compact['value_boundaries'][0]!=0. or compact['value_boundaries'][-1]!=.5*reference
            or scope['network']!='ptdf' or scope['T']!=24 or scope['segments']!=3 or scope['congestion']!='tight'):
        raise ValueError('Map differs from the dashboard domain/model configuration')
    hour = scope.get('bid_hour_1based')
    row = dict(id=f'{scope["case"]}-G{g+1}-'+('all' if hour is None else f'h{hour}'),
        case=scope['case'], generator_index=g, generator_count=len(gens), bid_hour_1based=hour,
        reference_slope=reference, rho_lower=0., rho_upper=.5,
        model_sha256=model_identity(gens,net)['model_sha256'],
        price_selector_sha256=digest(directory/'compact.npz'), raw_witness_sha256=digest(directory/'oracle.npz'),
        source_oracle=directory.relative_to(ROOT).as_posix(), value_regions=compression['merged_value_intervals'],
        price_segments=compression['selected_price_intervals'], offline_seconds=audit['offline_seconds'],
        value_tolerance_usd=audit['value_tolerance_usd'], price_tolerance_usd=audit['price_tolerance_usd'],
        common_primal_tolerance_usd=audit['price_tolerance_usd'],
        price_compression_tolerance_usd_per_mwh=compression['price_tolerance_usd_per_mwh'],
        export_validation='Source-matched complete dual witnesses and independent interior validation at publication',
        identity_scope='Model identity saved with the native oracle', physical_regions=[], settlements=[], profit_candidates=[],
        physical_sha256=hashlib.sha256(b'[]').hexdigest(), validation=validation_summary(directory,audit))
    row.update({k:compact[k].tolist() for k in ('value_boundaries','values','price_boundaries','prices')})
    data,_ = load_catalog(output)
    previous = get_scenario(data,scope['case'],g,hour)
    if previous and previous['price_selector_sha256']==row['price_selector_sha256']:
        for key in ('physical_regions','physical_points','physical_sha256','physical_validation','settlements','profit_candidates'):
            if key in previous: row[key]=previous[key]
    entry = publish(row,output)
    return dict(id=entry['id'], status='published', solved_points=audit['solved_points'],
        value_regions=row['value_regions'], price_segments=row['price_segments'], offline_seconds=row['offline_seconds'],
        independent_points=len(validation['direct_checks']), residuals=validation['maximums'],
        baseline_audit=entry['baseline_audit'], payload=entry['payload'])


def register_physical(scenario, directory, output=EXPORTS):
    """Check the archived full UC plans against fixed data and endpoint global bounds."""
    from engine import load_case
    from benchmarks.unit_self_schedule import dispatch_cost
    from run_initial_condition_audit import schedule_residuals
    from price_vulnerability.model_identity import model_identity
    report = json.loads((directory/'physical_regions.json').read_text(encoding='utf-8'))
    if (report['status']!='numerically_validated_complete' or not all(r['ready'] for r in report['physical_regions'])
            or report['source_sha256']!=scenario['raw_witness_sha256']
            or report['compact_sha256']!=scenario['price_selector_sha256']
            or report.get('physical_archive_sha256')!=digest(directory/'physical_plans.npz')):
        raise ValueError('UC map is incomplete or belongs to a different price/source version')
    gens,net = load_case(scenario['case'],'ptdf',24,3,'tight')
    if model_identity(gens,net)['model_sha256']!=scenario['model_sha256']:
        raise ValueError('Current fixed model differs from the price map')
    points = {p['delta']:p for p in report['physical_points']}
    maximum = 0.
    regions = []
    with np.load(directory/'physical_plans.npz') as raw:
        for k,r in enumerate(report['physical_regions']):
            if not r['ready']: raise ValueError('Unvalidated UC interval')
            indices = np.flatnonzero(raw['deltas']==r['witness_delta'])
            if len(indices)!=1: raise ValueError('Missing/ambiguous UC plan witness')
            p,u = raw['outputs'][indices[0]],raw['commitments'][indices[0]]
            residual = max(schedule_residuals(gens,net,p,u).values())
            maximum = max(maximum,residual)
            if residual>1e-6: raise ValueError('UC plan violates physical constraints')
            cost = sum(dispatch_cost(g,p[i],u[i]) for i,g in enumerate(gens))
            g = scenario['generator_index']
            exposure = float((p[g]-gens[g].P_min*u[g]).sum())
            gap = max(abs(cost+d*exposure-points[d]['lower_bound']) for d in (r['left'],r['right']))
            if gap>report['physical_tolerance_usd']: raise ValueError('UC endpoint global bound gap exceeds tolerance')
            regions.append(dict(r,region_index=k,output=p.tolist(),commitment=u.tolist()))
    if (not regions or regions[0]['left']!=0. or regions[-1]['right']!=scenario['reference_slope']*.5
            or any(a['right']!=b['left'] for a,b in zip(regions[:-1],regions[1:]))):
        raise ValueError('UC regions do not cover the full declared domain')
    row = dict(scenario,physical_regions=regions,physical_points=report['physical_points'],
        physical_sha256=hashlib.sha256(json.dumps(regions,sort_keys=True).encode()).hexdigest(),
        physical_validation=dict(report_sha256=digest(directory/'physical_regions.json'),
            archive_sha256=report['physical_archive_sha256'],source=directory.relative_to(ROOT).as_posix(),
            maximum_feasibility_residual=maximum,global_bound_tolerance_usd=report['physical_tolerance_usd'],
            uc_solves=report['uc_solves'],offline_seconds=report['physical_discovery_seconds']))
    expected = {k:scenario[k] for k in ('model_sha256','raw_witness_sha256','price_selector_sha256','physical_sha256')}
    return publish(row,output,expected=expected)


def write_inventory(output=EXPORTS):
    """Snapshot actual published coverage, not the attempted batch queue."""
    import csv
    data,_ = load_catalog(output)
    rows = []
    for entry in data['scenarios']:
        s = get_scenario(data,entry['case'],entry['generator_index'],entry['bid_hour_1based'])
        v = s['validation']
        rows.append(dict(id=s['id'],case=s['case'],generator=s['generator_index']+1,hour=s['bid_hour_1based'],
            status='published',solved_points=len(v['optimality_intervals'])+1,
            value_regions=s['value_regions'],price_segments=s['price_segments'],
            discovery_seconds=s['offline_seconds'],independent_points=v['independent_points'],
            validation_source_bound=v['source_bound'],uc_regions=len(s['physical_regions']),
            zero_offer_price_difference_usd_per_mwh=s['baseline_audit']['maximum_price_difference_usd_per_mwh'],
            maximum_value_error_usd=v['independent_maximums'].get('value_error_usd'),
            maximum_selector_gap_usd=v['independent_maximums'].get('selector_dual_gap_usd'),
            model_sha256=s['model_sha256'],selector_sha256=s['price_selector_sha256'],payload_sha256=entry['sha256']))
    thirty = [r for r in rows if r['case']=='30']
    report = dict(schema=1,thirty_bus=dict(expected=150,published=len(thirty),
        all_day=sum(r['hour'] is None for r in thirty),hourly=sum(r['hour'] is not None for r in thirty),
        all_day_uc_maps=sum(r['hour'] is None and r['uc_regions']>0 for r in thirty),
        all_source_bound=all(r['validation_source_bound'] for r in thirty)),scenarios=rows,
        scope='150 separate scalar bid directions, not a joint 24-dimensional offer map. Price coverage is not full economic-result coverage.')
    write_json(output/'coverage.json',report)
    with (output/'coverage.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return report
