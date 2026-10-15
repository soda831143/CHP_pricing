"""Keep raw CHP witnesses while exporting compact value and price lookup arrays."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from price_vulnerability.affine_oracle import query
from price_vulnerability.oracle_compression import compress_full_oracle, query_compact


def postprocess(oracle_dir: Path, value_tolerance: float = 1e-7,
                price_tolerance: float = 1e-8) -> dict:
    started = time.perf_counter()
    report = json.loads((oracle_dir / "audit.json").read_text(encoding="utf-8"))
    if report["status"] != "numerically_validated":
        raise ValueError("only fully price-ready oracles can be compressed")
    raw_path = oracle_dir / "oracle.npz"
    with np.load(raw_path) as raw:
        boundaries = raw["boundaries"]
        ready = raw["price_ready"]
        compression = compress_full_oracle(
            boundaries, raw["values"], raw["dual_values"],
            raw["objectives"], raw["primals"], raw["prices"], ready,
            value_tolerance=value_tolerance, price_tolerance=price_tolerance,
        )
        vi, pi = compression.value_indices, compression.price_indices
        value_boundaries, values = boundaries[vi], raw["values"][vi]
        price_boundaries, prices = boundaries[pi], raw["prices"][pi]
        # Every deleted raw breakpoint is checked, plus one interior point per raw interval.
        checks = np.unique(np.r_[boundaries, 0.5 * (boundaries[:-1] + boundaries[1:])])
        max_value_difference = 0.0
        max_price_difference = 0.0
        for delta in checks:
            old_value, old_price = query(
                float(delta), boundaries, raw["values"], raw["prices"], ready,
            )
            new_value, new_price = query_compact(
                float(delta), value_boundaries, values, price_boundaries, prices,
            )
            max_value_difference = max(max_value_difference, abs(old_value - new_value))
            max_price_difference = max(max_price_difference, float(np.max(np.abs(old_price - new_price))))
    if max_value_difference > value_tolerance or max_price_difference > price_tolerance:
        raise RuntimeError("compact map changed the declared value or price path")
    compact_path = oracle_dir / "compact.npz"
    np.savez_compressed(
        compact_path, value_boundaries=value_boundaries, values=values,
        price_boundaries=price_boundaries, prices=prices,
        value_raw_indices=vi, price_raw_indices=pi,
    )
    audit = {
        "status": "numerically_validated_compression",
        "source": "oracle.npz; raw primal and complete-dual witnesses remain unchanged",
        "source_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "raw_intervals": len(boundaries) - 1,
        "merged_value_intervals": len(vi) - 1,
        "selected_price_intervals": len(pi) - 1,
        "value_raw_indices": vi.tolist(),
        "price_raw_indices": pi.tolist(),
        "value_witness_raw_indices": list(compression.value_witness_indices),
        "max_merged_value_endpoint_gap_usd": max(compression.value_endpoint_gaps),
        "max_removed_price_deviation_usd_per_mwh": compression.max_removed_price_deviation,
        "max_checked_value_change_usd": max_value_difference,
        "max_checked_price_change_usd_per_mwh": max_price_difference,
        "value_tolerance_usd": value_tolerance,
        "price_tolerance_usd_per_mwh": price_tolerance,
        "raw_file_bytes": raw_path.stat().st_size,
        "compact_file_bytes": compact_path.stat().st_size,
        'postprocessing_seconds': time.perf_counter()-started,
        "interpretation": "Numerical common-primal merging and numerically lossless selected-price compression; not an exact symbolic certificate.",
    }
    (oracle_dir / "compression.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--value-tolerance", type=float, default=1e-7)
    parser.add_argument("--price-tolerance", type=float, default=1e-8)
    args = parser.parse_args()
    audit = postprocess(args.oracle_dir, args.value_tolerance, args.price_tolerance)
    print(f"{audit['raw_intervals']} raw intervals -> "
          f"{audit['merged_value_intervals']} value regimes and "
          f"{audit['selected_price_intervals']} unchanged selected-price segments; "
          f"{audit['compact_file_bytes']} compact bytes")


if __name__ == "__main__":
    main()
