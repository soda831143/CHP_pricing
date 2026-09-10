"""Generate reproducible 30-bus robustness artefacts for the TPS manuscript.

The study is a bounded input-misspecification experiment, not a stochastic or
robust-optimization model.  It combines (i) joint errors across input families
and (ii) one-family-at-a-time errors.  Every D-CHP/DWP comparison is paired on
the same modified instance.  This script only summarizes CSV results; it never
changes a production model or invokes a solver.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


NOMINAL_OBJECTIVE = 179840.93804621452
NOMINAL_UPLIFT = 2736.8003549562923
DELTAS = [1e-3, 5e-3, 1e-2, 3e-2, 5e-2]
PRESENTATION_DELTA = 1e-2
FAMILY_ORDER = ["ramping", "cost", "demand", "line_limit"]
FAMILY_LABELS = {
    "ramping": "Ramping",
    "cost": "Costs",
    "demand": "Demand",
    "line_limit": "Line limits",
}
FAMILY_COLORS = {
    "ramping": "#0072B2",
    "cost": "#D55E00",
    "demand": "#009E73",
    "line_limit": "#CC79A7",
}
METHOD_COLORS = {"chp": "#0072B2", "dwp_incremental": "#D55E00"}
METHOD_LABELS = {"chp": "D-CHP", "dwp_incremental": "DWP"}


def _load(path: Path, expected_rows: int, experiment: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    if len(raw) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows} rows in {path}, found {len(raw)}")
    if not raw["status"].eq("optimal").all():
        failures = raw.loc[~raw["status"].eq("optimal"), ["status", "delta", "seed"]]
        raise RuntimeError(f"Non-optimal results in {path}:\n{failures.to_string(index=False)}")
    if not raw["experiment"].eq(experiment).all():
        raise RuntimeError(f"Unexpected experiment tag in {path}")
    data = raw.copy()
    for col in ("pricing_obj", "total_uplift", "end_to_end_time"):
        data[col] = pd.to_numeric(data[col])
    data["objective_change_pct"] = 100.0 * (data["pricing_obj"] - NOMINAL_OBJECTIVE) / NOMINAL_OBJECTIVE
    data["uplift_change_pct"] = 100.0 * (data["total_uplift"] - NOMINAL_UPLIFT) / NOMINAL_UPLIFT
    return data


def _range(values: pd.Series) -> tuple[float, float]:
    return float(values.min()), float(values.max())


def _iqr(values: pd.Series) -> tuple[float, float, float]:
    return float(values.median()), float(values.quantile(0.25)), float(values.quantile(0.75))


def _fmt_range(values: pd.Series, digits: int = 3) -> str:
    lo, hi = _range(values)
    return f"[{lo:.{digits}f},\\ {hi:.{digits}f}]"


def _fmt_iqr(values: pd.Series) -> str:
    med, q1, q3 = _iqr(values)
    return f"{med:.2f}\\ [{q1:.2f},\\ {q3:.2f}]"


def _joint_chp(joint: pd.DataFrame) -> pd.DataFrame:
    return joint[joint["method"].eq("chp")].copy()


def _family_chp(family: pd.DataFrame) -> pd.DataFrame:
    return family[family["method"].eq("chp")].copy()


def _latex_table(joint: pd.DataFrame, family: pd.DataFrame) -> str:
    """One compact, two-panel manuscript table instead of redundant tables."""
    j_chp = _joint_chp(joint)
    j_dwp = joint[joint["method"].eq("dwp_incremental")]
    f_chp = _family_chp(family)
    f_dwp = family[family["method"].eq("dwp_incremental")]
    rows: list[str] = []

    rows.append("\\multicolumn{7}{l}{\\textit{Panel A: Joint perturbation of all input families}}\\\\")
    for delta in DELTAS:
        x = j_chp[np.isclose(j_chp["delta"], delta)]
        y = j_dwp[np.isclose(j_dwp["delta"], delta)]
        rows.append(
            f"All families & {100*delta:g} & ${_fmt_range(x['objective_change_pct'])}$ & "
            f"${_fmt_range(x['uplift_change_pct'])}$ & -- & "
            f"${_fmt_iqr(x['end_to_end_time'])}$ & ${_fmt_iqr(y['end_to_end_time'])}$ \\\\"
        )

    rows.append("\\addlinespace")
    rows.append("\\multicolumn{7}{l}{\\textit{Panel B: One-family-at-a-time perturbation at $\\delta=1\\%$}}\\\\")
    for name in FAMILY_ORDER:
        x = f_chp[(f_chp["parameter_family"].eq(name)) & np.isclose(f_chp["delta"], PRESENTATION_DELTA)]
        y = f_dwp[(f_dwp["parameter_family"].eq(name)) & np.isclose(f_dwp["delta"], PRESENTATION_DELTA)]
        schedule = 100.0 * pd.to_numeric(x["schedule_change_ratio"])
        rows.append(
            f"{FAMILY_LABELS[name]} & 1 & ${_fmt_range(x['objective_change_pct'])}$ & "
            f"${_fmt_range(x['uplift_change_pct'])}$ & ${_fmt_range(schedule, 2)}$ & "
            f"${_fmt_iqr(x['end_to_end_time'])}$ & ${_fmt_iqr(y['end_to_end_time'])}$ \\\\"
        )
    body = "\n".join(rows)
    return """\\begin{table*}[t]
