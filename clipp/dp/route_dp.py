"""Route-level dynamic programs with memoization (used by memo.py, Solution B).

1. Windowed Held-Karp (exact DP over subsets, memoized).
   For a window of k consecutive tasks of a route, entered from node `a` and
   left towards node `b`, the cheapest order *and* orientation is

       f(mask, last) = min over prev in mask - {last} of
                       f(mask - {last}, prev) + d(end(prev), start(last)) + t(last)
       f({x}, x)     = d(a, start(x)) + t(x)
       best          = min over last of f(full, last) + d(end(last), b)

   where `last` is an oriented task (two-way streets have 2 orientations).
   The answer is memoized under (a, b, set of streets): when a window repeats
   (later sweeps, other plans sharing the same routes) it is read, not solved.

2. Multiple-choice knapsack DP for insertion.
   Each gap g between consecutive tasks of a route is a group; inserting
   street j into gap g costs c(j, g) = d(E_g, start) + t_j + d(end, S_g) - d(E_g, S_g)
   and is worth delta(j, q). Each street is offered in its cheapest gap and at
   most one street per gap is chosen:

       K[g][w] = max(K[g-1][w], max_{j in group g} K[g-1][w - c(j, g)] + delta_j)

   Inserting into different gaps is additive, so the chosen set is feasible.
   Rounds repeat because every insertion creates new gaps.
"""

import math

from .distances import INF, Oracle
from .io import Problem
from .tour import end, orientations, start


