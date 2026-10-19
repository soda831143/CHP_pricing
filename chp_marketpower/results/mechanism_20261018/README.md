> Publication note (2026-10-19): this branch contains source and analysis documents. Referenced raw results, logs, figures and machine-specific manifests remain in the local archive; see [publication scope](PUBLICATION_SCOPE.md).

# E0–E1 mechanism audit, 2026-10-18

> 本地接续更新：E2/E3源码、原始证书与E4失败日志已恢复；E4六组重建结算与八个一致价格泛函端点通过，既定有限集合的E5初步筛选完成。当前报告、三张机制图与恢复记录见 [完整接续报告](followup/MECHANISM_REPORT.md) 和 [恢复状态](followup/RECOVERY_STATUS.md)。下文保留E0–E1历史说明。

Scope is deliberately limited to the original IEEE30 G1 all-day boundary and its
two prespecified perturbations. E2–E4 have not run.

- [Mechanism report](MECHANISM_REPORT.md): findings, exact ledgers, physical substitution, literature limits and next steps.
- [Mathematical propositions](../../notes/mechanism_propositions.md): hypotheses, P1–P4 proofs, counterexamples and validation status.
- [Paper outline](PAPER_OUTLINE.md) and [next-stage decision](NEXT_BRANCH_DECISION.md).
- `manifest.json`: original input/code hashes, base commit, model identity, solver parameters, numerical gates, attempted solve counts and completed checkpoints.
- `profit_mechanism.csv`: ten actual bid/execution ledgers; derivatives explicitly not assessed in E1.
- `boundary_dispatch_audit.csv`: hourly G1 A/B/independent-solver execution, costs and self-schedule at the same price.
- `full_system_dispatch.csv`, `selected_nodal_prices.csv`: all six units and full 30×24 prices at each bid.
- `boundary_system_costs.csv`, `boundary_cost_corollary.json`: G5 early online cost, other units' replacement and common-offer-cost corollary.
- `baseline/boundary/left/right.json` and `.npz`: global UC bounds, full selected dual residuals, actual self-schedule and dispatch arrays.
- `model_snapshot.json/.npz`: complete loaded cost/physical parameters, initial conditions, demand, PTDF and line limits.
- `paper_figures/figure1_boundary_mechanism.png/.svg`: one scientific figure in two formats.
- `execution.log`, `failed_attempt_01/`: retained success and implementation-failure records.
- `summarize_e1.py`: reproduce cost attribution and the figure without optimization.

The existing source maps, candidates and timing benchmarks are unchanged. This
directory is an E0–E1 delivery, not a completed MRG or physical counterfactual study.

From `chp_marketpower`, run the audit in a **new output directory**:

```powershell
python -m mechanism_study.run_study --stage audit --dry-run
python -m mechanism_study.run_study --stage audit --out-dir results/new_mechanism_audit --max-uc-solves 4 --max-chp-solves 4 --time-budget 300 --seed 20261018
```

Use `--resume` with the same directory/budget and unchanged code/data. Failed
attempts consume budget; exceeding it stops rather than silently extending the
experiment. The CLI implements only `audit`, so later stages cannot run by accident.

Tests from the same directory (use a new writable test directory):

```powershell
python -m pytest -q tests/test_profit_identity.py tests/test_profit_range.py tests/test_model_consistency.py -p no:cacheprovider --basetemp results/mechanism_test_new
```

The local pre-existing-user-change patch is a private preservation aid and is
excluded from the research commit. Output numerical fingerprints are not digital
signatures or symbolic optimality proofs.