\\centering
\\caption{Robustness under bounded input misspecification on the modified IEEE 30-bus BASE case. Each row summarizes ten fixed, paired perturbation realizations. Relative changes are measured from the nominal value; time is end-to-end seconds, reported as median [IQR]. In Panel B, schedule change is the fraction of 144 pricing-day unit-hour commitment decisions that differs from the nominal schedule. D-CHP and DWP reached optimal status and coincide to the displayed precision for every realization.}
\\label{tab:robustness-sensitivity}
\\scriptsize
\\resizebox{\\textwidth}{!}{%
\\begin{tabular}{lrrrrrr}
\\toprule
Input perturbation & $\\delta$ (\\%) & $\\Delta C^{\\mathrm{LP}}/C^{\\mathrm{LP},0}$ (\\%) & $\\Delta U^{\\mathrm{tot}}/U^{\\mathrm{tot},0}$ (\\%) & Schedule change (\\%) & D-CHP time (s) & DWP time (s) \\\\
\\midrule
""" + body + """
\\bottomrule
\\end{tabular}%
}
\\end{table*}
"""


def _max_abs_by_delta(data: pd.DataFrame, family: str, metric: str) -> list[float]:
    values = []
    for delta in DELTAS:
        x = data[(data["parameter_family"].eq(family)) & np.isclose(data["delta"], delta)][metric]
        values.append(float(np.abs(x).max()))
    return values


def _plot_sensitivity_magnitude(ax, family: pd.DataFrame, metric: str, title: str) -> None:
    chp = _family_chp(family)
    x = np.asarray(DELTAS) * 100.0
    for name in FAMILY_ORDER:
        y = _max_abs_by_delta(chp, name, metric)
        ax.plot(x, y, marker="o", ms=3.8, lw=1.6, color=FAMILY_COLORS[name], label=FAMILY_LABELS[name])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(x, [f"{v:g}" for v in x])
    ax.set_xlabel(r"Perturbation bound $\delta$ (\%)")
    ax.set_ylabel(r"Maximum $|\Delta|$ (\%)")
    ax.set_title(title, fontsize=9)
    ax.grid(True, which="both", color="0.88", lw=0.6)


def _plot_joint_timing(ax, joint: pd.DataFrame) -> None:
    x = np.asarray(DELTAS) * 100.0
    for method in ("chp", "dwp_incremental"):
        sub = joint[joint["method"].eq(method)]
        medians, lows, highs = [], [], []
        for delta in DELTAS:
            values = sub[np.isclose(sub["delta"], delta)]["end_to_end_time"]
            med, q1, q3 = _iqr(values)
            medians.append(med)
            lows.append(med - q1)
            highs.append(q3 - med)
        ax.errorbar(
            x, medians, yerr=[lows, highs], marker="o", ms=4.0, lw=1.6,
            capsize=2.5, color=METHOD_COLORS[method], label=METHOD_LABELS[method],
        )
    ax.set_xscale("log")
    ax.set_xticks(x, [f"{v:g}" for v in x])
    ax.set_xlabel(r"Joint perturbation bound $\delta$ (\%)")
    ax.set_ylabel("End-to-end time (s)")
    ax.set_title("(c) Joint-perturbation timing", fontsize=9)
    ax.grid(True, which="both", color="0.88", lw=0.6)
    ax.legend(frameon=False, fontsize=8, loc="upper left")


def _make_figure(joint: pd.DataFrame, family: pd.DataFrame, outbase: Path) -> None:
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 2.42), constrained_layout=True)
    _plot_sensitivity_magnitude(axes[0], family, "objective_change_pct", "(a) Pricing-objective sensitivity")
    _plot_sensitivity_magnitude(axes[1], family, "uplift_change_pct", "(b) Total-uplift sensitivity")
    _plot_joint_timing(axes[2], joint)
    axes[1].legend(frameon=False, fontsize=7.2, loc="upper left")
    fig.savefig(outbase.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(outbase.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def _exact_gap(data: pd.DataFrame, keys: list[str]) -> tuple[float, float]:
    wide = data.pivot_table(index=keys, columns="method", values=["pricing_obj", "total_uplift"], aggfunc="first")
    obj = float((wide["pricing_obj"]["chp"] - wide["pricing_obj"]["dwp_incremental"]).abs().max())
    uplift = float((wide["total_uplift"]["chp"] - wide["total_uplift"]["dwp_incremental"]).abs().max())
    return obj, uplift


def _write_record(joint: pd.DataFrame, family: pd.DataFrame, path: Path) -> None:
    j_obj, j_uplift = _exact_gap(joint, ["delta", "seed"])
    f_obj, f_uplift = _exact_gap(family, ["parameter_family", "delta", "seed"])
    family_chp = _family_chp(family)
    schedule = 100.0 * pd.to_numeric(family_chp["schedule_change_ratio"])
    record = f"""# 30-Bus Bounded Input-Misspecification Experiment Record

