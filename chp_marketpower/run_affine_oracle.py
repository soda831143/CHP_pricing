"""Build or query a numerically audited scalar CHP value/price selector."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from engine import load_case
from price_vulnerability.affine_oracle import query, solve_endpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regimes", type=Path,
                        default=Path("results/value_oracle_G2_absolute_residual_audit/value_regimes.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/affine_oracle_G2"))
    parser.add_argument("--query", type=float, help="Query a previously built oracle without a CHP solve")
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--generator", type=int, default=1, help="0-based generator index")
    parser.add_argument("--network", choices=("single", "ptdf"), default="ptdf")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    args = parser.parse_args()
    oracle_file = args.out_dir / "oracle.npz"
    if args.query is not None:
        report = json.loads((args.out_dir / "audit.json").read_text(encoding="utf-8"))
        if report["status"] != "numerically_validated":
            raise SystemExit("Oracle audit is not valid; refusing a stale query file")
        with np.load(oracle_file) as oracle:
            value, price = query(args.query, oracle["boundaries"], oracle["values"], oracle["prices"])
        print(json.dumps({"delta": args.query, "value": value, "nodal_price": price.tolist()}))
        return

    with args.regimes.open(newline="", encoding="utf-8") as stream:
        regimes = list(csv.DictReader(stream))
    if not regimes or any(float(row["right"]) <= float(row["left"]) for row in regimes):
        raise ValueError("regimes must contain increasing, nonempty intervals")
    boundaries = np.asarray([float(regimes[0]["left"])] +
                            [float(row["right"]) for row in regimes])
    if not np.all(np.isfinite(boundaries)) or any(
           not np.isfinite(float(row["left"])) or
           abs(float(row["left"]) - boundaries[k]) > 1e-10
           for k, row in enumerate(regimes)) or np.any(np.diff(boundaries) <= 0):
        raise ValueError("value regimes must be contiguous and strictly increasing")

    generators, network = load_case(
        args.case, args.network, args.T, args.segments, args.congestion
    )
    if not 0 <= args.generator < len(generators):
        raise ValueError("generator is outside the case")
    started = time.perf_counter()
    endpoints = [solve_endpoint(generators, network, args.generator, float(delta))
                 for delta in boundaries]
    midpoints = [solve_endpoint(generators, network, args.generator,
                               float((left + right) / 2))
                 for left, right in zip(boundaries[:-1], boundaries[1:])]
    checks = []
    for k, (left, mid, right) in enumerate(zip(endpoints[:-1], midpoints, endpoints[1:])):
        predicted_value, predicted_price = query(
            mid.delta, boundaries, np.asarray([point.value for point in endpoints]),
            np.stack([point.price for point in endpoints]),
        )
        checks.append({
            "interval": k + 1,
            "left": left.delta,
            "right": right.delta,
            "common_primal_gap": max(abs(left.objective @ mid.primal - left.value),
                                     abs(right.objective @ mid.primal - right.value)),
            "midpoint_value_gap": abs(predicted_value - mid.value),
            "objective_affinity": float(np.max(np.abs(
                mid.objective - 0.5 * (left.objective + right.objective)
            ))),
            "price_selection_vs_direct": float(np.max(np.abs(predicted_price - mid.price))),
        })
    max_audit = {key: max(point.audit[key] for point in endpoints + midpoints)
                 for key in endpoints[0].audit}
    max_common = max(item["common_primal_gap"] for item in checks)
    max_value = max(item["midpoint_value_gap"] for item in checks)
    max_affinity = max(item["objective_affinity"] for item in checks)
    passed = (
        max_audit["primal_feasibility"] <= 1e-7
        and max_audit["dual_sign"] <= 1e-7
        and max_audit["stationarity"] <= 1e-7
        and max_audit["price_projection"] <= 1e-9
        and max_audit["duality_gap"] <= 1e-6
        and max_audit["row_complementarity"] <= 1e-6
        and max_audit["bound_complementarity"] <= 1e-6
        and max_common <= 1e-6 and max_value <= 1e-6 and max_affinity <= 1e-9
    )
    offline_seconds = time.perf_counter() - started
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "numerically_validated" if passed else "failed",
        "scope": {"case": args.case, "network": args.network, "T": args.T,
                  "segments": args.segments, "congestion": args.congestion,
                  "generator_index": args.generator, "parameter": "all-day absolute adder"},
        "max_full_lp_residuals": max_audit,
        "intervals": checks,
        "offline_seconds": offline_seconds,
        "mean_direct_chp_seconds": float(np.mean([point.runtime for point in midpoints])),
        "interpretation": "Endpoint dual interpolation selects one optimal price; it need not match a direct solver's degenerate price.",
    }
    (args.out_dir / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not passed:
        raise SystemExit("No queryable oracle saved: primal-dual interval audit failed; see audit.json")
    np.savez_compressed(
        oracle_file, boundaries=boundaries,
        values=np.asarray([point.value for point in endpoints]),
        prices=np.stack([point.price for point in endpoints]),
        eq_duals=np.stack([point.eq_dual for point in endpoints]),
        ineq_duals=np.stack([point.ineq_dual for point in endpoints]),
        lower_duals=np.stack([point.lower_dual for point in endpoints]),
        upper_duals=np.stack([point.upper_dual for point in endpoints]),
    )
    print(f"{len(checks)} audited intervals; maximum common-primal gap {max_common:.3e} USD; "
          f"maximum duality gap {max_audit['duality_gap']:.3e} USD; "
          f"offline {offline_seconds:.2f}s; saved {oracle_file}")


if __name__ == "__main__":
    main()
