"""Explicit on-demand physical UC and all-unit LOC settlement, cached by exact bid/version."""
import hashlib
import json
import threading
import time
from uuid import uuid4
from pathlib import Path

import numpy as np

from dashboard.data import evaluate, cache_key

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.Lock()
CACHE = ROOT/'results/dashboard_runtime_cache'


def engine_sha():
    paths = [ROOT.parent/'chp_energy/chp_solver/schedule_run.py',
             ROOT.parent/'chp_energy/benchmarks/unit_self_schedule.py',
             ROOT/'strategic_market_simulation/profit_sweep.py',
             ROOT/'dashboard/service.py', ROOT/'dashboard/data.py',
             ROOT/'price_vulnerability/affine_oracle.py', ROOT/'engine.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()


def cached(scenario, delta, region_index, directory=CACHE):
    key = cache_key(scenario, delta, region_index, engine_sha())
    path = directory/f'{key}.json'
    if path.exists():
        result = json.loads(path.read_text(encoding='utf-8'))
        if result['cache_key'] != key or result['status'] != 'solved_on_demand':
            raise ValueError('Settlement cache is not matched to this query/version')
        from engine import load_case
        from price_vulnerability.model_identity import model_identity
        gens, net = load_case(scenario['case'], 'ptdf', 24, 3, 'tight')
        if model_identity(gens, net)['model_sha256'] != scenario['model_sha256']:
            raise ValueError('Current model changed; refusing the live settlement cache. Archived price data remains a frozen scenario.')
        return result
    return None


def solve(scenario, rho, region_index=None, progress=lambda message: None, directory=CACHE):
    from engine import load_case, ScheduleRunMILP
    from price_vulnerability.model_identity import model_identity
    from price_vulnerability.affine_oracle import bid_adder_matrix
    from strategic_market_simulation.profit_sweep import _settle_target
    from run_initial_condition_audit import schedule_residuals
    query = evaluate(scenario, rho)
    delta = query['delta']
    available = query['physical']
    if available and region_index not in [r['region_index'] for r in available]:
        raise ValueError('Select one of the adjacent archived physical regions at this bid')
    result = cached(scenario, delta, region_index, directory)
    if result:
        return result
    with LOCK:
        started = time.perf_counter()
        gens, net = load_case(scenario['case'], 'ptdf', 24, 3, 'tight')
        if model_identity(gens, net)['model_sha256'] != scenario['model_sha256']:
            raise ValueError('Current data/initial state differs from the exported price model')
        hour = scenario['bid_hour_1based']
        adders = bid_adder_matrix(len(gens), net.T, scenario['generator_index'], delta,
                                 hour-1 if hour else None)
        if available:
            region = next(r for r in available if r['region_index'] == region_index)
            p, u = np.asarray(region['output']), np.asarray(region['commitment'])
            uc_status = 'precomputed_verified'
            physical_audit = dict(common_plan_gap_usd=region['common_plan_gap_usd'],
                witness_delta=region['witness_delta'], region_left=region['left'], region_right=region['right'])
        else:
            progress('求解当前报价的全局物理 UC…')
            uc = ScheduleRunMILP(gens, net, bid_adders=adders)
            p, u, _ = uc.solve(require_optimal=True, mip_gap=0.)
            uc_status = 'solved_on_demand'
            physical_audit = dict(uc_solve_info=uc.solve_info)
        residuals = schedule_residuals(gens, net, p, u)
        physical_audit['residuals'] = residuals
        if max(residuals.values()) > 1e-6:
            raise RuntimeError('Physical execution failed feasibility checks')
        rows = []
        for i, gen in enumerate(gens):
            progress(f'计算 G{i+1}/{len(gens)} 的最优自调度与申报 LOC…')
            row = _settle_target(gen, gen, query['price'][net.gen_bus_idx(i)], p[i], u[i],
                                 mip_gap=0., bid_adders=adders[i])
            rows.append(dict(unit=gen.unit_id, generator_index=i, generation_mwh=float(p[i].sum()),
                **{k:v for k, v in row.items() if not isinstance(v, np.ndarray)}))
        key = cache_key(scenario, delta, region_index, engine_sha())
        result = dict(status='solved_on_demand', uc_status=uc_status, cache_key=key,
            delta=delta, rho=query['rho'], region_index=region_index, elapsed_seconds=time.perf_counter()-started,
            model_sha256=scenario['model_sha256'], price_selector_sha256=scenario['price_selector_sha256'],
            physical_audit=physical_audit, output=p.tolist(), commitment=u.tolist(), rows=rows)
        directory.mkdir(parents=True, exist_ok=True)
        pending = directory/f'{key}.{uuid4().hex}.pending'
        pending.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
        pending.replace(directory/f'{key}.json')
        return result
