"""
IEEE 30 节点 `case_30ww`（与 OneDrive `case30/withUC/case_30ww.m` 及 MATPOWER `case30` 支路一致）。

- 节点/机组/成本：与 MATLAB `case_30ww` 中覆盖的 `mpc.bus` / `mpc.gen` / `mpc.gencost` 对齐。
- 支路 r,x,b,rateA：与 MATPOWER `data/case30.m` 标准支路表一致（41 条）。
- 24h 归一化负荷与 PTDF 推导见 `case_common.py`。
"""
from __future__ import annotations

from .case_common import (
    BranchData,
    BusData,
    CaseMPC,
    GenCostData,
    GenData,
    build_load_profile,
    build_ptdf,
    derive_piecewise_costs,
    get_gen_params_for_thermal,
    get_line_limits,
)

__all__ = [
    "Case30WW", "build_case_30ww", "get_line_limits", "get_gen_params_for_thermal",
]

Case30WW = CaseMPC


def build_case_30ww(n_segments: int = 3) -> CaseMPC:
    mpc = CaseMPC()

    mpc.buses = [
        BusData(1,  3, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(2,  2, 21.7, 12.7, 1.0, 0.0, 135, 1.10, 0.95),
        BusData(3,  1, 12.4,  1.2,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(4,  1, 17.6,  1.6,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(5,  1, 0.0, 0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(6,  1, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(7,  1, 22.8, 10.9, 1.0, 0.0, 135, 1.05, 0.95),
        BusData(8,  1, 30.0, 30.0, 1.0, 0.0, 135, 1.05, 0.95),
        BusData(9,  1, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(10, 1, 15.8,  2.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(11, 1, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(12, 1, 11.2, 7.5,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(13, 2, 0.0,  0.0,  1.0, 0.0, 135, 1.10, 0.95),
        BusData(14, 1, 16.2,  1.6,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(15, 1, 8.2,  2.5,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(16, 1, 13.5,  1.8,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(17, 1, 9.0,  5.8,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(18, 1, 13.2,  0.9,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(19, 1, 9.5,  3.4,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(20, 1, 12.2,  0.7,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(21, 1, 17.5, 11.2, 1.0, 0.0, 135, 1.05, 0.95),
        BusData(22, 2, 0.0,  0.0,  1.0, 0.0, 135, 1.10, 0.95),
        BusData(23, 2, 13.2,  1.6,  1.0, 0.0, 135, 1.10, 0.95),
        BusData(24, 1, 8.7,  6.7,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(25, 1, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(26, 1, 13.5,  2.3,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(27, 2, 0.0,  0.0,  1.0, 0.0, 135, 1.10, 0.95),
        BusData(28, 1, 0.0,  0.0,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(29, 1, 12.4,  0.9,  1.0, 0.0, 135, 1.05, 0.95),
        BusData(30, 1, 10.6, 1.9,  1.0, 0.0, 135, 1.05, 0.95),
    ]

    mpc.generators = [
        GenData(1,  260.2, 120, 40, 10, 0,  T_on_min=6, T_off_min=6),
        GenData(2,  40.0,  50, 20, 50, -40, T_on_min=4, T_off_min=4), #
        GenData(22,  0.0,   80, 30, 40, -40, T_on_min=5, T_off_min=5), #
        GenData(27,  0.0,   20, 8,  40, -10, T_on_min=3, T_off_min=3), #
        GenData(23, 0.0,   100, 25, 24, -6,  T_on_min=5, T_off_min=5), #
        GenData(13, 0.0,   30, 10,  24, -6,  T_on_min=4, T_off_min=4), #
    ]

    ramps = (60, 25.0, 40.0, 10.0, 50.0, 15.0)
    # Startup fuel (Mbtu): set to ~2.5x cf for coal, ~1.5x cf for CC/gas,
    # consistent with industry hot-start data.  G3 (coal 80 MW) corrected
    # from the original St=45 to 2.5x cf.  G5 cf=10.15 is an outlier in the
    # source dataset (Unit 1007); St is kept from the original.
    # Shutdown fuel: industry practice sets shutdown at ~0.25x startup.
    genc = (
        # a, b, c, startup fuel (Mbtu), shutdown fuel (Mbtu)
        (0.00440, 13.29,   39.00,    100,   25),   # G1: coal, 50--200 MW
        (0.00977, 22.9423, 58.81, 88,  22),   # G2: 1CT+1ST CC, 25--50 MW
        (0.04592, 15.4708, 74.33,    186,   47),   # G3: coal, 30--80 MW  ← corrected
        (0.02830, 37.6968, 17.95,  30,   8),   # G4: 1CT CC, 8--20 MW
        (0.01280, 17.82,   10.15,    50,  13),   # G5: coal, 25--100 MW
        (0.06966, 26.2438, 31.67,    40,  10),   # G6: gas, 5--30 MW
    )
    mpc.gen_costs = [
        GenCostData(model=2, cost_a=a, cost_b=b, cost_c=c,
                    ramp_up=r, ramp_down=r, fuel_price=3.0,
                    startup_fuel=su, shutdown_fuel=sd)
        for (a, b, c, su, sd), r in zip(genc, ramps)
    ]

    # MATPOWER case30.m 支路 rateA（MVA, baseMVA=100），与 MATPOWER 8.1 完全一致
    _ra = 130, 130, 65, 130, 130, 65, 90, 70, 130, 32, 65, 32, 65, 65, 65, 65, 32, 32, 32, 16, 16, 16, 16, 32, 32, 32, 32, 32, 32, 16, 16, 16, 16, 16, 16, 65, 16, 16, 16, 32, 32
    _rows = [
        (1, 2, 0.02, 0.06, 0.03), (1, 3, 0.05, 0.19, 0.02), (2, 4, 0.06, 0.17, 0.02),
        (3, 4, 0.01, 0.04, 0.0), (2, 5, 0.05, 0.2, 0.02), (2, 6, 0.06, 0.18, 0.02),
        (4, 6, 0.01, 0.04, 0.0), (5, 7, 0.05, 0.12, 0.01), (6, 7, 0.03, 0.08, 0.01),
        (6, 8, 0.01, 0.04, 0.0), (6, 9, 0.0, 0.21, 0.0), (6, 10, 0.0, 0.56, 0.0),
        (9, 11, 0.0, 0.21, 0.0), (9, 10, 0.0, 0.11, 0.0), (4, 12, 0.0, 0.26, 0.0),
        (12, 13, 0.0, 0.14, 0.0), (12, 14, 0.12, 0.26, 0.0), (12, 15, 0.07, 0.13, 0.0),
        (12, 16, 0.09, 0.2, 0.0), (14, 15, 0.22, 0.2, 0.0), (16, 17, 0.08, 0.19, 0.0),
        (15, 18, 0.11, 0.22, 0.0), (18, 19, 0.06, 0.13, 0.0), (19, 20, 0.03, 0.07, 0.0),
        (10, 20, 0.09, 0.21, 0.0), (10, 17, 0.03, 0.08, 0.0), (10, 21, 0.03, 0.07, 0.0),
        (10, 22, 0.07, 0.15, 0.0), (21, 22, 0.01, 0.02, 0.0), (15, 23, 0.1, 0.2, 0.0),
        (22, 24, 0.12, 0.18, 0.0), (23, 24, 0.13, 0.27, 0.0), (24, 25, 0.19, 0.33, 0.0),
        (25, 26, 0.25, 0.38, 0.0), (25, 27, 0.11, 0.21, 0.0), (28, 27, 0.0, 0.4, 0.0),
        (27, 29, 0.22, 0.42, 0.0), (27, 30, 0.32, 0.6, 0.0), (29, 30, 0.24, 0.45, 0.0),
        (8, 28, 0.06, 0.2, 0.02), (6, 28, 0.02, 0.06, 0.01),
    ]
    assert len(_rows) == len(_ra)
    mpc.branches = [
        BranchData(f, t, r, x, b, rateA) for (f, t, r, x, b), rateA in zip(_rows, _ra)
    ]

    mpc.NB = len(mpc.buses)
    mpc.NG = len(mpc.generators)
    mpc.NL = len(mpc.branches)
    build_load_profile(mpc)
    build_ptdf(mpc)
    derive_piecewise_costs(mpc, n_segments=n_segments)
    return mpc
