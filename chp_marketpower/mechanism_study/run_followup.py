"""Bounded serial E2-E4 execution on the original research branch."""
import argparse
import os
import subprocess
import sys

from mechanism_study.runtime import OUTPUT, ROOT, write, read, CAUSAL_STAGE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('local','pivotal','causal'),required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--time-budget',type=float,default=600.)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.time_budget<=0:parser.error('Positive time budget required')
    names=dict(local='E2_local',pivotal='E3_pivotal',causal=CAUSAL_STAGE)
    out=OUTPUT/names[args.stage]
    if args.worker or args.dry_run:
        if args.stage=='local':
            from mechanism_study.local_response import run
        elif args.stage=='pivotal':
            from mechanism_study.structural_pivotality import run
        else:
            from mechanism_study.constraint_attribution import run
        result=run(resume=args.resume,seconds=args.time_budget,dry_run=args.dry_run)
        if args.dry_run:
            import json
            print(json.dumps(result,indent=2))
        return
    out.mkdir(parents=True,exist_ok=True)
    with (out/'execution.log').open('a',encoding='utf-8') as log:
        try:
            process=subprocess.run([sys.executable,'-m','mechanism_study.run_followup',*sys.argv[1:],'--worker'],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=args.time_budget,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'))
        except subprocess.TimeoutExpired:
            manifest=read(out/'manifest.json') if (out/'manifest.json').exists() else {}
            manifest.update(status='time_budget_exhausted',error='Worker stopped at the prespecified wall-clock deadline')
            write(out/'manifest.json',manifest)
            raise SystemExit('Stage timed out; completed and incomplete attempts retained')
    if process.returncode:
        manifest=read(out/'manifest.json') if (out/'manifest.json').exists() else {}
        manifest.update(status='failed',worker_returncode=process.returncode,
            error='Worker failed; inspect execution.log for the original traceback')
        write(out/'manifest.json',manifest)
        raise SystemExit(f'Stage failed; inspect {out}/execution.log')
    print(f'Completed {args.stage}; see {out}/summary.json')


if __name__=='__main__':main()
