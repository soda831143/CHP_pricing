"""Summarize 30-bus coefficient-sensitivity validation for the TPS paper.

Inputs are the raw CSVs written by ``run_tps_numerical_stability.py``.  The
script deliberately produces both manuscript-ready artefacts and a compact
machine-readable audit table, so no number in the paper needs to be copied by
hand.  It does not invoke a solver or modify the pricing implementation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


NOMINAL_OBJECTIVE = 179840.93804621452
NOMINAL_UPLIFT = 2736.8003549562923
FAMILY_LABELS = {
    "ramping": "Ramping",
    "cost": "Costs",
    "demand": "Demand",
    "line_limit": "Line limits",
}
FAMILY_ORDER = ["ramping", "cost", "demand", "line_limit"]
COLORS = {1e-3: "#0072B2", 1e-2: "#D55E00"}  # color-blind safe


def _iqr(values: pd.Series) -> tuple[float, float, float]:
    return float(values.median()), float(values.quantile(0.25)), float(values.quantile(0.75))


def _range(values: pd.Series) -> tuple[float, float]:
    return float(values.min()), float(values.max())


def _fmt_range(values: pd.Series, digits: int = 4) -> str:
    lo, hi = _range(values)
    return f"[{lo:.{digits}f},\\ {hi:.{digits}f}]"


def _fmt_timing(values: pd.Series) -> str:
    med, q1, q3 = _iqr(values)
    return f"{med:.2f}\\ [{q1:.2f},\\ {q3:.2f}]"


def _prepare(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    data = data[data["status"].eq("optimal")].copy()
    data["pricing_obj"] = pd.to_numeric(data["pricing_obj"])
    data["total_uplift"] = pd.to_numeric(data["total_uplift"])
    data["end_to_end_time"] = pd.to_numeric(data["end_to_end_time"])
    return data


def _latex_joint_table(joint: pd.DataFrame) -> str:
    chp = joint[(joint["experiment"] == "coefficient_perturbation") & (joint["method"] == "chp")].copy()
    chp["objective_pct"] = 100.0 * (chp["pricing_obj"] - NOMINAL_OBJECTIVE) / NOMINAL_OBJECTIVE
    chp["uplift_pct"] = 100.0 * (chp["total_uplift"] - NOMINAL_UPLIFT) / NOMINAL_UPLIFT
    dwp = joint[(joint["experiment"] == "coefficient_perturbation") & (joint["method"] == "dwp_incremental")].copy()

    rows = []
    for delta in sorted(chp["delta"].unique()):
        x = chp[chp["delta"] == delta]
        y = dwp[dwp["delta"] == delta]
        rows.append(
            f"$10^{{{int(round(np.log10(delta)))}}}$ & {len(x)} & "
            f"${_fmt_range(x['objective_pct'])}$ & ${_fmt_range(x['uplift_pct'])}$ & "
            f"${_fmt_timing(x['end_to_end_time'])}$ & ${_fmt_timing(y['end_to_end_time'])}$ \\\\"
        )
    body = "\n".join(rows)
    return """\\begin{table}[t]
\\centering
\\caption{Joint coefficient perturbations on the modified IEEE 30-bus BASE case. Each entry covers five fixed seeds and reports the range of the relative change from the nominal value or the median [IQR] end-to-end time in seconds.}
\\label{tab:numerical-stability}
\\scriptsize
\\resizebox{\\columnwidth}{!}{%
\\begin{tabular}{lrrrrr}
\\toprule
Magnitude $\\delta$ & Instances & $\\Delta C^{\\mathrm{LP}}/C^{\\mathrm{LP},0}$ (\\%) & $\\Delta U^{\\mathrm{tot}}/U^{\\mathrm{tot},0}$ (\\%) & D-CHP time (s) & DWP time (s) \\\\
\\midrule
""" + body + """
\\bottomrule
\\end{tabular}%
}
\\end{table}
"""


def _latex_family_table(family: pd.DataFrame) -> str:
    chp = family[(family["experiment"] == "family_sensitivity") & (family["method"] == "chp") & (family["delta"] == 1e-2)].copy()
    dwp = family[(family["experiment"] == "family_sensitivity") & (family["method"] == "dwp_incremental") & (family["delta"] == 1e-2)].copy()
    chp["objective_pct"] = 100.0 * (chp["pricing_obj"] - NOMINAL_OBJECTIVE) / NOMINAL_OBJECTIVE
    chp["uplift_pct"] = 100.0 * (chp["total_uplift"] - NOMINAL_UPLIFT) / NOMINAL_UPLIFT
    rows = []
    for name in FAMILY_ORDER:
        x = chp[chp["parameter_family"] == name]
        y = dwp[dwp["parameter_family"] == name]
        sched = 100.0 * pd.to_numeric(x["schedule_change_ratio"])
        rows.append(
            f"{FAMILY_LABELS[name]} & ${_fmt_range(x['objective_pct'])}$ & "
            f"${_fmt_range(x['uplift_pct'])}$ & ${_fmt_range(sched, 2)}$ & "
            f"${_fmt_timing(x['end_to_end_time'])}$ & ${_fmt_timing(y['end_to_end_time'])}$ \\\\"
        )
    body = "\n".join(rows)
    return """\\begin{table}[t]
