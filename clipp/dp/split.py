"""Split dynamic programs: optimal partition of a giant tour into vehicle routes.

Notation (0-based): tour tasks 0..n-1, a segment s..e is served by one vehicle as
depot -> task s -> ... -> task e -> depot. With shortest-path distances

    time(s, e) = from[s] + cum[e] - cum[s] + t[e] + to[e],
    cum[h]     = sum_{x < h} (t[x] + leg[x]).

By the triangle inequality time(s, e) is non-increasing in s and non-decreasing
in e, so for each end e the feasible starts form a window [lo(e), e] whose left
border never moves backwards. Segment values are additive (see io.Problem.delta),
so every recurrence below is evaluated with a monotone deque in O(1) amortised
per state, giving linear-time Split DPs (cf. Vidal 2016).
"""

from collections import deque
from dataclasses import dataclass

from .distances import Oracle
from .io import Problem, TYPE_OF_CAPACITY
from .tour import Tour, end, start

NEG = float("-inf")


@dataclass(frozen=True)
class Segment:
    capacity: int
    first: int  # task index s
    last: int   # task index e (inclusive)


class SplitData:
    """Prefix arrays shared by all Split variants for one tour."""

    def __init__(self, problem: Problem, oracle: Oracle, tour: Tour) -> None:
        self.problem = problem
        self.tour = tour
        n = self.n = len(tour)
        tasks = tour.tasks
        streets = [oid >> 1 for oid in tasks]
        self.streets = streets
        dfrom, dto = oracle.from_depot[0], oracle.to_depot[0]
        self.from_ = [dfrom[start(problem, oid)] for oid in tasks]
        self.to = [dto[end(problem, oid)] for oid in tasks]
        self.t = [problem.time[j] for j in streets]
        cum = [0] * (n + 1)
        for h in range(n):
            cum[h + 1] = cum[h] + self.t[h] + (tour.legs[h] if h < n - 1 else 0)
        self.cum = cum
        self.mandatory = [problem.category[j] == "M" for j in streets]
        self.m_prefix = [0] * (n + 1)
        for h in range(n):
            self.m_prefix[h + 1] = self.m_prefix[h] + self.mandatory[h]
        self._values: dict[int, list[float]] = {}
        self._windows: dict[int, list[int]] = {}

    def time(self, s: int, e: int) -> int:
        return self.from_[s] + self.cum[e] - self.cum[s] + self.t[e] + self.to[e]

    def task_value(self, h: int, q: int) -> float:
        d = self.problem.delta(self.streets[h], q)
        if self.mandatory[h]:
            return d  # None means q cannot serve it; excluded by the window
        return d if d is not None and d > 0 else 0.0

    def values(self, q: int) -> list[float]:
        """Prefix sums V_q[i] = sum of task values of tasks 0..i-1 for capacity q."""
        if q not in self._values:
            prefix = [0.0] * (self.n + 1)
            for h in range(self.n):
                v = self.task_value(h, q)
                prefix[h + 1] = prefix[h] + (v if v is not None else 0.0)
            self._values[q] = prefix
        return self._values[q]

    def window(self, q: int) -> list[int]:
        """lo[e] = smallest feasible start of a segment ending at e for capacity q
        (lo[e] = e + 1 when no segment can end at e)."""
        if q not in self._windows:
            T = self.problem.time_limit
            req = self.problem.requirement
            lo = [0] * self.n
            s = 0
            last_bad = -1
            for e in range(self.n):
                if self.mandatory[e] and req[self.streets[e]] > q:
                    last_bad = e
                if s < last_bad + 1:
                    s = last_bad + 1
                while s <= e and self.time(s, e) > T:
                    s += 1
                lo[e] = s
            self._windows[q] = lo
        return self._windows[q]

    def prefix_has_mandatory(self, i: int) -> bool:
        return self.m_prefix[i] > 0


def split_ordered(data: SplitData, capacities: list[int]) -> tuple[float, list[Segment]]:
    """Selective Split for a fleet in a fixed order (Solution A).

    State  P_k[i] = best value covering tour prefix 0..i-1 with vehicles 1..k,
                    every mandatory task of the prefix inside some route.
    P_k[i] = max( P_{k-1}[i],                                   vehicle k unused
                  P_k[i-1]                       if task i-1 is optional (skip),
                  V_q[i] + max_{s in [lo(i-1), i-1]} (P_{k-1}[s] - V_q[s]) )
    with q the capacity of vehicle k. Optimal for the given tour and order.
    """
    n = data.n
    prev = [NEG if data.prefix_has_mandatory(i) else 0.0 for i in range(n + 1)]
    choices: list[list[int]] = []
    for q in capacities:
        values = data.values(q)
        lo = data.window(q)
        cur = [NEG] * (n + 1)
        choice = [-1] * (n + 1)
        cur[0] = prev[0]
        window: deque[int] = deque()
        for i in range(1, n + 1):
            cand = i - 1
            if prev[cand] > NEG:
                key = prev[cand] - values[cand]
                while window and prev[window[-1]] - values[window[-1]] <= key:
                    window.pop()
                window.append(cand)
            low = lo[i - 1]
            while window and window[0] < low:
                window.popleft()
            best, how = prev[i], -1
            if not data.mandatory[i - 1] and cur[i - 1] > best:
                best, how = cur[i - 1], -2
            if window:
                s = window[0]
                value = values[i] + prev[s] - values[s]
                if value > best:
                    best, how = value, s
            cur[i], choice[i] = best, how
        choices.append(choice)
        prev = cur
    if prev[n] == NEG:
        return NEG, []
    segments: list[Segment] = []
    i, k = n, len(capacities) - 1
    while i > 0 and k >= 0:
        how = choices[k][i]
        if how == -1:
            k -= 1
        elif how == -2:
            i -= 1
        else:
            segments.append(Segment(capacities[k], how, i - 1))
            i, k = how, k - 1
    segments.reverse()
    return prev[n], segments


