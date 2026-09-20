"""
Rebuilt-RMP Dantzig-Wolfe benchmark variant.

This wrapper preserves the original audit implementation in which the
restricted master problem is rebuilt at every column-generation iteration and
unit pricing subproblems are solved serially.  It is useful for implementation
sensitivity checks, while ``DantzigWolfePricing`` is the optimized benchmark
used for fair timing comparisons.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from benchmarks.dantzig_wolfe_pricing import DantzigWolfePricing
from models.generator import GeneratorParams
from models.network import NetworkModel


class RebuiltDantzigWolfePricing(DantzigWolfePricing):
    """DWP variant using repeated RMP rebuilds and serial pricing."""

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        p_dispatch: np.ndarray,
        u_dispatch: np.ndarray,
        max_iter: int = 200,
        tol: float = 1e-6,
        verbose: bool = False,
    ) -> None:
        super().__init__(
            generators=generators,
            network=network,
            p_dispatch=p_dispatch,
            u_dispatch=u_dispatch,
            max_iter=max_iter,
            tol=tol,
            verbose=verbose,
            incremental_rmp=False,
            parallel_pricing=False,
            max_workers=None,
            pricing_threads=1,
        )


class ParallelRebuiltDantzigWolfePricing(DantzigWolfePricing):
    """DWP variant using repeated RMP rebuilds and parallel unit pricing."""

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        p_dispatch: np.ndarray,
        u_dispatch: np.ndarray,
        max_iter: int = 200,
        tol: float = 1e-6,
        verbose: bool = False,
        max_workers: Optional[int] = None,
    ) -> None:
        super().__init__(
            generators=generators,
            network=network,
            p_dispatch=p_dispatch,
            u_dispatch=u_dispatch,
            max_iter=max_iter,
            tol=tol,
            verbose=verbose,
            incremental_rmp=False,
            parallel_pricing=True,
            max_workers=max_workers,
            pricing_threads=1,
        )
