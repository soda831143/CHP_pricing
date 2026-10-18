"""E0-E1 only: frozen-model and common-price boundary settlement audit.

Run from chp_marketpower: python -m mechanism_study.run_study --stage audit
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from importlib.metadata import version

import numpy as np

from engine import load_case, ScheduleRunMILP, SingleNodeNetwork
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.affine_oracle import bid_adder_matrix, dual_audit_passed
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.model_identity import model_identity, check_model_identity
from price_vulnerability.oracle_compression import load_matched_compact, query_compact
from run_initial_condition_audit import schedule_residuals
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study.profit_identity import hourly_cost, ledger, paired_identity

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT/'results/scope_study_20261016/30_bracket_repeat1'
PHYSICAL = ROOT/'results/targeted_study_20261016/30_G1_profit_0to50'
DEFAULT_OUTPUT = ROOT/'results/mechanism_20261018'
LIMITS = dict(primal_feasibility=1e-7, dual_sign=1e-7, stationarity=1e-7,
    duality_gap=1e-6, row_complementarity=1e-6, bound_complementarity=1e-6,
    objective_reconstruction=1e-6, price_projection=1e-8)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    temporary = path.with_suffix(path.suffix+'.pending')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def csv_write(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT.parent, encoding='utf-8').strip()


def source_files():
    paths = [ORACLE/name for name in ('audit.json', 'compression.json', 'compact.npz',
                                    'oracle.npz', 'model_identity.json')]
    paths += [PHYSICAL/name for name in ('profit_range.json', 'physical_regions.json',
                                       'physical_plans.npz', 'direct_validation.json')]
    paths += list((ROOT.parent/'chp_energy').rglob('*.py'))
    paths += list((ROOT/'price_vulnerability').glob('*.py'))
    paths += list((ROOT/'mechanism_study').glob('*.py'))
    paths += [ROOT/name for name in ('engine.py', 'run_profit_range.py', 'run_initial_condition_audit.py',
                                     'strategic_market_simulation/profit_sweep.py')]
    import gurobi_compat
    paths += [Path(gurobi_compat.__file__)]
    return {str(p.resolve()):sha(p) for p in sorted(set(paths)) if p.is_file()}


def load_inputs():
    audit, compression, compact = load_matched_compact(ORACLE)
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    expected_scope = dict(case='30', network='ptdf', T=24, segments=3, congestion='tight', generator_index=0)
    if any(audit['scope'].get(k) != v for k, v in expected_scope.items()):
        raise ValueError('Wrong Oracle direction or physical case')
    if audit['scope'].get('bid_hour_1based') is not None:
        raise ValueError('E1 requires the original all-day bid direction')
    if not check_model_identity(ORACLE, gens, net, audit):
        raise ValueError('Unbound legacy maps cannot support this economic audit')
    report = read(PHYSICAL/'profit_range.json')
    if (report['source_sha256'] != compression['source_sha256']
            or report['compact_sha256'] != sha(ORACLE/'compact.npz')
            or report['status'] != 'numerically_validated_complete'):
        raise ValueError('Physical study belongs to a different price map or is incomplete')
    delta = report['maximizing_candidate']['delta']
    adjacent = [r for r in report['physical_regions'] if r['left'] <= delta <= r['right']]
    if len(adjacent) != 2 or not all(r['ready'] for r in adjacent):
        raise ValueError('Need two archived common-plan regions at the winning boundary')
    with np.load(PHYSICAL/'physical_plans.npz') as archive:
        saved = {float(d):(archive['outputs'][i], archive['commitments'][i])
                 for i, d in enumerate(archive['deltas'])}
    plans = {label:saved[r['witness_delta']] for label, r in zip(('A_left', 'B_right'), adjacent)}
    if any(g.initial_status or g.initial_power or g.initial_down_time < g.T_off_min for g in gens):
        raise ValueError('Unexpected initial state; do not replace the archived cold start')
    return gens, net, compact, report, delta, adjacent, plans


def selected_dual_audit(persistent, raw, compact, delta, direct):
    """Audit the archived FULL dual at the selected price, not a fresh-solver price."""
    boundaries = raw['boundaries']
    k = min(int(np.searchsorted(boundaries, delta, side='right'))-1, len(boundaries)-2)
    if not raw['price_ready'][k]:
        raise ValueError('Selected raw interval has no price certificate')
    theta = (delta-boundaries[k])/(boundaries[k+1]-boundaries[k])
    def interp(key):
        return (1-theta)*raw[key][k]+theta*raw[key][k+1]
    c, pi, mu, zl, zu = [interp(key) for key in
        ('objectives', 'eq_duals', 'ineq_duals', 'lower_duals', 'upper_duals')]
    if np.max(np.abs(c-direct.objective)) > 1e-8:
        raise ValueError('Archived objective differs from the freshly constructed model')
    eq, b, nf, ns, ineq, h = persistent.matrices
    lb, ub = persistent.lb, persistent.ub
    il, iu = np.flatnonzero(lb > -1e20), np.flatnonzero(ub < 1e20)
    value, price = query_compact(delta, *[compact[key] for key in
        ('value_boundaries', 'values', 'price_boundaries', 'prices')])
    # The original interval is value-affine; audit one archived common primal.
    costs = raw['primals']@c
    j = int(np.argmin(abs(costs-value)))
    x = raw['primals'][j]
    dual_value = float(b@pi+h@mu+lb[il]@zl[il]+ub[iu]@zu[iu])
    balance = pi[nf+ns:nf+ns+persistent.network.T]
    lines = mu[-2*persistent.network.N_line*persistent.network.T:]
    projected = balance[None, :]+persistent.network.PTDF.T@(
        lines[0::2].reshape(persistent.network.N_line, -1)
        -lines[1::2].reshape(persistent.network.N_line, -1))
    residual = dict(
        primal_feasibility=float(max(np.max(abs(eq@x-b)), np.max(ineq@x-h),
                                    np.max(lb-x), np.max(x-ub), 0.)),
        dual_sign=float(max(np.max(mu, initial=0.), -np.min(zl, initial=0.), np.max(zu, initial=0.),
                            np.max(abs(zl[np.setdiff1d(np.arange(len(c)), il)]), initial=0.),
                            np.max(abs(zu[np.setdiff1d(np.arange(len(c)), iu)]), initial=0.))),
        stationarity=float(np.max(abs(c-eq.T@pi-ineq.T@mu-zl-zu))),
        duality_gap=abs(float(c@x)-dual_value),
        row_complementarity=float(np.max(abs(mu*(h-ineq@x)), initial=0.)),
        bound_complementarity=float(max(np.max(abs(zl[il]*(x[il]-lb[il])), initial=0.),
                                         np.max(abs(zu[iu]*(ub[iu]-x[iu])), initial=0.))),
        objective_reconstruction=max(abs(float(c@x)-value), abs(direct.value-value)),
        price_projection=float(max(np.max(abs(projected-price)), np.max(abs(interp('prices')-price)))))
    if any(not np.isfinite(residual[key]) or residual[key] > limit for key, limit in LIMITS.items()):
        raise ValueError(f'Archived selected full dual failed: {residual}')
    return dict(residuals=residual, raw_interval=k, theta=float(theta), primal_index=j,
                selected_value=value, selected_dual_value=dual_value,
                fresh_price_difference_usd_per_mwh=float(np.max(abs(direct.price-price)))), dict(
        price=price, primal=x, objective=c, eq_dual=pi, ineq_dual=mu, lower_dual=zl, upper_dual=zu)


def run(args):
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    gens, net, compact, historical, delta, regions, plans = load_inputs()
    extent = float(compact['value_boundaries'][-1]-compact['value_boundaries'][0])
    jobs = [('baseline', 0.), ('boundary', delta), ('left', delta-1e-5*extent), ('right', delta+1e-5*extent)]
    if not regions[0]['left'] < jobs[2][1] < delta < jobs[3][1] < regions[1]['right']:
        raise ValueError('Prespecified perturbations leave the neighboring UC regions')
    if args.dry_run:
        print(json.dumps(dict(stage='E0-E1', jobs=jobs, planned_uc_solves=4, planned_chp_solves=4,
                             planned_self_schedule_solves=4, model=model_identity(gens, net)), indent=2))
        return
    sources = source_files()
    manifest_path = out/'manifest.json'
    policy = dict(max_uc_solves=args.max_uc_solves, max_chp_solves=args.max_chp_solves,
                  max_self_schedule_solves=4, time_budget_seconds=args.time_budget, seed=args.seed,
                  threads=1, requested_mip_gap=0., physical_cost_tolerance_usd=1e-5,
                  accounting_tolerance_usd=1e-6, selected_dual_limits=LIMITS)
    if manifest_path.exists():
        if not args.resume:
            raise ValueError('Existing manifest; use --resume or a new directory')
        manifest = read(manifest_path)
        if manifest['source_sha256'] != sources or manifest['policy'] != policy:
            raise ValueError('Resume rejected: source fingerprints or budgets changed')
        if manifest['status'] == 'passed':
            print('Completed E0-E1 checkpoint verified; no solver calls repeated')
            return
    else:
        if args.resume:
            raise ValueError('No checkpoint to resume')
        manifest = dict(schema=1, stage='E0-E1', status='running',
            git_commit=git('rev-parse', 'HEAD'), git_branch=git('branch', '--show-current'),
            initial_git_status=git('status', '--porcelain=v1', '-uall'),
            model_identity=model_identity(gens, net), source_sha256=sources,
            policy=policy, solver=dict(name='COPT', version=version('coptpy'), python=sys.version),
            definitions=dict(bid='C_rep=C_true+delta*sum_t(p-Pmin*u); delta=rho*41.982 USD/MWh; hourly duration=1 h',
                price='Original compact path, projected from interpolation of archived COMPLETE optimal duals; no re-selection',
                loc='Complete reported opportunity cost M_rep-(lambda dot p_UC-C_rep), not ISO make-whole',
                boundary='Retain both archived adjacent full-system plans separately; no hidden tie-break',
                legacy_binding='Retrospective model binding retained as such; independently re-audited at these four bids'),
            jobs=[dict(name=name, delta=d) for name, d in jobs], attempts=[], completed=[])
    write(manifest_path, manifest)
    started = time.perf_counter()

    def checkpoint():
        manifest['status'] = 'running'
        write(manifest_path, manifest)

    def spend(kind, name):
        limit = policy[f'max_{kind}_solves']
        if sum(a['kind'] == kind for a in manifest['attempts']) >= limit:
            raise RuntimeError(f'{kind} solve budget exhausted; failed attempts are counted')
        if time.perf_counter()-started >= args.time_budget:
            raise RuntimeError('Time budget exhausted')
        manifest['attempts'].append(dict(kind=kind, job=name, status='started'))
        checkpoint()
        return manifest['attempts'][-1]

    # The wrapper only sets study-local solver parameters; existing engines are untouched.
    import gurobi_compat as gp
    original_model = gp.Model
    def bounded_model(*a, **kw):
        m = original_model(*a, **kw)
        m.setParam('Threads', 1)
        m.setParam('RandSeed', args.seed)
        m.setParam('TimeLimit', max(.01, args.time_budget-(time.perf_counter()-started)))
        return m
    gp.Model = bounded_model
    try:
        with np.load(ORACLE/'oracle.npz') as data:
            raw = {key:data[key].copy() for key in ('boundaries', 'price_ready', 'primals',
                'objectives', 'eq_duals', 'ineq_duals', 'lower_duals', 'upper_duals', 'prices')}
        for name, d in jobs:
            if name in manifest['completed']:
                record = read(out/f'{name}.json')
                if sha(out/f'{name}.npz') != record['checkpoint_sha256']:
                    raise ValueError('Checkpoint bytes changed')
                continue
            print(f'E1 {name}: delta={d:.17g}', flush=True)
            reported = apply_generator_adder(gens, 0, d)
            attempt = spend('uc', name)
            uc = ScheduleRunMILP(reported, net)
            p, u, objective = uc.solve(require_optimal=True, mip_gap=0.)
            attempt.update(status='optimal', solver_info=uc.solve_info)
            np.savez_compressed(out/f'{name}_uc.npz', output=p, commitment=u)
            checkpoint()
            attempt = spend('chp', name)
            persistent = PersistentCHP(gens, net, 0)
            direct = persistent.solve(d)
            if not dual_audit_passed(direct):
                raise ValueError('Fresh CHP failed complete primal-dual audit')
            certificate, arrays = selected_dual_audit(persistent, raw, compact, d, direct)
            attempt.update(status='optimal', residuals=direct.audit)
            checkpoint()
            attempt = spend('self_schedule', name)
            price = arrays['price'][net.gen_bus_idx(0)]
            ss = _settle_target(gens[0], reported[0], price, p[0], u[0], mip_gap=0.)
            ss_p, ss_u = ss['self_output_mw'], ss['self_commitment']
            ss_residual = schedule_residuals([gens[0]], SingleNodeNetwork(ss_p), ss_p[None, :], ss_u[None, :])
            ss_reconstructed = float(price@ss_p-dispatch_cost(reported[0], ss_p, ss_u))
            if max(ss_residual.values()) > 1e-6 or abs(ss_reconstructed-ss['best_reported_profit']) > 1e-6:
                raise ValueError('Self-schedule physical or objective reconstruction failed')
            if ss['self_schedule_gap_usd'] > 1e-6:
                raise ValueError('Self-schedule optimum not certified to accounting tolerance')
            attempt.update(status='optimal', upper_bound=ss['self_schedule_upper_bound'],
                           gap_usd=ss['self_schedule_gap_usd'])
            checkpoint()
            chosen = dict(solver=(p, u))
            if name in ('baseline', 'boundary'):
                chosen.update(plans)
            else:
                chosen['A_left' if name == 'left' else 'B_right'] = plans['A_left' if name == 'left' else 'B_right']
            ledgers = []
            for label, (pp, uu) in chosen.items():
                residual = schedule_residuals(gens, net, pp, uu)
                if max(residual.values()) > 1e-6:
                    raise ValueError(f'Infeasible physical plan {name}/{label}: {residual}')
                row = ledger(gens[0], pp[0], uu[0], price, d, ss['best_reported_profit'])
                if label == 'solver' and abs(row['true_profit_usd']-ss['true_profit']) > 1e-6:
                    raise ValueError('Independent ledger differs from the existing settlement engine')
                cost = float(sum(dispatch_cost(gen, pp[i], uu[i]) for i, gen in enumerate(reported)))
                basecost = float(sum(dispatch_cost(gen, pp[i], uu[i]) for i, gen in enumerate(gens)))
                wedge_error = abs(cost-basecost-d*row['exposure_mwh'])
                # Audit both cost implementations and reject double-counted slope adders.
                direct_adder_cost = sum(dispatch_cost(gen, pp[i], uu[i], bid_adders=bid_adder_matrix(
                    len(gens), net.T, 0, d)[i]) for i, gen in enumerate(gens))
                if max(abs(cost-direct_adder_cost), wedge_error, abs(row['identity_residual_usd'])) > 1e-6:
                    raise ValueError('Cost-adder / accounting identity failed')
                gap = cost-uc.solve_info['lower_bound']
                optimal_required = name != 'baseline' or label == 'solver'
                if optimal_required and abs(gap) > 1e-5:
                    raise ValueError('Archived common plan not supported by fresh global UC bound')
                if cost < uc.solve_info['lower_bound']-1e-5 or certificate['selected_value'] > uc.solve_info['lower_bound']+1e-5:
                    raise ValueError('CHP / UC lower bound ordering failed')
                if abs(row['true_cost_usd']-dispatch_cost(gens[0], pp[0], uu[0])) > 1e-6:
                    raise ValueError('Independent hourly cost reconstruction failed')
                ledgers.append(dict(job=name, delta=d, rho=d/41.982, plan=label,
                    uc_optimal_required=optimal_required, system_reported_cost_usd=cost,
                    system_true_cost_usd=basecost, uc_lower_bound_usd=uc.solve_info['lower_bound'],
                    plan_gap_to_uc_bound_usd=gap, physical_residuals=residual,
                    self_schedule_gap_usd=ss['self_schedule_gap_usd'],
                    self_exposure_mwh=float(np.sum(ss_p-gens[0].P_min*ss_u)),
                    derivative_status='not_assessed_E1', **row))
                arrays[f'p_{label}'], arrays[f'u_{label}'] = pp, uu
            arrays.update(self_p=ss_p, self_u=ss_u)
            np.savez_compressed(out/f'{name}.npz', **arrays)
            record = dict(job=name, delta=d, fresh_chp_audit=direct.audit,
                selected_chp_certificate=certificate, uc_solve_info=uc.solve_info,
                uc_objective_reconstruction_usd=abs(objective-sum(dispatch_cost(gen, p[i], u[i]) for i, gen in enumerate(reported))),
                self_physical_residuals=ss_residual, self_objective_residual_usd=abs(ss_reconstructed-ss['best_reported_profit']),
                ledgers=ledgers, checkpoint_sha256=sha(out/f'{name}.npz'))
            if record['uc_objective_reconstruction_usd'] > 1e-6:
                raise ValueError('Fresh UC objective reconstruction failed')
            write(out/f'{name}.json', record)
            manifest['completed'].append(name)
            checkpoint()
        results(out, gens, net, historical, jobs)
        if source_files() != sources:
            raise ValueError('Input or implementation changed during execution')
        manifest.update(status='passed', e0_gate='passed', e1_gate='passed',
                        later_stages='not_run; return E0-E1 evidence before E2-E4',
                        run_seconds=time.perf_counter()-started)
        manifest['output_sha256'] = {p.name:sha(p) for p in out.iterdir()
            if p.is_file() and p.suffix in ('.json', '.npz', '.csv') and p.name != 'manifest.json'}
        write(manifest_path, manifest)
        print('E0-E1 passed; E2-E4 not started', flush=True)
    except Exception as error:
        manifest.update(status='failed', error=f'{type(error).__name__}: {error}')
        for a in manifest['attempts']:
            if a['status'] == 'started':
                a.update(status='failed_or_incomplete', error=str(error))
        write(manifest_path, manifest)
        raise
    finally:
        gp.Model = original_model


def results(out, gens, net, historical, jobs):
    summary, hourly, physical, prices = [], [], [], []
    for name, d in jobs:
        record = read(out/f'{name}.json')
        with np.load(out/f'{name}.npz') as data:
            price = data['price']
            for n, t in np.ndindex(price.shape):
                prices.append(dict(job=name, delta=d, bus=n+1, hour=t+1, price_usd_per_mwh=float(price[n,t])))
            for row in record['ledgers']:
                summary.append({k:v for k,v in row.items() if k != 'physical_residuals'})
                p, u = data[f'p_{row["plan"]}'], data[f'u_{row["plan"]}']
                ss_p, ss_u = data['self_p'], data['self_u']
                cost = hourly_cost(gens[0], p[0], u[0])
                for i, gen in enumerate(gens):
                    previous = np.r_[gen.initial_status, u[i,:-1]]
                    su, sd = np.maximum(u[i]-previous, 0.), np.maximum(previous-u[i], 0.)
                    for t in range(net.T):
                        physical.append(dict(job=name, delta=d, plan=row['plan'], unit=gen.unit_id,
                            hour=t+1, output_mw=float(p[i,t]), commitment=float(u[i,t]),
                            startup=float(su[t]), shutdown=float(sd[t]), pmin_mw=gen.P_min))
                for t in range(net.T):
                    hourly.append(dict(job=name, delta=d, plan=row['plan'], hour=t+1,
                        price_usd_per_mwh=float(price[net.gen_bus_idx(0),t]), output_mw=float(p[0,t]),
                        commitment=float(u[0,t]), startup=float(max(0., u[0,t]-(gens[0].initial_status if t==0 else u[0,t-1]))),
                        shutdown=float(max(0., (gens[0].initial_status if t==0 else u[0,t-1])-u[0,t])),
                        committed_pmin_mw=float(gens[0].P_min*u[0,t]),
                        incremental_exposure_mwh=float(p[0,t]-gens[0].P_min*u[0,t]),
                        true_cost_usd=float(cost[t]), reported_cost_usd=float(cost[t]+d*(p[0,t]-gens[0].P_min*u[0,t])),
                        self_output_mw=float(ss_p[t]), self_commitment=float(ss_u[t]),
                        self_exposure_mwh=float(ss_p[t]-gens[0].P_min*ss_u[t])))
    boundary = {r['plan']:r for r in summary if r['job']=='boundary'}
    baseline = {r['plan']:r for r in summary if r['job']=='baseline'}
    pair = paired_identity(jobs[1][1], boundary['A_left'], boundary['B_right'])
    zero = paired_identity(0., baseline['A_left'], baseline['B_right'])
    if max(abs(pair['residual_usd']), abs(zero['residual_usd'])) > 1e-6:
        raise ValueError('P2 / truthful invariance failed')
    # Check raw historical economics without relying on their rounded report values.
    historical_differences = []
    for old in historical['candidate_bids']:
        if old['delta'] != jobs[1][1]:
            continue
        match = next(r for r in boundary.values() if abs(r['exposure_mwh']-old['physical_exposure_mwh']) < 1e-8)
        gap = max(abs(match[new]-old[key]) for new,key in (
            ('true_profit_usd','true_profit'), ('energy_revenue_usd','energy_revenue'),
            ('true_cost_usd','true_cost'), ('loc_usd','reported_uplift'),
            ('best_reported_profit_usd','best_reported_profit')))
        historical_differences.append(gap)
    if len(historical_differences) != 2 or max(historical_differences) > 1e-6:
        raise ValueError('Original boundary settlements were not reproduced')
    csv_write(out/'profit_mechanism.csv', summary)
    csv_write(out/'boundary_dispatch_audit.csv', [r for r in hourly if r['job']=='boundary'])
    csv_write(out/'hourly_dispatch_audit.csv', hourly)
    csv_write(out/'full_system_dispatch.csv', physical)
    csv_write(out/'selected_nodal_prices.csv', prices)
    write(out/'identity_validation.json', dict(status='passed', P1_max_abs_residual_usd=max(abs(r['identity_residual_usd']) for r in summary),
        P2=pair, truthful_feasible_dispatch_invariance=zero,
        truthful_invariance_note='A/B are feasible at delta=0 but not claimed optimal at truthful cost. P1 and zero-adder invariance do not require system optimality.',
        max_historical_boundary_ledger_difference_usd=max(historical_differences),
        boundary_ledger=boundary, baseline_true_profit_usd=baseline['solver']['true_profit_usd']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('audit',), default='audit', help='Only E0-E1 is implemented in this gated delivery')
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-uc-solves', type=int, default=4)
    parser.add_argument('--max-chp-solves', type=int, default=4)
    parser.add_argument('--time-budget', type=float, default=300.)
    parser.add_argument('--seed', type=int, default=20261018)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.max_uc_solves, args.max_chp_solves) < 0 or not np.isfinite(args.time_budget) or args.time_budget <= 0:
        parser.error('Need nonnegative solve counts and a positive finite time budget')
    if args.worker or args.dry_run:
        run(args)
        return
    # Kill the entire in-process optimization on wall timeout; retain already-written checkpoints.
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir/'execution.log').open('a', encoding='utf-8') as log:
        try:
            result = subprocess.run([sys.executable, '-m', 'mechanism_study.run_study', *sys.argv[1:], '--worker'],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=args.time_budget,
                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        except subprocess.TimeoutExpired:
            path = args.out_dir/'manifest.json'
            report = read(path) if path.exists() else dict(stage='E0-E1')
            report.update(status='time_budget_exhausted', error='Worker killed at wall-clock deadline; incomplete results retained')
            write(path, report)
            raise SystemExit('E0-E1 wall-clock budget exhausted; see execution.log and manifest.json')
    if result.returncode:
        raise SystemExit(f'E0-E1 failed ({result.returncode}); see execution.log and manifest.json')
    print('E0-E1 completed; see manifest.json and identity_validation.json')


if __name__ == '__main__':
    main()
