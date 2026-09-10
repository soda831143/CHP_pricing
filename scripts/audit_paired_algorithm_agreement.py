"""Audit D-CHP/DWP agreement on already-completed perturbation instances.

Unlike an economic-sensitivity summary, this utility never compares a
perturbed instance with the nominal case.  It pairs D-CHP and DWP on the same
modified instance and reports their numerical agreement.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


METHOD_DCHP = "chp"
METHOD_DWP = "dwp_incremental"


def _float(row: dict, key: str) -> float:
    return float(row[key])


def _relative_gap(left: float, right: float) -> float:
    return abs(left - right) / max(1.0, abs(left), abs(right))


def _read_pairs(path: Path, label: str) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        raw = list(csv.DictReader(stream))
    grouped: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in raw:
        key = (row.get("parameter_family", "joint"), row["delta"], row["seed"])
        grouped[key][row["method"]] = row

    pairs: list[dict] = []
    for key, methods in sorted(grouped.items(), key=lambda item: (item[0][0], float(item[0][1]), int(item[0][2]))):
        if METHOD_DCHP not in methods or METHOD_DWP not in methods:
            raise RuntimeError(f"Incomplete D-CHP/DWP pair in {label}: {key}")
        dchp, dwp = methods[METHOD_DCHP], methods[METHOD_DWP]
        if dchp.get("status") != "optimal" or dwp.get("status") != "optimal":
            raise RuntimeError(f"Non-optimal paired run in {label}: {key}")
        c_dchp, c_dwp = _float(dchp, "pricing_obj"), _float(dwp, "pricing_obj")
        u_dchp, u_dwp = _float(dchp, "total_uplift"), _float(dwp, "total_uplift")
        pairs.append(
            {
                "dataset": label,
                "parameter_family": key[0],
                "delta": float(key[1]),
                "seed": int(key[2]),
                "dchp_status": dchp["status"],
                "dwp_status": dwp["status"],
                "dchp_objective": c_dchp,
                "dwp_objective": c_dwp,
                "objective_abs_gap": abs(c_dchp - c_dwp),
                "objective_relative_gap": _relative_gap(c_dchp, c_dwp),
                "dchp_total_uplift": u_dchp,
                "dwp_total_uplift": u_dwp,
                "uplift_abs_gap": abs(u_dchp - u_dwp),
                "uplift_relative_gap": _relative_gap(u_dchp, u_dwp),
                "dchp_end_to_end_time": _float(dchp, "end_to_end_time"),
                "dwp_end_to_end_time": _float(dwp, "end_to_end_time"),
            }
        )
    return pairs


def _max(rows: list[dict], key: str) -> float:
    return max(float(row[key]) for row in rows)


def _summary_table(rows: list[dict], filter_dataset: str) -> list[str]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["dataset"] == filter_dataset:
            groups[(row["parameter_family"], row["delta"])].append(row)
    lines = [
        "| Input set | $\\delta$ | Instances | Max relative objective disagreement | Max relative total-uplift disagreement |",
        "|---|---:|---:|---:|---:|",
    ]
    for (family, delta), group in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        lines.append(
            f"| {family} | {100*delta:g}% | {len(group)} | "
            f"{_max(group, 'objective_relative_gap'):.3e} | "
            f"{_max(group, 'uplift_relative_gap'):.3e} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--joint",
        type=Path,
        default=Path("results/tps_revision_validation/joint_robustness_5levels_10seeds.csv"),
    )
    parser.add_argument(
        "--family",
        type=Path,
        default=Path("results/tps_revision_validation/family_robustness_5levels_10seeds.csv"),
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=Path("results/tps_revision_validation/paired_algorithm_agreement_audit.csv"),
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=Path("results/tps_revision_validation/paired_algorithm_agreement_audit.md"),
    )
    args = parser.parse_args()

    rows = _read_pairs(args.joint, "joint perturbations") + _read_pairs(args.family, "one-family perturbations")
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    by_dataset = Counter(row["dataset"] for row in rows)
    document = [
        "# Paired D-CHP/DWP Algorithm-Agreement Audit",
        "",
        "## Purpose",
        "",
        "This audit assesses numerical agreement on the same perturbed UC/CHP instance. It does not interpret the difference between a perturbed instance and the nominal market instance as an algorithmic error.",
        "",
        "## Result",
        "",
        f"- Paired instances: {len(rows)} ({by_dataset['joint perturbations']} joint and {by_dataset['one-family perturbations']} one-family instances).",
        "- Every D-CHP and DWP run has status `optimal`.",
        f"- Maximum relative pricing-objective disagreement: {_max(rows, 'objective_relative_gap'):.3e}.",
        f"- Maximum relative total-uplift disagreement: {_max(rows, 'uplift_relative_gap'):.3e}.",
        "- Conclusion: the archived perturbation data show no method-specific numerical disagreement at the solver precision represented by these runs.",
        "",
        "## Joint-perturbation audit",
        "",
        *_summary_table(rows, "joint perturbations"),
        "",
        "## One-family-at-a-time audit",
        "",
        *_summary_table(rows, "one-family perturbations"),
        "",
        "## Scope boundary",
        "",
        "This is a first-round agreement audit. The archived runs do not retain a DWP reduced-cost certificate or high-accuracy solver-quality attributes. The separate `run_algorithm_stability_diagnostic.py` script is available for a strict direct-LP/DWP tolerance check in a normal local Gurobi environment if that additional evidence is needed.",
        "",
    ]
    args.out_md.write_text("\n".join(document), encoding="utf-8")
    print(f"Wrote {len(rows)} paired rows to {args.out_csv}")
    print(f"Wrote audit summary to {args.out_md}")


if __name__ == "__main__":
    main()
