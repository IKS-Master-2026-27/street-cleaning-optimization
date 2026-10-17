"""Route-level DPs and moves for Solution B (dense networks).

A route is represented by its ordered service list (oids); movement between
services and to/from the depot follows shortest paths, so

    time(seq) = d(depot, a_1) + sum t + sum d(b_i, a_{i+1}) + d(b_last, depot).

Components:
  * held_karp_window - exact reordering/re-orientation of w consecutive services
  * select_within    - in-route selection DP (which optional services to keep)
  * insert_unserved  - best-ratio insertion of unserved optional streets
  * normalize        - turn a materialised route back into its service list
"""

from .distances import INF, Oracle
from .io import Problem
from .objective import Route
from .tour import end, orientations, start


class Dense:
    """All-pairs shortest distances for small networks (N <= ~2000)."""

    def __init__(self, problem: Problem, oracle: Oracle) -> None:
        self.p = problem
        self.oracle = oracle
        self.D = [oracle.dist_row(u) if u != problem.depot else oracle.from_depot[0]
                  for u in range(problem.num_junctions)]
        self.depot = problem.depot
        self.a = [start(problem, oid) for oid in range(2 * problem.num_streets)]
        self.b = [end(problem, oid) for oid in range(2 * problem.num_streets)]

    def time(self, seq: list[int]) -> int:
        if not seq:
            return 0
        D, a, b, t = self.D, self.a, self.b, self.p.time
        total = D[self.depot][a[seq[0]]]
        for k, oid in enumerate(seq):
            total += t[oid >> 1]
            nxt = a[seq[k + 1]] if k + 1 < len(seq) else self.depot
            total += D[b[oid]][nxt]
        return total


def value_of(problem: Problem, seq: list[int], capacity: int) -> float:
    total = 0.0
    for oid in seq:
        d = problem.delta(oid >> 1, capacity)
        if d is not None:
            total += d
    return total


# ---------------------------------------------------------------- Held-Karp

def held_karp_window(dense: Dense, seq: list[int], i: int, w: int) -> bool:
    """Optimally reorder and re-orient seq[i:i+w] between fixed neighbours.

    H[S][k] = min time from the entry node through exactly the services in S,
              ending with oriented service k (k ranges over the 2w orientations)
    H[S | {k}][k'] = min_k H[S][k] + d(end(k), start(k')) + t(k')
    Returns True if the window was improved (in place).
    """
    p, D = dense.p, dense.D
    window = seq[i:i + w]
    m = len(window)
    if m < 2:
        return False
    entry = dense.depot if i == 0 else dense.b[seq[i - 1]]
    exit_ = dense.depot if i + m >= len(seq) else dense.a[seq[i + m]]
    options = [orientations(p, oid >> 1) for oid in window]
    # flattened oriented choices: (item index, oid)
    choices = [(x, oid) for x in range(m) for oid in options[x]]
    t = [p.time[oid >> 1] for _, oid in choices]
    starts = [dense.a[oid] for _, oid in choices]
    ends = [dense.b[oid] for _, oid in choices]
    size = 1 << m
    K = len(choices)
    H = [[INF] * K for _ in range(size)]
    parent = [[-1] * K for _ in range(size)]
    row_entry = D[entry]
    for k, (x, _) in enumerate(choices):
        H[1 << x][k] = row_entry[starts[k]] + t[k]
    for S in range(1, size):
        HS = H[S]
        for k in range(K):
            base = HS[k]
            if base >= INF:
                continue
            row = D[ends[k]]
            for k2 in range(K):
                x2 = choices[k2][0]
                if S >> x2 & 1:
                    continue
                S2 = S | (1 << x2)
                value = base + row[starts[k2]] + t[k2]
                if value < H[S2][k2]:
                    H[S2][k2] = value
                    parent[S2][k2] = k
    full = size - 1
    best, best_k = INF, -1
    for k in range(K):
        if H[full][k] < INF:
            value = H[full][k] + D[ends[k]][exit_]
            if value < best:
                best, best_k = value, k
    current = row_entry[dense.a[window[0]]]
    for k in range(m):
        current += p.time[window[k] >> 1]
        nxt = dense.a[window[k + 1]] if k + 1 < m else exit_
        current += D[dense.b[window[k]]][nxt]
    if best_k < 0 or best >= current:
        return False
    order = []
    S, k = full, best_k
    while k >= 0:
        order.append(choices[k][1])
        prev = parent[S][k]
        S ^= 1 << choices[k][0]
        k = prev
    order.reverse()
    seq[i:i + m] = order
    return True


