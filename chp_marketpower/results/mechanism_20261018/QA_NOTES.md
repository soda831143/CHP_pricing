# Validation and scope gates

- Numerical E0/E1: passed. Four prespecified bids, four global system UC solves,
  four independent CHP solves and four G1 self-schedules; no new price maps or scans.
- P1: maximum ledger residual 1.4551915228366852e-11 USD across ten ledgers.
- P2: raw-precision predicted/observed difference 1387.3469913044246 USD; residual 0.
- Same total reported system cost corollary: residual 8.731149137020111e-11 USD.
- Original boundary economics reproduced within 2.9103830456733704e-11 USD.
- All selected COMPLETE dual witnesses passed the recorded feasibility,
  stationarity, sign, complementarity, duality-gap and price-projection gates.
- All four UC global bounds and self-schedule upper bounds are saved separately.
- Forty-four tests passed: `test_profit_identity.py`, `test_profit_range.py`,
  `test_model_consistency.py`, `test_affine_oracle.py`. See `test_results.log`.
- Mathematical P3/P4 tests are analytic toy checks, not new IEEE30 E2 results.
- Completed `--resume`: passed, zero additional solve attempts.
- Numerical source fingerprints and every saved numerical output hash were
  checked again after reporting; all unchanged.
- Pre-existing tracked modifications were compared with the exact original
  binary patch; unchanged. That preservation patch is not part of the commit.
- `git diff --check`: passed. One scientific figure was visually inspected.

Failures retained: the first implementation attempt completed one UC, then
failed while saving solver metadata because `status` was supplied twice to
`dict.update`. The fix changed only the new audit harness. Full failure manifest
and traceback are in `failed_attempt_01/`; this extra UC is included in the
report's cumulative solve count (5 UC, 4 CHP, 4 SS).

The initial pytest invocation had 17 passes and 10 fixture errors because its
default temporary path was unwritable. A new project-local `--basetemp` resolved
that environment issue; the final 44 tests passed. Python's existing pyreadline
shutdown warning appears after test success, with process exit code zero.

E0/E1 gates pass under the declared numerical tolerances. No tolerance is
converted into an unproved exact dispatch/profit error bound. E2–E4, alternative
legal-price sensitivity, MRG/removal-cost experiments, causal attribution,
coalitions and additional offer dimensions remain unexecuted.
