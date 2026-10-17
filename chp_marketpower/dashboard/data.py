"""Pure archived-data queries: no solver import and no profit interpolation."""
import hashlib
import json
from pathlib import Path

import numpy as np

EXPORTS = Path(__file__).parent/'exports'


def load_export(directory=EXPORTS):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    raw = (directory/'data.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['data_sha256']:
        raise ValueError('Export checksum differs; regenerate from validated source archives')
    return json.loads(raw), manifest


def get_scenario(data, case, generator, hour=None):
    return next((s for s in data['scenarios'] if s['case'] == str(case)
                 and s['generator_index'] == generator and s['bid_hour_1based'] == hour), None)


def evaluate(scenario, rho):
    if scenario is None:
        raise ValueError('No price map for this generator and bid direction')
    if not np.isfinite(rho) or not scenario['rho_lower'] <= rho <= scenario['rho_upper']:
        raise ValueError('Offer outside this archived parameter domain')
    requested = float(rho*scenario['reference_slope'])
    delta = requested
    # Resolve UI rounding near saved UC boundaries, and always disclose the evaluated bid.
    boundaries = [r['left'] for r in scenario['physical_regions']]+[r['right'] for r in scenario['physical_regions']]
    if boundaries:
        nearest = min(boundaries, key=lambda d:abs(d-requested))
        if abs(nearest-requested) <= 1e-7:
            delta = nearest
    b = np.array(scenario['price_boundaries'])
    k = min(np.searchsorted(b, delta, side='right')-1, len(b)-2)
    theta = (delta-b[k])/(b[k+1]-b[k])
    price = (1-theta)*np.asarray(scenario['prices'][k])+theta*np.asarray(scenario['prices'][k+1])
    value = float(np.interp(delta, scenario['value_boundaries'], scenario['values']))
    physical = [r for r in scenario['physical_regions'] if r['left'] <= delta <= r['right']]
    return dict(requested_delta=requested, delta=float(delta), rho=float(delta/scenario['reference_slope']),
        snapped_to_boundary=bool(delta != requested), value=value, price=price,
        physical=physical, price_status='precomputed_verified',
        uc_status='precomputed_verified' if physical else 'not_available')


def sampled_settlement(scenario, delta, region_index):
    rows = [r for r in scenario['settlements'] if abs(r['delta']-delta) < 1e-10
            and r['physical_region'] == region_index]
    return sorted(rows, key=lambda r:r['generator_index']) if len(rows) == scenario['generator_count'] else None


def cache_key(scenario, delta, region_index, engine_sha):
    payload = dict(scenario=scenario['id'], model=scenario['model_sha256'],
        selector=scenario['price_selector_sha256'], physical=scenario['physical_sha256'],
        delta=float(delta).hex(), region=region_index, engine=engine_sha)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def profit_summary(rows, baseline_rows, generator):
    current = next((r['true_profit'] for r in rows or [] if r['generator_index']==generator), None)
    baseline = next((r['true_profit'] for r in baseline_rows or [] if r['generator_index']==generator), None)
    extra = current-baseline if current is not None and baseline is not None else None
    percent = 100*extra/abs(baseline) if extra is not None and abs(baseline)>1e-9 else None
    return dict(baseline=baseline, current=current, additional=extra, percent=percent)


def bid_response(scenario, node, hour, samples=201):
    """Rendering grid includes every selected-price knot; does not discover new regimes."""
    prices = np.asarray(scenario['prices'])
    if not 0<=node<prices.shape[1] or not 0<=hour<prices.shape[2] or samples<2:
        raise ValueError('Invalid observation or rendering sample count')
    b = np.asarray(scenario['price_boundaries'])
    delta = np.unique(np.r_[b,np.linspace(b[0],b[-1],samples)])
    time = np.stack([np.interp(delta,b,prices[:,node,t])-prices[0,node,t] for t in range(prices.shape[2])])
    space = np.stack([np.interp(delta,b,prices[:,n,hour])-prices[0,n,hour] for n in range(prices.shape[1])])
    return delta/scenario['reference_slope']*100,time,space


def parameter_rows(model):
    physical,costs = [],[]
    fields = ['P_min','P_max','R_up','R_down','SU_ramp','SD_ramp','T_on_min','T_off_min',
              'cost_su','cost_sd','cost_nl','initial_status','initial_power','initial_up_time','initial_down_time']
    for i,g in enumerate(model['generators']):
        physical.append(dict(unit=g['unit_id'],bus=model['gen_bus_map'][i]+1,**{k:g[k] for k in fields}))
        slopes,widths = g['pwl_slopes'] or [g['cost_var']],g['pwl_widths'] or [g['P_max']-g['P_min']]
        for k,(slope,width) in enumerate(zip(slopes,widths)):
            costs.append(dict(unit=g['unit_id'],segment=k+1,incremental_width_mw=width,
                slope_usd_mwh=slope,reference_slope_usd_mwh=slopes[len(slopes)//2]))
    return physical,costs
