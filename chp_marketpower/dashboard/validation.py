"""Explicit, single-quote independent CHP check; never changes the archived map."""
import numpy as np

from dashboard.data import evaluate
from dashboard.service import ROOT


def validate_current(scenario, rho):
    from engine import load_case
    from price_vulnerability.model_identity import check_model_identity
    from price_vulnerability.oracle_compression import load_matched_compact
    from validate_affine_oracle import validate_point, VALIDATION_LIMITS
    directory = ROOT/scenario['source_oracle']
    audit,compression,_ = load_matched_compact(directory)
    from dashboard.catalog import digest
    if (digest(directory/'compact.npz')!=scenario['price_selector_sha256']
            or compression['source_sha256']!=scenario['raw_witness_sha256']):
        raise ValueError('Archived witnesses no longer match the displayed price selector')
    scope = audit['scope']
    gens,net = load_case(scope['case'],scope['network'],scope['T'],scope['segments'],scope['congestion'])
    if not check_model_identity(directory,gens,net,audit):
        raise ValueError('Missing model identity')
    q = evaluate(scenario,rho)
    with np.load(directory/'oracle.npz') as raw:
        data = {k:raw[k] for k in ('boundaries','values','prices','eq_duals','ineq_duals','lower_duals','upper_duals')}
    k = int(min(np.searchsorted(data['boundaries'],q['delta'],side='right')-1,len(data['boundaries'])-2))
    hour = scope.get('bid_hour_1based')
    result = validate_point(gens,net,scope['generator_index'],q['delta'],k,data,
        aggregate_output=scope.get('aggregate_output',False),hour=hour-1 if hour else None)
    # Include the displayed compressed path, not only the original raw selector.
    theta = (q['delta']-data['boundaries'][k])/(data['boundaries'][k+1]-data['boundaries'][k])
    raw_price = (1-theta)*data['prices'][k]+theta*data['prices'][k+1]
    result['display_vs_raw_price_difference_usd_per_mwh'] = float(np.max(abs(q['price']-raw_price)))
    limits = dict(VALIDATION_LIMITS,display_vs_raw_price_difference_usd_per_mwh=1e-8)
    if any(not np.isfinite(result[key]) or result[key]>limit for key,limit in limits.items()):
        raise RuntimeError(f'Current-quote numerical check failed: {result}')
    return dict(status='passed',scenario=scenario['id'],rho=q['rho'],delta=q['delta'],checks=result,limits=limits,
        model_sha256=scenario['model_sha256'],price_selector_sha256=scenario['price_selector_sha256'])