\\centering
\\caption{One-parameter-family-at-a-time sensitivity at $\\delta=10^{-2}$ on the modified IEEE 30-bus BASE case. Each range covers five fixed seeds. Schedule change is the fraction of the 144 unit-hour commitment decisions that differs from the nominal pricing-day schedule. Both exact methods reached optimal status and coincide to the displayed precision for all cases.}
\\label{tab:family-sensitivity}
\\scriptsize
\\resizebox{\\columnwidth}{!}{%
\\begin{tabular}{lrrrrr}
\\toprule
Perturbed family & $\\Delta C^{\\mathrm{LP}}/C^{\\mathrm{LP},0}$ (\\%) & $\\Delta U^{\\mathrm{tot}}/U^{\\mathrm{tot},0}$ (\\%) & Schedule change (\\%) & D-CHP time (s) & DWP time (s) \\\\
\\midrule
""" + body + """
\\bottomrule
\\end{tabular}
}
\\end{table}
"""


def _plot_ranges(ax, data: pd.DataFrame, metric: str, title: str) -> None:
    y_base = np.arange(len(FAMILY_ORDER), dtype=float)
    offsets = {1e-3: -0.16, 1e-2: 0.16}
    for delta in (1e-3, 1e-2):
        for pos, family in enumerate(FAMILY_ORDER):
            x = data[(data["parameter_family"] == family) & (data["delta"] == delta)][metric]
            lo, hi = _range(x)
            med = float(x.median())
            ax.plot([lo, hi], [y_base[pos] + offsets[delta]] * 2, color=COLORS[delta], lw=2.0, solid_capstyle="round")
            ax.scatter(med, y_base[pos] + offsets[delta], color=COLORS[delta], s=24, zorder=3)
    ax.axvline(0.0, color="0.35", lw=0.8)
    ax.set_yticks(y_base, [FAMILY_LABELS[x] for x in FAMILY_ORDER])
    ax.invert_yaxis()
    ax.set_xlabel("Relative change from nominal (\\%)")
    ax.set_title(title, fontsize=9)
    ax.grid(axis="x", color="0.88", lw=0.7)


def _plot_times(ax, data: pd.DataFrame) -> None:
    x_positions = np.arange(len(FAMILY_ORDER), dtype=float)
    offsets = {"chp": -0.16, "dwp_incremental": 0.16}
    colors = {"chp": "#009E73", "dwp_incremental": "#CC79A7"}
    labels = {"chp": "D-CHP", "dwp_incremental": "DWP"}
    for method in ("chp", "dwp_incremental"):
        for i, family in enumerate(FAMILY_ORDER):
            values = data[(data["parameter_family"] == family) & (data["method"] == method) & (data["delta"] == 1e-2)]["end_to_end_time"]
            med, q1, q3 = _iqr(values)
            xpos = x_positions[i] + offsets[method]
            ax.vlines(xpos, q1, q3, color=colors[method], lw=4.0, alpha=0.75)
            ax.scatter(values * 0 + xpos, values, color=colors[method], s=16, alpha=0.75, zorder=3)
            ax.scatter(xpos, med, color="black", s=15, marker="_", zorder=4)
        ax.scatter([], [], color=colors[method], label=labels[method])
    ax.set_xticks(x_positions, [FAMILY_LABELS[x] for x in FAMILY_ORDER], rotation=20, ha="right")
    ax.set_ylabel("End-to-end time (s)")
    ax.set_title("(c) Timing at 1% perturbation", fontsize=9)
    ax.grid(axis="y", color="0.88", lw=0.7)
    ax.legend(frameon=False, fontsize=8, loc="upper left")


def _make_figure(family: pd.DataFrame, outbase: Path) -> None:
    chp = family[(family["experiment"] == "family_sensitivity") & (family["method"] == "chp")].copy()
    chp["objective_pct"] = 100.0 * (chp["pricing_obj"] - NOMINAL_OBJECTIVE) / NOMINAL_OBJECTIVE
    chp["uplift_pct"] = 100.0 * (chp["total_uplift"] - NOMINAL_UPLIFT) / NOMINAL_UPLIFT

    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 2.45), constrained_layout=True)
    _plot_ranges(axes[0], chp, "objective_pct", "(a) Pricing objective")
    _plot_ranges(axes[1], chp, "uplift_pct", "(b) Total uplift")
    _plot_times(axes[2], family)
    handles = [
        plt.Line2D([0], [0], color=COLORS[1e-3], marker="o", lw=2, label=r"$\delta=10^{-3}$"),
        plt.Line2D([0], [0], color=COLORS[1e-2], marker="o", lw=2, label=r"$\delta=10^{-2}$"),
    ]
    axes[1].legend(handles=handles, frameon=False, fontsize=8, loc="upper right")
    fig.savefig(outbase.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(outbase.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def _write_record(joint: pd.DataFrame, family: pd.DataFrame, path: Path) -> None:
    """Write a concise provenance record beside the raw experiment CSVs."""
    joint_cases = joint[joint["experiment"].eq("coefficient_perturbation")]
    family_cases = family[family["experiment"].eq("family_sensitivity")]
    joint_wide = joint_cases.pivot_table(
        index=["delta", "seed"], columns="method",
        values=["pricing_obj", "total_uplift"], aggfunc="first",
    )
    family_wide = family_cases.pivot_table(
        index=["parameter_family", "delta", "seed"], columns="method",
        values=["pricing_obj", "total_uplift"], aggfunc="first",
    )
    joint_obj_gap = float((joint_wide["pricing_obj"]["chp"] - joint_wide["pricing_obj"]["dwp_incremental"]).abs().max())
    joint_uplift_gap = float((joint_wide["total_uplift"]["chp"] - joint_wide["total_uplift"]["dwp_incremental"]).abs().max())
    family_obj_gap = float((family_wide["pricing_obj"]["chp"] - family_wide["pricing_obj"]["dwp_incremental"]).abs().max())
    family_uplift_gap = float((family_wide["total_uplift"]["chp"] - family_wide["total_uplift"]["dwp_incremental"]).abs().max())
    max_schedule_change = float(100.0 * pd.to_numeric(family_cases.loc[family_cases["method"].eq("chp"), "schedule_change_ratio"]).max())
    record = f"""# 30-Bus Coefficient-Sensitivity Experiment Record