class RouteDP:
    def __init__(self, problem: Problem, oracle: Oracle, window: int = 7) -> None:
        self.problem = problem
        self.oracle = oracle
        self.depot = problem.depot
        self.window = window
        self.rows: dict[int, list[int]] = {}
        self.memo: dict[tuple, tuple[int, tuple[int, ...]]] = {}
        self.hits = 0
        self.misses = 0

    def row(self, u: int) -> list[int]:
        r = self.rows.get(u)
        if r is None:
            r = self.rows[u] = (self.oracle.from_depot[0] if u == self.depot
                                else self.oracle.dist_row(u))
        return r

    def duration(self, seq: list[int]) -> int:
        p = self.problem
        total, cur = 0, self.depot
        for o in seq:
            total += self.row(cur)[start(p, o)] + p.time[o >> 1]
            cur = end(p, o)
        return total + self.row(cur)[self.depot]

    # -- 1. windowed Held-Karp ---------------------------------------------
    def held_karp(self, a: int, b: int, streets: tuple[int, ...]) -> tuple[int, tuple[int, ...]]:
        """Cheapest a -> (all streets, any order/orientation) -> b. Memoized."""
        key = (a, b, tuple(sorted(streets)))
        stored = self.memo.get(key)
        if stored is not None:
            self.hits += 1
            return stored
        self.misses += 1
        p = self.problem
        k = len(streets)
        options = [orientations(p, j) for j in streets]
        f: dict[tuple[int, int], tuple[int, int, int]] = {}  # (mask, oid) -> (cost, prev mask, prev oid)
        ra = self.row(a)
        for x in range(k):
            for o in options[x]:
                f[(1 << x, o)] = (ra[start(p, o)] + p.time[o >> 1], 0, -1)
        for mask in range(1, 1 << k):
            for x in range(k):
                if not mask & (1 << x):
                    continue
                for o in options[x]:
                    state = f.get((mask, o))
                    if state is None:
                        continue
                    cost = state[0]
                    row_e = self.row(end(p, o))
                    for y in range(k):
                        if mask & (1 << y):
                            continue
                        nmask = mask | (1 << y)
                        for oy in options[y]:
                            c = cost + row_e[start(p, oy)] + p.time[oy >> 1]
                            old = f.get((nmask, oy))
                            if old is None or c < old[0]:
                                f[(nmask, oy)] = (c, mask, o)
        full = (1 << k) - 1
        best = None
        for x in range(k):
            for o in options[x]:
                state = f.get((full, o))
                if state is None:
                    continue
                c = state[0] + self.row(end(p, o))[b]
                if best is None or c < best[0]:
                    best = (c, o)
        order = []
        mask, o = full, best[1]
        while o != -1:
            order.append(o)
            _, pmask, po = f[(mask, o)]
            mask, o = pmask, po
        order.reverse()
        result = (best[0], tuple(order))
        self.memo[key] = result
        return result

    def reorder(self, seq: list[int]) -> list[int]:
        """Sweep Held-Karp windows over the route until no window improves."""
        p, k = self.problem, self.window
        seq = list(seq)
        if len(seq) < 2:
            return seq
        improved = True
        while improved:
            improved = False
            step = max(1, k // 2)
            for i in range(0, max(1, len(seq) - k + step), step):
                block = seq[i:i + k]
                if len(block) < 2:
                    continue
                a = self.depot if i == 0 else end(p, seq[i - 1])
                b = self.depot if i + len(block) >= len(seq) else start(p, seq[i + len(block)])
                current = self.row(a)[start(p, block[0])]
                for h, o in enumerate(block):
                    current += p.time[o >> 1]
                    nxt = start(p, block[h + 1]) if h + 1 < len(block) else b
                    current += self.row(end(p, o))[nxt]
                cost, order = self.held_karp(a, b, tuple(o >> 1 for o in block))
                if cost < current:
                    seq[i:i + len(block)] = list(order)
                    improved = True
        return seq

    # -- 2. multiple-choice knapsack insertion ------------------------------
    def insert(self, seq: list[int], capacity: int, candidates: set[int],
               max_cells: int = 2000) -> list[int]:
        p = self.problem
        seq = list(seq)
        slack = p.time_limit - self.duration(seq)
        if slack <= 0:
            return seq
        E = [self.depot] + [end(p, o) for o in seq]
        S = [start(p, o) for o in seq] + [self.depot]
        groups: dict[int, list[tuple[int, int, float, int]]] = {}  # gap -> (cost, oid, value, street)
        for j in candidates:
            value = p.delta(j, capacity)
            if value is None or value <= 0 or p.time[j] > slack:
                continue
            best = None
            for o in orientations(p, j):
                so, eo = start(p, o), end(p, o)
                row_e = self.row(eo)
                for g in range(len(seq) + 1):
                    ra = self.row(E[g])
                    if ra[so] >= INF:
                        continue
                    c = ra[so] + p.time[j] + row_e[S[g]] - ra[S[g]]
                    if c <= slack and (best is None or c < best[0]):
                        best = (c, g, o)
            if best is not None:
                c, g, o = best
                groups.setdefault(g, []).append((c, o, value, j))
        if not groups:
            return seq
        beta = max(1, math.ceil(slack / max_cells))
        W = slack // beta
        K = [0.0] * (W + 1)
        choice: list[tuple[int, list]] = []
        for g, items in groups.items():
            weights = [math.ceil(c / beta) for c, _, _, _ in items]
            new = K[:]
            pick = [-1] * (W + 1)
            for idx, (w_i, item) in enumerate(zip(weights, items)):
                value = item[2]
                for w in range(W, w_i - 1, -1):
                    v = K[w - w_i] + value
                    if v > new[w]:
                        new[w] = v
                        pick[w] = idx
            choice.append((g, items, weights, pick))
            K = new
        # backtrack: recover which item each group took
        w = max(range(W + 1), key=lambda x: K[x])
        chosen: dict[int, tuple] = {}
        for g, items, weights, pick in reversed(choice):
            idx = pick[w]
            if idx >= 0:
                chosen[g] = items[idx]
                w -= weights[idx]
        for g in sorted(chosen, reverse=True):
            c, o, value, j = chosen[g]
            seq.insert(g, o)
            candidates.discard(j)
        return seq