## Purpose and scope

- This is a local, bounded input-misspecification study motivated by forecast, calibration, and availability errors. It is not an estimated probability model, Monte Carlo uncertainty quantification, or robust-optimization model.
- Case: modified IEEE 30-bus PTDF BASE case, $T=24$, three-segment PWL costs.
- Each modified instance regenerates the 48-hour rolling UC history before the pricing-day UC and pricing calculations.
- End-to-end pricing time includes construction, pricing optimization, and common exact unit self-scheduling/settlement evaluation; the warm-up UC is excluded.
- D-CHP and DWP are paired on every modified instance: they receive the same perturbed input, rolling initial condition, physical pricing-day schedule, and settlement protocol.

## Joint perturbations

- Bounds: $\\delta\\in\\{{0.1\\%,0.5\\%,1\\%,3\\%,5\\%\\}}$.
- Ten fixed seeds per bound; 50 modified instances and {len(joint)} method-level records.
- All records reached `optimal` status.
- Maximum D-CHP/DWP absolute difference: {j_obj:.12g} in pricing objective and {j_uplift:.12g} in total uplift.

## One-family-at-a-time perturbations

- Families: ramping limits, cost coefficients, hourly demand profile, and line limits.
- Same five bounds and ten fixed seeds per family and bound; 200 modified instances and {len(family)} method-level records.
- All records reached `optimal` status.
- Maximum D-CHP/DWP absolute difference: {f_obj:.12g} in pricing objective and {f_uplift:.12g} in total uplift.
- Largest observed pricing-day schedule-change ratio: {schedule.max():.2f}\\%.

## Interpretation rule

- A commitment switch is reported as an economic/physical UC response to altered data, not as a numerical error.
- Exactness is assessed by solver status and paired D-CHP/DWP agreement to displayed precision.
- No probability, confidence-level, or universal-invariance claim is made from the ten deterministic realizations.
"""
    path.write_text(record, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--joint", type=Path, default=Path("results/tps_revision_validation/joint_robustness_5levels_10seeds.csv"))
    parser.add_argument("--family", type=Path, default=Path("results/tps_revision_validation/family_robustness_5levels_10seeds.csv"))
    parser.add_argument("--outdir", type=Path, default=Path("results/paper_main"))
    args = parser.parse_args()

    joint = _load(args.joint, expected_rows=100, experiment="coefficient_perturbation")
    family = _load(args.family, expected_rows=400, experiment="family_sensitivity")
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "table_robustness_sensitivity.tex").write_text(_latex_table(joint, family), encoding="utf-8")
    _make_figure(joint, family, args.outdir / "robustness_sensitivity_30bus")

    audit = pd.concat([joint.assign(study="joint"), family.assign(study="one_family")], ignore_index=True)
    audit.to_csv(args.outdir / "robustness_5levels_10seeds_audit.csv", index=False, encoding="utf-8-sig")
    _write_record(joint, family, args.family.parent / "robustness_5levels_10seeds_record.md")
    print(f"Wrote robustness table, figure, audit CSV, and experiment record to {args.outdir}")


if __name__ == "__main__":
    main()