def split_heterogeneous(data: SplitData, fleet_counts: dict[int, int],
                        max_cells: int = 6_000_000) -> tuple[float, list[Segment]] | None:
    """Exact heterogeneous-fleet Selective Split (Solution B).

    The fleet order is no longer fixed: the DP chooses the vehicle type of every
    route. State (c, i), c = vector of vehicles used per type:
      P_c[i] = max( P_c[i-1]                          if task i-1 is optional,
                    max_{x: c_x > 0} V_x[i] + max_{s in win_x(i-1)} (P_{c-e_x}[s] - V_x[s]) )
    Answer: max over c <= fleet of P_c[n]. Returns None if the table is too large.
    """
    n = data.n
    types = sorted(fleet_counts)
    radix = [fleet_counts[q] + 1 for q in types]
    states = 1
    for r in radix:
        states *= r
    if states * (n + 1) > max_cells:
        return None
    strides = []
    acc = 1
    for r in radix:
        strides.append(acc)
        acc *= r
    values = {q: data.values(q) for q in types}
    windows = {q: data.window(q) for q in types}
    P: list[list[float]] = [None] * states  # type: ignore[list-item]
    how_type: list[list[int]] = [None] * states  # type: ignore[list-item]
    how_start: list[list[int]] = [None] * states  # type: ignore[list-item]
    P[0] = [NEG if data.prefix_has_mandatory(i) else 0.0 for i in range(n + 1)]
    how_type[0] = [-2] * (n + 1)
    how_start[0] = [-1] * (n + 1)
    for c in range(1, states):
        counts = [(c // strides[x]) % radix[x] for x in range(len(types))]
        cur = [NEG] * (n + 1)
        htype = [-1] * (n + 1)
        hstart = [-1] * (n + 1)
        sources = []
        for x, q in enumerate(types):
            if counts[x] > 0:
                sources.append((x, q, P[c - strides[x]], values[q], windows[q], deque()))
        for i in range(1, n + 1):
            best, bt, bs = NEG, -1, -1
            if not data.mandatory[i - 1] and cur[i - 1] > best:
                best, bt = cur[i - 1], -2
            for x, q, prev, val, lo, window in sources:
                cand = i - 1
                if prev[cand] > NEG:
                    key = prev[cand] - val[cand]
                    while window and prev[window[-1]] - val[window[-1]] <= key:
                        window.pop()
                    window.append(cand)
                low = lo[i - 1]
                while window and window[0] < low:
                    window.popleft()
                if window:
                    s = window[0]
                    value = val[i] + prev[s] - val[s]
                    if value > best:
                        best, bt, bs = value, x, s
            cur[i], htype[i], hstart[i] = best, bt, bs
        P[c], how_type[c], how_start[c] = cur, htype, hstart
    best_state = max(range(states), key=lambda c: (P[c][n], -c))
    if P[best_state][n] == NEG:
        return NEG, []
    segments: list[Segment] = []
    c, i = best_state, n
    while i > 0:
        t = how_type[c][i]
        if c == 0 or t == -2:
            i -= 1
            continue
        s = how_start[c][i]
        segments.append(Segment(types[t], s, i - 1))
        c -= strides[t]
        i = s
    segments.reverse()
    return P[best_state][n], segments


def split_min_routes(data: SplitData, capacity: int) -> list[Segment] | None:
    """Cover every task of the tour with the fewest routes of one capacity.

    R[i] = 1 + min_{s in [lo(i-1), i-1]} R[s], R[0] = 0. Because R is
    non-decreasing and the window only moves right, this is O(n).
    Returns None if some task cannot be served by this capacity.
    """
    n = data.n
    lo = data.window(capacity)
    R = [0] + [None] * n
    parent = [-1] * (n + 1)
    window: deque[int] = deque()
    for i in range(1, n + 1):
        cand = i - 1
        if R[cand] is not None:
            while window and R[window[-1]] >= R[cand]:
                window.pop()
            window.append(cand)
        while window and window[0] < lo[i - 1]:
            window.popleft()
        if window:
            s = window[0]
            R[i] = R[s] + 1
            parent[i] = s
    if R[n] is None:
        return None
    segments = []
    i = n
    while i > 0:
        s = parent[i]
        segments.append(Segment(capacity, s, i - 1))
        i = s
    segments.reverse()
    return segments


def vehicles_for(problem: Problem, segments: list[Segment]) -> list[tuple[int, Segment]]:
    """Give each segment a concrete vehicle of its capacity (fleet order)."""
    free: dict[int, list[int]] = {}
    for v in range(problem.num_vehicles - 1, -1, -1):
        free.setdefault(problem.capacities[v], []).append(v)
    assigned = []
    for seg in segments:
        pool = free.get(seg.capacity)
        if not pool:
            raise ValueError(f"no free vehicle of type {TYPE_OF_CAPACITY[seg.capacity]}")
        assigned.append((pool.pop(), seg))
    return assigned
