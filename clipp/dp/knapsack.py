"""Knapsack DP that spends each vehicle's spare time on extra optional streets.

A candidate is a loop u -> a -> (street j) -> b -> u anchored at a node u the
route already visits. Loops return to their anchor, so inserting any set of
them adds exactly the sum of their costs: the selection problem is an exact
0/1 knapsack

    K[i][w] = max(K[i-1][w], K[i-1][w - c_i] + p_i),

with c_i the loop time (rounded *up* to buckets of beta seconds, so every
selection is feasible) and p_i = delta(j, q) > 0. Rounds with growing budget
fractions let later rounds anchor on loops inserted earlier, which chains
neighbouring streets into longer detours.
"""

import math

from .distances import INF, Oracle
from .io import Problem
from .objective import Route
from .tour import end, orientations, start


def knapsack(weights: list[int], profits: list[float], capacity: int) -> list[int]:
    """Exact 0/1 knapsack; returns chosen item indices."""
    best = [0.0] * (capacity + 1)
    keep: list[bytearray] = []
    for w_i, p_i in zip(weights, profits):
        row = bytearray(capacity + 1)
        if w_i <= capacity:
            for w in range(capacity, w_i - 1, -1):
                value = best[w - w_i] + p_i
                if value > best[w]:
                    best[w] = value
                    row[w] = 1
        keep.append(row)
    chosen = []
    w = capacity
    for i in range(len(weights) - 1, -1, -1):
        if keep[i][w]:
            chosen.append(i)
            w -= weights[i]
    chosen.reverse()
    return chosen


def _insert_loops(route: Route, loops: list[tuple[int, list[int], list[int]]]) -> None:
    """Insert (anchor, nodes, streets) loops at the anchor's first visit."""
    positions = []
    for anchor, nodes, streets in loops:
        positions.append((route.nodes.index(anchor), nodes, streets))
    positions.sort(key=lambda x: -x[0])
    for p, nodes, streets in positions:
        route.nodes[p + 1:p + 1] = nodes[1:]
        route.streets[p:p] = streets


def fill_spare_time(problem: Problem, oracle: Oracle, routes: list[Route],
                    rounds: tuple[float, ...] = (0.35, 0.6, 0.85, 1.0),
                    max_items: int = 200, max_cells: int = 1500,
                    max_anchors: int = 400) -> int:
    """Knapsack-DP fill of spare time. Returns the number of streets added.

    Intended for networks where distance rows are cheap (dense oracle cache)."""
    T = problem.time_limit
    cleaned = {j for route in routes for j in route.cleaned}
    added = 0
    order = sorted(range(len(routes)), key=lambda v: (routes[v].capacity, v))
    for frac in rounds:
        for v in order:
            route = routes[v]
            q = route.capacity
            slack = T - route.duration(problem)
            budget = slack if frac >= 1.0 else int(slack * frac)
            if budget <= 0:
                continue
            anchors = list(dict.fromkeys(route.nodes))[:max_anchors]
            best: dict[int, tuple[int, int, int]] = {}  # street -> (cost, anchor, oid)
            pending = [j for j in range(problem.num_streets)
                       if j not in cleaned and problem.category[j] != "C"
                       and (d := problem.delta(j, q)) is not None and d > 0]
            if not pending:
                continue
            ends = {end(problem, oid) for j in pending for oid in orientations(problem, j)}
            back_rows = {b: oracle.dist_row(b) for b in ends}
            for u in anchors:
                row_u = oracle.from_depot[0] if u == problem.depot else oracle.dist_row(u)
                for j in pending:
                    for oid in orientations(problem, j):
                        go = row_u[start(problem, oid)]
                        if go >= INF:
                            continue
                        back = back_rows[end(problem, oid)][u]
                        cost = go + problem.time[j] + back
                        cur = best.get(j)
                        if cost <= budget and (cur is None or cost < cur[0]):
                            best[j] = (cost, u, oid)
            if not best:
                continue
            items = sorted(best.items(),
                           key=lambda kv: -problem.delta(kv[0], q) / max(1, kv[1][0]))[:max_items]
            beta = max(1, math.ceil(budget / max_cells))
            weights = [math.ceil(c / beta) for _, (c, _, _) in items]
            profits = [problem.delta(j, q) for j, _ in items]
            chosen = knapsack(weights, profits, budget // beta)
            loops = []
            for i in chosen:
                j, (cost, u, oid) = items[i]
                go_nodes, go_streets = oracle.path(u, start(problem, oid))
                back_nodes, back_streets = oracle.path(end(problem, oid), u)
                nodes = go_nodes + back_nodes
                streets = go_streets + [j] + back_streets
                loops.append((u, nodes, streets))
                cleaned.add(j)
                route.cleaned.append(j)
                added += 1
            _insert_loops(route, loops)
    return added
