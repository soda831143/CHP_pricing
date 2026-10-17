"""Budgeted price-map queue, preview by default. No UC/profit batch is implied."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from dashboard.data import load_catalog, get_scenario

ROOT = Path(__file__).resolve().parents[1]


def discovery_budget(total_points):
    if total_points < 3:
        raise ValueError('At least two discovery endpoints and one validation midpoint are required')
    return (total_points+1)//2


def tasks(data, case, generators, hours):
    count = len(data['models'][case]['generators'])
    if any(not 1 <= g <= count for g in generators) or any(h != 'all' and (not h.isdigit() or not 1 <= int(h) <= 24) for h in hours):
        raise ValueError('Use existing 1-based generators and all or hours 1..24')
    rows = []
    for g in sorted(set(generators)):
        for h in dict.fromkeys(hours):
            hour = None if h == 'all' else int(h)
            present = any(s['case']==case and s['generator_index']==g-1 and s['bid_hour_1based']==hour for s in data['scenarios'])
            rows.append(dict(case=case, generator=g, hour=hour,
                id=f'{case}-G{g}-'+('all' if hour is None else f'h{hour}'),
                status='skip_exported_map' if present else 'pending'))
    return rows


def check_task_scope(audit,task,reference):
    scope = audit['scope']
    expected = dict(case=task['case'],generator_index=task['generator']-1,
        bid_hour_1based=task['hour'],network='ptdf',T=24,segments=3,congestion='tight')
    if any(scope.get(k)!=v for k,v in expected.items()):
        raise ValueError('Checkpoint belongs to a different generator/hour/model configuration')
    if audit['intervals'][0]['left']!=0. or audit['intervals'][-1]['right']!=.5*reference:
        raise ValueError('Checkpoint has a different bid domain')


def run_step(command, directory, deadline, byte_limit, log):
    if time.monotonic() >= deadline or sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) >= byte_limit:
        raise RuntimeError('No remaining wall-time/disk budget; no new step started')
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        while process.poll() is None:
            size = sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
            if time.monotonic() >= deadline or size >= byte_limit:
                process.kill()
                process.wait()
                raise RuntimeError('Wall-time/disk budget stopped this task; checkpoint/log retained, not a complete map')
            time.sleep(1)
        if process.returncode:
            raise RuntimeError(f'Step exited {process.returncode}; inspect task.log and resume only a valid checkpoint')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['30','118'],default='30')
    parser.add_argument('--generators',type=int,nargs='+',default=[1,2,3,4,5,6],help='1-based indices')
    parser.add_argument('--hours',nargs='+',default=['all'])
    parser.add_argument('--execute',action='store_true',help='Without this flag, only print the queue')
    parser.add_argument('--uc-only',action='store_true',help='Extend verified all-day price maps with UC regions; no profit sweep')
    parser.add_argument('--max-uc-solves',type=int,default=400)
    parser.add_argument('--max-tasks',type=int,default=1)
    parser.add_argument('--max-points',type=int,default=400,help='Per-map total CHP point budget, including resumed points')
    parser.add_argument('--seconds',type=float,default=600.)
    parser.add_argument('--max-mb',type=float,default=1024.)
    args = parser.parse_args()
    if args.max_tasks < 1 or args.max_points < 3 or args.seconds <= 0 or args.max_mb <= 0:
        parser.error('Task/point/time/disk budgets must be positive')
    data,_ = load_catalog()
    queue = tasks(data,args.case,args.generators,args.hours)
    if args.uc_only:
        if args.hours!=['all'] or args.max_uc_solves<2:
            parser.error('UC region extension requires --hours all and at least two UC solves')
        for task in queue:
            s = get_scenario(data,task['case'],task['generator']-1)
            task['status'] = 'pending' if s and not s['physical_regions'] else 'skip_existing_uc' if s else 'skip_missing_price_map'
    if not args.execute:
        print(json.dumps(queue,indent=2)); return
    from engine import load_case
    from price_vulnerability.model_identity import model_identity
    gens,net = load_case(args.case,'ptdf',24,3,'tight')
    if model_identity(gens,net)['model_sha256'] != data['models'][args.case]['model_sha256']:
        raise ValueError('Current model differs from the catalog; re-export/revalidate before extending it')
    folder = ROOT/('results/dashboard_uc_regions' if args.uc_only else 'results/dashboard_precompute')
    folder.mkdir(parents=True,exist_ok=True)
    deadline = time.monotonic()+args.seconds
    attempted = 0
    for task in queue:
        if task['status'] != 'pending' or attempted >= args.max_tasks: continue
        directory = folder/task['id']
        if args.uc_only:
            attempted += 1
            started = time.monotonic()
            try:
                s = get_scenario(data,task['case'],task['generator']-1)
                if not (directory/'physical_regions.json').exists():
                    log_path = folder/f'{task["id"]}.log'
                    with log_path.open('a',encoding='utf-8') as log:
                        run_step([sys.executable,'run_profit_range.py','--oracle-dir',str(ROOT/s['source_oracle']),
                            '--out-dir',str(directory),'--physical-only','--max-uc-solves',str(args.max_uc_solves)],
                            folder,deadline,args.max_mb*1024**2,log)
                from dashboard.catalog import register_physical
                task['publication'] = register_physical(s,directory)
                task['status'] = 'published_uc_regions'
            except (RuntimeError,OSError,ValueError,KeyError) as error:
                task.update(status='incomplete',diagnostic=str(error))
            task['batch_task_seconds'] = time.monotonic()-started
            (folder/'queue.json').write_text(json.dumps(queue,indent=2),encoding='utf-8')
            print(json.dumps(task),flush=True)
            if task['status']=='incomplete': break
            continue
        directory.mkdir(exist_ok=True)
        gen = gens[task['generator']-1]
        reference = gen.pwl_slopes[len(gen.pwl_slopes)//2] if gen.pwl_slopes else gen.cost_var
        command = [sys.executable,'run_affine_oracle.py','--discover','--complete','--case',args.case,
            '--generator',str(task['generator']-1),'--upper',str(.5*reference),'--max-points',str(discovery_budget(args.max_points)),
            '--out-dir',str(directory),'--checkpoint-every','1']
        if args.case == '118': command += ['--aggregate-output']
        if task['hour'] is not None: command += ['--bid-hour',str(task['hour'])]
        if (directory/'audit.json').exists(): command += ['--resume']
        attempted += 1
        started = time.monotonic()
        try:
            with (directory/'task.log').open('a',encoding='utf-8') as log:
                postprocess = [sys.executable,'postprocess_oracle.py','--oracle-dir',str(directory)]
                steps = [command,postprocess]
                validation_needed = True
                audit_path = directory/'audit.json'
                if audit_path.exists():
                    from price_vulnerability.model_identity import check_model_identity
                    audit = json.loads(audit_path.read_text(encoding='utf-8'))
                    check_task_scope(audit,task,reference)
                    if not check_model_identity(directory,gens,net,audit):
                        raise ValueError('Checkpoint lacks its fixed model identity')
                    if audit['status']=='numerically_validated':
                        steps = [postprocess]
                        try:
                            from price_vulnerability.oracle_compression import load_matched_compact
                            load_matched_compact(directory)
                            steps = []
                            try:
                                from dashboard.catalog import check_validation
                                check_validation(directory,audit,model_identity(gens,net)['model_sha256'])
                                validation_needed = False
                            except (ValueError,OSError,KeyError):
                                pass
                        except (ValueError,OSError,KeyError):
                            pass  # Complete raw checkpoint can regenerate a stale/missing compact file.
                if validation_needed:
                    steps.append([sys.executable,'validate_affine_oracle.py','--oracle-dir',str(directory),'--persistent-direct','--fractions','0.5'])
                for step in steps:
                    run_step(step,folder,deadline,args.max_mb*1024**2,log)
            from dashboard.catalog import register
            task['publication'] = register(directory)
            task['status'] = 'validated_price_map'
            task['directory'] = str(directory.relative_to(ROOT))
        except (RuntimeError,OSError,ValueError,KeyError) as error:
            task.update(status='incomplete',diagnostic=str(error))
        task['batch_task_seconds'] = time.monotonic()-started
        (folder/'queue.json').write_text(json.dumps(queue,indent=2),encoding='utf-8')
        print(json.dumps(task),flush=True)
        if task['status']=='incomplete': break


if __name__ == '__main__':
    main()
