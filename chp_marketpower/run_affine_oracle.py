"""Build or query a numerically audited scalar CHP value/price selector."""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from engine import load_case
from price_vulnerability.affine_oracle import Endpoint, dual_audit_passed, query, solve_endpoint
from price_vulnerability.budgeted_oracle import build_budgeted_oracle


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
    parser.add_argument("--discover", action="store_true",
                        help="Discover intervals by largest primal-upper/dual-chord gap")
    parser.add_argument("--complete", action="store_true",
                        help="Continue refining every non-price-ready interval until coverage or budget")
    parser.add_argument("--lower", type=float, default=0.0)
    parser.add_argument("--upper", type=float, default=0.1)
    parser.add_argument("--max-points", type=int, default=40)
    parser.add_argument("--value-tolerance", type=float, default=1e-6)
    parser.add_argument("--price-tolerance", type=float, default=1e-6)
    parser.add_argument("--focus-lower", type=float)
    parser.add_argument("--focus-upper", type=float)
    parser.add_argument("--focus-budget", type=int, default=12)
    parser.add_argument("--resume", action="store_true", help="Continue a matching saved discovery checkpoint")
    parser.add_argument("--resume-from", type=Path,
                        help="Fork a saved partial map into --out-dir without modifying the source")
    parser.add_argument("--seed-delta", type=float,
                        help="With --resume-from, learn the uncovered interval containing this query")
    args = parser.parse_args()
    oracle_file = args.out_dir / "oracle.npz"
    if args.query is not None:
        report = json.loads((args.out_dir / "audit.json").read_text(encoding="utf-8"))
        if report["status"] not in {"numerically_validated", "numerically_validated_partial"}:
            raise SystemExit("Oracle audit is not valid; refusing a stale query file")
        with np.load(oracle_file) as oracle:
            boundaries = oracle["boundaries"]
            if report.get("solved_points", len(boundaries)) != len(boundaries):
                raise SystemExit("Oracle checkpoint and audit refer to different solve counts")
            if not np.isfinite(args.query) or not boundaries[0] <= args.query <= boundaries[-1]:
                raise ValueError("query is outside the preprocessed parameter domain")
            values = oracle["values"]
            prices = oracle["prices"]
            ready = oracle["price_ready"] if "price_ready" in oracle else np.ones(len(values) - 1, bool)
            k = min(int(np.searchsorted(boundaries, args.query, side="right")) - 1,
                    len(ready) - 1)
            offline = bool(ready[k] or np.any(boundaries == args.query))
            if offline:
                value, price = query(args.query, boundaries, values, prices, ready)
        if not offline:
            scope = report["scope"]
            generators, network = load_case(
                scope["case"], scope["network"], scope["T"],
                scope["segments"], scope["congestion"],
            )
            with contextlib.redirect_stdout(io.StringIO()):
                solved = solve_endpoint(generators, network, scope["generator_index"], args.query)
            value, price = solved.value, solved.price
        print(json.dumps({"delta": args.query, "value": value,
                          "nodal_price": price.tolist(),
                          "source": "offline_selector" if offline else "direct_chp_fallback"}))
        return

    if args.discover:
        if args.resume and args.resume_from is not None:
            raise ValueError("choose --resume or --resume-from, not both")
        if (args.seed_delta is None) != (args.resume_from is None):
            raise ValueError("--seed-delta and --resume-from must be supplied together")
        if args.seed_delta is not None and args.complete:
            raise ValueError("seeded learning is a local budgeted expansion, not complete mode")
        if (args.focus_lower is None) != (args.focus_upper is None):
            raise ValueError("focus-lower and focus-upper must be supplied together")
        focus = ((args.focus_lower, args.focus_upper)
                 if args.focus_lower is not None else None)
        generators, network = load_case(
            args.case, args.network, args.T, args.segments, args.congestion
        )
        if not 0 <= args.generator < len(generators):
            raise ValueError("generator is outside the case")
        scope = {"case": args.case, "network": args.network, "T": args.T,
                 "segments": args.segments, "congestion": args.congestion,
                 "generator_index": args.generator, "parameter": "all-day absolute adder"}
        previous = None
        previous_offline_seconds = 0.0
        preserved_ready = []
        original_prices = {}
        learning_seed_delta = args.seed_delta
        parent_oracle = str(args.resume_from) if args.resume_from is not None else None
        source_dir = args.resume_from or args.out_dir
        if args.resume_from is not None and args.out_dir.exists() and any(args.out_dir.iterdir()):
            raise ValueError("fork output directory must be empty to preserve the source and other files")
        if args.resume or args.resume_from is not None:
            saved = json.loads((source_dir / "audit.json").read_text(encoding="utf-8"))
            if args.resume:
                parent_oracle = saved.get("parent_oracle")
            if args.resume and saved.get("learning_seed_delta") is not None:
                learning_seed_delta = saved["learning_seed_delta"]
                if focus is None:
                    focus = tuple(saved["focus_window"])
            if (saved["scope"] != scope or saved["value_tolerance_usd"] != args.value_tolerance
                    or saved["price_tolerance_usd"] != args.price_tolerance
                    or (args.resume and saved.get("focus_window") != (
                        list(focus) if focus is not None else None))
                    or (args.resume and saved.get("completion_requested", False) != args.complete)):
                raise ValueError("saved discovery has a different case, parameter, tolerance, or focus")
            with np.load(source_dir / "oracle.npz") as old:
                keys = [str(key) for key in old["audit_keys"]]
                previous = [Endpoint(
                    float(old["boundaries"][k]), float(old["values"][k]),
                    float(old["dual_values"][k]), float(old["exposures"][k]),
                    old["prices"][k].copy(), old["objectives"][k].copy(),
                    old["primals"][k].copy(), old["eq_duals"][k].copy(),
                    old["ineq_duals"][k].copy(), old["lower_duals"][k].copy(),
                    old["upper_duals"][k].copy(),
                    dict(zip(keys, map(float, old["audit_values"][k]))),
                    float(old["runtimes"][k]),
                ) for k in range(len(old["boundaries"]))]
            if previous[0].delta != args.lower or previous[-1].delta != args.upper:
                raise ValueError("saved discovery has a different parameter domain")
            previous_offline_seconds = float(saved["offline_seconds"])
            if learning_seed_delta is not None:
                preserved_ready = [item for item in saved["intervals"] if item["price_ready"]]
                original_prices = {point.delta: point.price for point in previous}
        args.out_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        if args.seed_delta is not None:
            if not np.isfinite(args.seed_delta) or not args.lower < args.seed_delta < args.upper:
                raise ValueError("seed query must be inside the saved parameter domain")
            source_intervals = saved["intervals"]
            target = next((item for item in source_intervals
                           if item["left"] < args.seed_delta < item["right"]), None)
            if target is None or target["price_ready"]:
                raise ValueError("seed query must lie strictly inside an uncovered interval")
            if args.focus_lower is not None or args.focus_upper is not None:
                raise ValueError("seeded learning chooses its own uncovered focus interval")
            if args.max_points <= len(previous):
                raise ValueError("learning budget must exceed the saved point count")
            focus = (target["left"], target["right"])
            previous.append(solve_endpoint(generators, network, args.generator, args.seed_delta))

        def save_snapshot(points, intervals):
            boundaries = np.asarray([point.delta for point in points])
            if preserved_ready:
                index = {point.delta: k for k, point in enumerate(points)}
                for old in preserved_ready:
                    left, right = index[old["left"]], index[old["right"]]
                    if (right != left + 1
                            or not np.array_equal(points[left].price, original_prices[old["left"]])
                            or not np.array_equal(points[right].price, original_prices[old["right"]])):
                        raise RuntimeError("learning would alter a previously price-ready selector")
            ready = np.asarray([item.price_ready for item in intervals], dtype=bool)
            coverage = sum(item.right - item.left for item in intervals if item.price_ready)
            report = {
                "status": "numerically_validated" if np.all(ready)
                          else "numerically_validated_partial",
                "scope": scope,
                "method": "largest numerical primal-upper/dual-chord gap; complete-dual interval gate",
                "value_tolerance_usd": args.value_tolerance,
                "price_tolerance_usd": args.price_tolerance,
                "solved_points": len(points), "max_points": args.max_points,
                "completion_requested": args.complete,
                "intervals": [asdict(item) for item in intervals],
                "price_coverage_fraction": float(coverage / (args.upper - args.lower)),
                "focus_window": list(focus) if focus is not None else None,
                "parent_oracle": parent_oracle,
                "learning_seed_delta": learning_seed_delta,
                "focus_coverage_fraction": (
                    float(sum(
                        max(0.0, min(item.right, focus[1]) - max(item.left, focus[0]))
                        for item in intervals if item.price_ready
                    ) / (focus[1] - focus[0])) if focus is not None else None
                ),
                "max_unresolved_value_gap_usd": float(max(
                    (item.max_value_gap for item in intervals if not item.price_ready),
                    default=0.0,
                )),
                "max_full_lp_residuals": {
                    key: max(point.audit[key] for point in points) for key in points[0].audit
                },
                "offline_seconds": previous_offline_seconds + time.perf_counter() - started,
                "mean_direct_chp_seconds": float(np.mean([point.runtime for point in points])),
                "interpretation": "Uncovered intervals return direct CHP prices; value gaps never certify price accuracy.",
            }
            pending_oracle = args.out_dir / "oracle.pending.npz"
            np.savez_compressed(
                pending_oracle, boundaries=boundaries,
                values=np.asarray([point.value for point in points]),
                prices=np.stack([point.price for point in points]),
                price_ready=ready,
                objectives=np.stack([point.objective for point in points]),
                primals=np.stack([point.primal for point in points]),
                exposures=np.asarray([point.exposure for point in points]),
                dual_values=np.asarray([point.dual_value for point in points]),
                audit_keys=np.asarray(list(points[0].audit)),
                audit_values=np.asarray([
                    [point.audit[key] for key in points[0].audit] for point in points
                ]),
                runtimes=np.asarray([point.runtime for point in points]),
                eq_duals=np.stack([point.eq_dual for point in points]),
                ineq_duals=np.stack([point.ineq_dual for point in points]),
                lower_duals=np.stack([point.lower_dual for point in points]),
                upper_duals=np.stack([point.upper_dual for point in points]),
            )
            for attempt in range(10):
                try:
                    pending_oracle.replace(oracle_file)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.2)
            pending_audit = args.out_dir / "audit.pending.json"
            pending_audit.write_text(json.dumps(report, indent=2), encoding="utf-8")
            for attempt in range(10):
                try:
                    pending_audit.replace(args.out_dir / "audit.json")
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.2)
            return report

        points, intervals = build_budgeted_oracle(
            lambda delta: solve_endpoint(generators, network, args.generator, delta),
            args.lower, args.upper, max_points=args.max_points,
            value_tolerance=args.value_tolerance,
            price_tolerance=args.price_tolerance,
            focus=focus, focus_budget=(args.max_points if learning_seed_delta is not None
                                      else args.focus_budget if focus is not None else 0),
            only_focus=learning_seed_delta is not None,
            require_complete=args.complete,
            initial_points=previous,
            on_update=save_snapshot,
        )
        report = save_snapshot(points, intervals)
        ready = [item.price_ready for item in intervals]
        print(f"{len(points)} CHP solves in {report['offline_seconds']:.1f}s; "
              f"{sum(ready)}/{len(ready)} price-ready intervals; "
              f"coverage {report['price_coverage_fraction']:.1%}; "
              f"max unresolved value gap {report['max_unresolved_value_gap_usd']:.4g} USD")
        if args.complete and not all(ready):
            raise SystemExit("price coverage incomplete at the solve budget; checkpoint preserved")
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
        all(dual_audit_passed(point) for point in endpoints + midpoints)
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
        objectives=np.stack([point.objective for point in endpoints]),
        primals=np.stack([point.primal for point in endpoints]),
        exposures=np.asarray([point.exposure for point in endpoints]),
        dual_values=np.asarray([point.dual_value for point in endpoints]),
        audit_keys=np.asarray(list(endpoints[0].audit)),
        audit_values=np.asarray([
            [point.audit[key] for key in endpoints[0].audit] for point in endpoints
        ]),
        runtimes=np.asarray([point.runtime for point in endpoints]),
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