def held_karp_sweep(dense: Dense, seq: list[int], w: int = 7) -> int:
    improved = 0
    step = max(1, w // 2)
    i = 0
    while i < len(seq) - 1:
        if held_karp_window(dense, seq, i, w):
            improved += 1
        i += step
    return improved


# ------------------------------------------------------- in-route selection

def select_within(dense: Dense, seq: list[int], capacity: int,
                  max_labels: int = 48) -> list[int] | None:
    """Keep the most valuable subsequence of seq that fits in T (order fixed).

    Labels at a kept service h are Pareto pairs (time, value):
      G[h] = { (time_g + d(b_g, a_h) + t_h, value_g + delta_h) : g kept before h,
               no mandatory service strictly between g and h }
    Mandatory services are forced, optional ones with delta <= 0 are dropped.
    A label is pruned when time + d(b_h, depot) > T. Returns None if the
    mandatory services alone do not fit.
    """
    p, D, T = dense.p, dense.D, dense.p.time_limit
    seq = [oid for oid in seq
           if p.category[oid >> 1] == "M"
           or ((d := p.delta(oid >> 1, capacity)) is not None and d > 0)]
    n = len(seq)
    if n == 0:
        return []
    mand = [p.category[oid >> 1] == "M" for oid in seq]
    if any(m and p.requirement[seq[k] >> 1] > capacity for k, m in enumerate(mand)):
        return None
    val = [p.delta(oid >> 1, capacity) for oid in seq]
    a = [dense.a[oid] for oid in seq]
    b = [dense.b[oid] for oid in seq]
    t = [p.time[oid >> 1] for oid in seq]
    to_depot = [D[b[k]][dense.depot] for k in range(n)]
    labels: list[list[tuple[int, float, int, int]]] = [[] for _ in range(n)]
    first_m = next((k for k in range(n) if mand[k]), n)
    last_m = max((k for k in range(n) if mand[k]), default=-1)
    row0 = D[dense.depot]
    for h in range(n):
        cand = []
        if h <= first_m:
            tm = row0[a[h]] + t[h]
            if tm + to_depot[h] <= T:
                cand.append((tm, val[h], -1, -1))
        g = h - 1
        while g >= 0:
            if labels[g]:
                row = D[b[g]]
                step = row[a[h]] + t[h]
                for idx, (tm, v, _, _) in enumerate(labels[g]):
                    tm2 = tm + step
                    if tm2 + to_depot[h] <= T:
                        cand.append((tm2, v + val[h], g, idx))
            if mand[g]:
                break
            g -= 1
        cand.sort(key=lambda x: (x[0], -x[1]))
        pareto = []
        best_v = float("-inf")
        for c in cand:
            if c[1] > best_v + 1e-15:
                pareto.append(c)
                best_v = c[1]
        if len(pareto) > max_labels:
            step_ = len(pareto) / max_labels
            keep = sorted({int(k * step_) for k in range(max_labels)} | {len(pareto) - 1})
            pareto = [pareto[k] for k in keep]
        labels[h] = pareto
    best = None
    for h in range(max(last_m, 0) if last_m >= 0 else 0, n):
        if h < last_m:
            continue
        for idx, (tm, v, _, _) in enumerate(labels[h]):
            if best is None or v > best[0]:
                best = (v, h, idx)
    if last_m < 0:
        if best is None or best[0] <= 0:
            return []
    if best is None:
        return None
    _, h, idx = best
    out = []
    while h >= 0:
        out.append(seq[h])
        _, _, g, gidx = labels[h][idx]
        h, idx = g, gidx
    out.reverse()
    return out


# ------------------------------------------------------------- insertion

def _route_proposals(dense: Dense, seq: list[int], q: int, slack: int,
                     pool: list[int]) -> dict[int, tuple[float, int, int, int]]:
    """Best (ratio, position, oid, extra time) per pooled street for one route."""
    p, D = dense.p, dense.D
    best: dict[int, tuple[float, int, int, int]] = {}
    if slack <= 0:
        return best
    cands = []
    for j in pool:
        d = p.delta(j, q)
        if d is None or d <= 0:
            continue
        for oid in orientations(p, j):
            cands.append((oid, dense.a[oid], D[dense.b[oid]], p.time[j], d, j))
    if not cands:
        return best
    nodes_prev = [dense.depot] + [dense.b[oid] for oid in seq]
    nodes_next = [dense.a[oid] for oid in seq] + [dense.depot]
    for pos in range(len(seq) + 1):
        u, w = nodes_prev[pos], nodes_next[pos]
        row_u = D[u]
        base = row_u[w]
        for oid, a, row_b, tj, d, j in cands:
            extra = row_u[a] + tj + row_b[w] - base
            if extra <= slack:
                ratio = d / (extra if extra > 1 else 1)
                cur = best.get(j)
                if cur is None or ratio > cur[0]:
                    best[j] = (ratio, pos, oid, extra)
    return best


def insert_unserved(dense: Dense, seqs: list[list[int]], capacities: list[int],
                    max_passes: int = 1_000_000) -> int:
    """Insert unserved optional streets, best value per extra second first.

    Every route keeps its own table of best insertions; after an insertion only
    the modified route's table is recomputed, so each step is exact and costs
    O(|pool| * |route|). Returns the number of insertions made."""
    p, T = dense.p, dense.p.time_limit
    served = {oid >> 1 for seq in seqs for oid in seq}
    pool = [j for j in range(p.num_streets) if j not in served and p.category[j] == "O"]
    times = [dense.time(seq) for seq in seqs]
    tables = [_route_proposals(dense, seq, capacities[r], T - times[r], pool)
              for r, seq in enumerate(seqs)]
    inserted = 0
    while inserted < max_passes:
        best = None
        for r, table in enumerate(tables):
            for j, prop in table.items():
                if j in served:
                    continue
                if best is None or prop[0] > best[0]:
                    best = (prop[0], r, prop)
        if best is None:
            break
        _, r, (_, pos, oid, extra) = best
        seqs[r].insert(pos, oid)
        times[r] += extra
        served.add(oid >> 1)
        inserted += 1
        pool = [j for j in pool if j not in served]
        tables[r] = _route_proposals(dense, seqs[r], capacities[r], T - times[r], pool)
        for table in tables:
            table.pop(oid >> 1, None)  # other routes are unchanged: tables stay exact
    return inserted


# ------------------------------------------------------------ normalize

def normalize(problem: Problem, route: Route) -> list[int]:
    """Service list of a materialised route: every street the vehicle cleans, in
    order of its first cleaning traversal and with the traversed orientation.
    Re-connecting these services by shortest paths never takes longer."""
    to_clean = set(route.cleaned)
    seq = []
    for k, j in enumerate(route.streets):
        if j in to_clean:
            to_clean.discard(j)
            u = route.nodes[k]
            seq.append(2 * j if u == problem.a[j] else 2 * j + 1)
    return seq