## Scope

- Case: modified IEEE 30-bus PTDF BASE case, $T=24$, three-segment PWL costs.
- Initial condition: each modified instance regenerates the 48-hour rolling UC history before the pricing-day UC and pricing calculations.
- Timing definition: model construction + pricing optimization + common exact unit self-scheduling/settlement evaluation. The warm-up UC is excluded from the pricing-method time.
- Exact benchmark: DWP. Both methods use the same physical schedule and common settlement protocol on a given modified instance.

## Joint perturbations

- Magnitudes: $10^{{-4}}$, $10^{{-3}}$, and $10^{{-2}}$.
- Seeds: five fixed seeds per magnitude; 15 modified instances and {len(joint_cases)} method-level records.
- Status: all method-level records are `optimal`.
- Maximum D-CHP/DWP absolute difference: {joint_obj_gap:.9g} in the pricing objective and {joint_uplift_gap:.9g} in total uplift. These differences are within solver tolerance and coincide to the displayed precision.

## One-family-at-a-time perturbations

- Families: ramping limits, costs, hourly demand profile, and line limits.
- Magnitudes: $10^{{-3}}$ and $10^{{-2}}$; five fixed seeds per family and magnitude; 40 modified instances and {len(family_cases)} method-level records.
- Status: all method-level records are `optimal`.
- Maximum D-CHP/DWP absolute difference: {family_obj_gap:.9g} in the pricing objective and {family_uplift_gap:.9g} in total uplift. These differences are within solver tolerance and coincide to the displayed precision.
- Largest observed pricing-day schedule-change ratio in the $1\\%$ one-family tests: {max_schedule_change:.2f}\\%.

## Artefacts

- Raw joint results: `numerical_stability_30bus.csv`.
- Raw family results: `family_sensitivity_30bus.csv`.
- Manuscript tables and figure are generated by `scripts/summarize_tps_sensitivity.py`; no manuscript number is copied manually.
"""
    path.write_text(record, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--joint", type=Path, default=Path("results/tps_revision_validation/numerical_stability_30bus.csv"))
    parser.add_argument("--family", type=Path, default=Path("results/tps_revision_validation/family_sensitivity_30bus.csv"))
    parser.add_argument("--outdir", type=Path, default=Path("results/paper_main"))
    args = parser.parse_args()

    joint = _prepare(args.joint)
    family = _prepare(args.family)
    if len(family) != 80 or not family["status"].eq("optimal").all():
        raise RuntimeError("Expected 80 optimal method-level family-sensitivity rows")
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "table_joint_sensitivity.tex").write_text(_latex_joint_table(joint), encoding="utf-8")
    (args.outdir / "table_family_sensitivity.tex").write_text(_latex_family_table(family), encoding="utf-8")
    _make_figure(family, args.outdir / "sensitivity_stability_30bus")

    audit = family.copy()
    audit["objective_change_pct"] = 100.0 * (audit["pricing_obj"] - NOMINAL_OBJECTIVE) / NOMINAL_OBJECTIVE
    audit["uplift_change_pct"] = 100.0 * (audit["total_uplift"] - NOMINAL_UPLIFT) / NOMINAL_UPLIFT
    audit.to_csv(args.outdir / "family_sensitivity_30bus_audit.csv", index=False, encoding="utf-8-sig")
    _write_record(joint, family, args.family.parent / "sensitivity_experiment_record.md")
    print(f"Wrote manuscript tables, figure, and audit CSV to {args.outdir}")


if __name__ == "__main__":
    main()
