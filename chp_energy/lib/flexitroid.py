"""
广义多面体 (g-polymatroid) 抽象基类。

设计目标：
  - 接口完全兼容 flexitroid-benchmark/flexitroid/flexitroid.py 的 Flexitroid 基类
  - 子类只需实现 b(S) / p(S) / T，即可继承贪心求解、紧凑约束生成等所有能力
  - greedy() 的实现严格对照 flexitroid.py 中基于扩展基多面体 b*(A) 的 Edmonds 贪心

索引约定：时间槽 t ∈ {0, 1, ..., T-1}，集合参数类型为 Set[int] 或 FrozenSet[int]。
"""

from abc import ABC, abstractmethod
from itertools import combinations
from typing import FrozenSet, Optional, Set, Tuple, Union
import numpy as np


AnySet = Union[Set[int], FrozenSet[int]]


class GPolymatroid(ABC):
    """
    广义多面体 (g-polymatroid) 抽象基类。

    数学定义
    --------
    P = { x ∈ R^T | p(S) ≤ Σ_{i∈S} x_i ≤ b(S),  ∀S ⊆ {0,...,T-1} }

    其中 b(·) 为次模函数（submodular），p(·) 为超模函数（supermodular）。

    与 flexitroid-benchmark 的关系
    --------------------------------
    - b(S) / p(S) 接口与 Flexitroid.b / .p 完全兼容（参数类型相同）
    - greedy() 方法严格对照 flexitroid.py 中 _b_star + Edmonds 贪心实现
      （升序排序 c_star，利用扩展基多面体 b*(A) 的增量赋值）
    """

    # ── 抽象接口 ──────────────────────────────────────────────────────────────

    @abstractmethod
    def b(self, S: AnySet) -> float:
        """次模上界秩函数 b(S)。"""
        pass

    @abstractmethod
    def p(self, S: AnySet) -> float:
        """超模下界秩函数 p(S)。"""
        pass

    @property
    @abstractmethod
    def T(self) -> int:
        """时间步长度。"""
        pass

    # ── 扩展基多面体辅助 ──────────────────────────────────────────────────────

    def _b_star(self, A: AnySet) -> float:
        """
        扩展基多面体 b*(A)，对应 flexitroid.py 的 _b_star()。

        规则：
          若 T ∈ A  →  b*(A) = -p(T_全集 - A)
          否则      →  b*(A) =  b(A)

        此函数仅在 greedy() 内部调用，A 为扩展地面集 {0,...,T-1,T} 的子集。
        """
        A = set(A)
        if self.T in A:
            T_set = set(range(self.T))
            return -self.p(T_set - A)
        return self.b(A)

    # ── 贪心求解器 ────────────────────────────────────────────────────────────

    def greedy(self, c: np.ndarray) -> np.ndarray:
        """
        在广义多面体上用 Edmonds 贪心算法求解 min c^T x。
        （注意：与 flexitroid.py 一致，此处对 c 升序排列，即求最小化方向的极点。）

        算法原理（对照 flexitroid.py line 54-75）：
          1. 在扩展地面集 {0,...,T}（T 为虚拟哑元）上，令 c_star[T] = 0
          2. 按 c_star 升序排列得置换 π
          3. 依次将 k 加入 S_k，赋值 v[k] = b*(S_k) - b*(S_{k-1})
          4. 去掉哑元分量，返回 v[:-1]

        此极点对应目标函数 min c^T x 的最优极点。
        若需 max，调用 greedy(-c)。

        Args
        ----
        c : (T,) 目标系数向量

        Returns
        -------
        v : (T,) 最优解（广义多面体上的极点）
        """
        assert len(c) == self.T, f"系数长度 {len(c)} ≠ T={self.T}"

        # 扩展系数向量，哑元 t* 的系数为 0
        c_star = np.append(c, 0.0)

        # 升序排列（flexitroid.py 中 argsort 默认升序）
        pi = np.argsort(c_star)

        v = np.zeros(self.T + 1)
        S_k = set()
        b_star_prev = 0.0
        for k in pi:
            S_k.add(int(k))
            b_star_now = self._b_star(S_k)
            v[k] = b_star_now - b_star_prev
            b_star_prev = b_star_now

        return v[:-1]   # 去掉哑元分量

    def greedy_maximize(self, c: np.ndarray) -> np.ndarray:
        """在广义多面体上求解 max c^T x，等价于 min (-c)^T x。"""
        return self.greedy(-c)

    # ── 紧凑约束生成（前缀和形式，O(T²) 个区间约束）────────────────────────────

    def get_compact_constraints(
        self,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        生成所有连续区间 [a,b] 对应的前缀和约束矩阵。

        连续区间约束等价于全子集约束（g-polymatroid 的 Edmonds 定理推论），
        约束数量 O(T²) 而非 O(2^T)，对 T=24 完全可解。

        Returns
        -------
        A_ub, b_ub_vec : 上界  A @ x ≤ b_ub_vec
        A_lb, b_lb_vec : 下界  A @ x ≥ b_lb_vec（即 -A @ x ≤ -b_lb_vec）
        """
        T = self.T
        n_ivl = T * (T + 1) // 2

        A      = np.zeros((n_ivl, T))
        b_ub_v = np.zeros(n_ivl)
        b_lb_v = np.zeros(n_ivl)

        idx = 0
        for a in range(T):
            for b_end in range(a, T):
                S = frozenset(range(a, b_end + 1))
                A[idx, a:b_end + 1] = 1.0
                b_ub_v[idx] = self.b(S)
                b_lb_v[idx] = self.p(S)
                idx += 1

        return A, b_ub_v, A.copy(), b_lb_v

    # ── 可行性验证（仅供测试，T 小时使用）──────────────────────────────────────

    def check_feasibility(
        self, x: np.ndarray, tol: float = 1e-6
    ) -> Tuple[bool, Optional[FrozenSet[int]]]:
        """
        验证向量 x 是否属于广义多面体（枚举全部子集，仅用于 T≤12 的测试场景）。

        Returns
        -------
        (feasible, violating_set)
        """
        for size in range(1, self.T + 1):
            for combo in combinations(range(self.T), size):
                S = frozenset(combo)
                sx = float(np.sum(x[list(S)]))
                if sx > self.b(S) + tol:
                    return False, S
                if sx < self.p(S) - tol:
                    return False, S
        return True, None
