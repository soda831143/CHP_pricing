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
