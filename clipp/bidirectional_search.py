"""Bidirectional Search (BDS) over the street-cleaning plan state space.

The search does not look for a path between two junctions. It searches the
space of *fleet plans*: a forward search grows plan prefixes from "vehicle 0
leaves the depot", a backward search grows plan suffixes from "the last
vehicle is parked at the depot", and the two meet when a prefix and a suffix
combine into a complete, feasible plan. See docs/bidirectional-search.md.

Two modes share the same states, moves and meeting rule:

* ``exact``   - every label within the halfway limit is expanded; safe
                dominance and an admissible bound are the only pruning.
                ``OPTIMAL`` is reported only when the search completes.
* ``bounded`` - per time bucket only W labels are expanded (diversity quotas),
                each with at most K candidate tasks. Approximate: it never
                claims optimality or completeness.

Usage (from the repository root)::

    python -m clipp.bidirectional_search data/input/syntetic_generated/instance_A.txt --mode bounded
    python -m clipp.bidirectional_search <instance> --mode exact --time-limit 60 --memory-limit-mb 4000
    python -m clipp.bidirectional_search data/input/real_instances/Presheva/instance.txt --class-reduction
"""

from __future__ import annotations

import argparse
import bisect
import heapq
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from heapq import heappop, heappush
from pathlib import Path

from .output import write_solution
from .parser import Instance, parse_instance
from .scoring import calculate_score
from .solver import VEHICLE_CAPACITIES, Solution, VehicleRoute
from .validator import validate_solution

INF = 1 << 62
APSP_NODE_LIMIT = 1500          # all-pairs table below this many junctions
SWITCH = -1                     # label.step value of a vehicle switch


# =========================================================== memory helpers
def memory_mb() -> tuple[float | None, float | None]:
    """(peak, current) resident memory of this process in MiB, or (None, None).

    Windows: GetProcessMemoryInfo with explicit 64-bit argument types
    (PeakWorkingSetSize / WorkingSetSize). Elsewhere: getrusage ru_maxrss.
    """
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                   wintypes.DWORD]
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),
                                              ctypes.byref(counters), counters.cb):
                return None, None
            return counters.PeakWorkingSetSize / 2**20, counters.WorkingSetSize / 2**20
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        return peak, peak
    except Exception:  # pragma: no cover - platform specific
        return None, None


def _over_memory(limit_mb: float) -> bool:
    current = memory_mb()[1]
    return current is not None and current > limit_mb


# ================================================================== network
class Network:
    """Directed street network; every arc keeps its street ID."""

    def __init__(self, instance: Instance) -> None:
        n = instance.num_junctions
        self.n = n
        self.out: list[list[tuple[int, int, int]]] = [[] for _ in range(n)]
        self.rev: list[list[tuple[int, int, int]]] = [[] for _ in range(n)]
        for s in instance.streets:
            self.out[s.a].append((s.b, s.time, s.id))
            self.rev[s.b].append((s.a, s.time, s.id))
            if s.direction == 2:
                self.out[s.b].append((s.a, s.time, s.id))
                self.rev[s.a].append((s.b, s.time, s.id))
        for edges in self.out:
            edges.sort(key=lambda e: (e[1], e[2]))
        for edges in self.rev:
            edges.sort(key=lambda e: (e[1], e[2]))

    def tree(self, source: int, reverse: bool = False):
        """Full Dijkstra: (dist, parent node, parent street) as lists.

        reverse=True gives distances *to* ``source``; the parent then is the
        next junction on a shortest path towards ``source``.
        """
        adjacency = self.rev if reverse else self.out
        dist = [INF] * self.n
        parent = [-1] * self.n
        street = [-1] * self.n
        dist[source] = 0
        heap = [(0, source)]
        while heap:
            d, u = heappop(heap)
            if d != dist[u]:
                continue
            for v, t, sid in adjacency[u]:
                nd = d + t
                if nd < dist[v]:
                    dist[v] = nd
                    parent[v] = u
                    street[v] = sid
                    heappush(heap, (nd, v))
        return dist, parent, street


def bidirectional_dijkstra(net: Network, s: int, t: int, limit: int = INF):
    """Point-to-point shortest path (dist, street IDs) or (INF, None).

    Improved copy of ``bidirectional_dijkstra`` from the original standalone
    package (E:/bidirectional-search, bisearch/search.py): it keeps street IDs
    (so parallel streets are never merged), skips stale heap entries, stops
    with the rule ``top_f + top_b >= mu`` and gives up once ``top_f + top_b``
    exceeds ``limit``. Used only to connect a forward and a backward label.
    """
    if s == t:
        return 0, []
    dist_f, dist_b = {s: 0}, {t: 0}
    par_f: dict[int, tuple[int, int]] = {}
    par_b: dict[int, tuple[int, int]] = {}
    done_f: set[int] = set()
    done_b: set[int] = set()
    heap_f, heap_b = [(0, s)], [(0, t)]
    mu, meet = INF, -1

    def top(heap, dist, done):
        while heap and (heap[0][1] in done or heap[0][0] != dist[heap[0][1]]):
            heappop(heap)
        return heap[0][0] if heap else INF

    while True:
        tf, tb = top(heap_f, dist_f, done_f), top(heap_b, dist_b, done_b)
        if tf == INF or tb == INF or tf + tb >= mu or tf + tb > limit:
            break
        forward = tf <= tb
        heap, dist, par, done, other, adjacency = (
            (heap_f, dist_f, par_f, done_f, dist_b, net.out) if forward
            else (heap_b, dist_b, par_b, done_b, dist_f, net.rev))
        d, u = heappop(heap)
        done.add(u)
        for v, w, sid in adjacency[u]:
            nd = d + w
            if nd < dist.get(v, INF):
                dist[v] = nd
                par[v] = (u, sid)
                heappush(heap, (nd, v))
            if v in other and nd + other[v] < mu:
                mu, meet = nd + other[v], v
    if meet < 0 or mu > limit:
        return INF, None
    left: list[int] = []
    node = meet
    while node != s:
        node, sid = par_f[node]
        left.append(sid)
    left.reverse()
    node = meet
    while node != t:
        node, sid = par_b[node]
        left.append(sid)
    return mu, left


# ==================================================================== model
@dataclass
class Task:
    """Cleaning one eligible street; ``orientations`` are the legal (start, end)."""
    street: int
    time: int
    mandatory: bool
    requirement: int
    orientations: tuple[tuple[int, int], ...]


class Model:
    """Task formulation of one instance for a given internal vehicle order.

    ``vehicles`` lists original vehicle IDs in internal order; ``task_filter``
    restricts the tasks (used by the vehicle-class reduction). Values are the
    exact per-street score terms as integers over the common denominator
    ``self.denominator``: Score = (1 - alpha) + total_value / denominator.
    """

    def __init__(self, instance: Instance, vehicles: list[int] | None = None,
                 task_filter=None, network: Network | None = None,
                 trees=None, apsp: bool | None = None) -> None:
        self.instance = instance
        self.T = instance.max_time
        self.depot = instance.depot
        self.vehicles = list(range(instance.num_vehicles)) if vehicles is None else list(vehicles)
        self.C = len(self.vehicles)
        self.cap = [VEHICLE_CAPACITIES[instance.vehicle_types[v]] for v in self.vehicles]
        self.net = network or Network(instance)
        if trees is None:
            trees = (self.net.tree(self.depot), self.net.tree(self.depot, reverse=True))
        (self.from_depot, self.from_par, self.from_street), \
            (self.to_depot, self.to_par, self.to_street) = trees

        alpha = Fraction(str(instance.water_waste_penalty))
        eligible = [s for s in instance.streets if s.category in ("M", "O")]
        l_max = sum(s.length for s in eligible)
        w_max = sum((30 - s.requirement) * s.length for s in eligible)  # 1000 * max_waste
        self.alpha = alpha
        if l_max == 0:
            self.denominator = 1
        elif w_max == 0:
            self.denominator = alpha.denominator * l_max
        else:
            self.denominator = alpha.denominator * l_max * w_max

        def value(street, capacity: int) -> int:
            if l_max == 0:
                return 0
            if w_max == 0:
                return alpha.numerator * street.length
            waste = (capacity - street.requirement) * street.length
            return (alpha.numerator * street.length * w_max
                    - (alpha.denominator - alpha.numerator) * waste * l_max)

        caps = sorted(set(self.cap))
        self.tasks: list[Task] = []
        for s in eligible:
            if task_filter is not None and not task_filter(s):
                continue
            usable = [q for q in caps if q >= s.requirement]
            if s.category == "O" and not any(value(s, q) > 0 for q in usable):
                continue  # never worth cleaning: dropping it cannot lower the score
            orientations = ((s.a, s.b),) if s.direction != 2 else ((s.a, s.b), (s.b, s.a))
            self.tasks.append(Task(s.id, s.time, s.category == "M", s.requirement, orientations))
        self.n = len(self.tasks)
        self.mmask = 0
        for j, task in enumerate(self.tasks):
            if task.mandatory:
                self.mmask |= 1 << j
        # value[k][j] is None when vehicle k may not clean task j
        self.value: list[list[int | None]] = []
        for k in range(self.C):
            row: list[int | None] = []
            for task in self.tasks:
                street = instance.streets[task.street]
                if self.cap[k] < task.requirement:
                    row.append(None)
                    continue
                v = value(street, self.cap[k])
                row.append(v if (task.mandatory or v > 0) else None)
            self.value.append(row)
        self.allowed = [[j for j in range(self.n) if self.value[k][j] is not None]
                        for k in range(self.C)]
        self.best_value = [max((self.value[k][j] for k in range(self.C)
                                if self.value[k][j] is not None), default=None)
                           for j in range(self.n)]
        # caps of the vehicles still available after (forward) / before (backward)
        self.suffix_cap = [max(self.cap[k:]) for k in range(self.C)]
        self.prefix_cap = [max(self.cap[:k + 1]) for k in range(self.C)]

        self.apsp = (self.net.n <= APSP_NODE_LIMIT) if apsp is None else apsp
        if self.apsp:
            self._rows = [self.net.tree(u) for u in range(self.net.n)]

    # ---------------------------------------------------------- distances
    def dist(self, u: int, v: int) -> int:
        if u == v:
            return 0
        if self.apsp:
            return self._rows[u][0][v]
        if u == self.depot:
            return self.from_depot[v]
        if v == self.depot:
            return self.to_depot[u]
        return bidirectional_dijkstra(self.net, u, v)[0]

    def path(self, u: int, v: int) -> list[int]:
        """Street IDs of a shortest u -> v path."""
        if u == v:
            return []
        if v == self.depot:
            out, node = [], u
            while node != v:
                out.append(self.to_street[node])
                node = self.to_par[node]
            return out
        if self.apsp or u == self.depot:
            dist, parent, street = self._rows[u] if self.apsp else (
                self.from_depot, self.from_par, self.from_street)
            if dist[v] >= INF:
                raise ValueError(f"no path {u}->{v}")
            out, node = [], v
            while node != u:
                out.append(street[node])
                node = parent[node]
            out.reverse()
            return out
        d, streets = bidirectional_dijkstra(self.net, u, v)
        if streets is None:
            raise ValueError(f"no path {u}->{v}")
        return streets

    def score_of(self, total_value: int) -> float:
        return float((1 - self.alpha) + Fraction(total_value, self.denominator))


# =================================================================== labels
class Label:
    """A plan prefix (side 0, forward) or suffix (side 1, backward).

    forward : vehicle k is at ``node`` (end of its last task) after ``time``.
    backward: vehicle k must still do the suffix starting at ``node`` (start of
              its next task, or the depot) and needs ``time`` until the depot.
    ``step`` is the task index (and ``a``/``b`` its orientation) that created
    the label, SWITCH for a vehicle switch, None for the root. ``link`` holds
    the connecting street IDs when they were computed during expansion.
    """
    __slots__ = ("side", "k", "node", "time", "S", "mcount", "value", "vm", "mrem",
                 "parent", "step", "a", "b", "link", "g", "alive", "seq")

    def __init__(self, side, k, node, t, S, mcount, value, vm, mrem, parent, step,
                 a=-1, b=-1, link=None, g=0, seq=0):
        self.side, self.k, self.node, self.time = side, k, node, t
        self.S, self.mcount, self.value, self.vm, self.mrem = S, mcount, value, vm, mrem
        self.parent, self.step, self.a, self.b, self.link = parent, step, a, b, link
        self.g, self.alive, self.seq = g, True, seq


def fleet_time(model: Model, side: int, k: int, t: int) -> int:
    """g_f = k*T + t (forward), g_b = (C-1-k)*T + tau (backward)."""
    return (k if side == 0 else model.C - 1 - k) * model.T + t


def roots(model: Model, total_mand_time=(0, 0)) -> tuple[Label, Label]:
    f = Label(0, 0, model.depot, 0, 0, 0, 0, 0, total_mand_time[0], None, None,
              g=fleet_time(model, 0, 0, 0))
    b = Label(1, model.C - 1, model.depot, 0, 0, 0, 0, 0, total_mand_time[1], None, None,
              g=fleet_time(model, 1, model.C - 1, 0))
    return f, b


def task_child(model: Model, L: Label, j: int, a: int, b: int, link_time: int,
               link=None, seq=0) -> Label | None:
    """Forward: append task j (a->b) after L. Backward: prepend it before L.

    Returns None when the move is illegal (already cleaned, capacity, time).
    Both directions check the same route-time identity
        t_prefix + link + t_suffix <= T
    with the depot distances as the remaining part.
    """
    bit = 1 << j
    if L.S & bit:
        return None
    v = model.value[L.k][j]
    if v is None:
        return None
    task = model.tasks[j]
    if link_time >= INF:
        return None
    if L.side == 0:
        t2 = L.time + link_time + task.time
        if t2 + model.to_depot[b] > model.T:
            return None
        node = b
    else:
        t2 = task.time + link_time + L.time
        if model.from_depot[a] + t2 > model.T:
            return None
        node = a
    mand = task.mandatory
    return Label(L.side, L.k, node, t2, L.S | bit, L.mcount + mand, L.value + v,
                 L.vm + (v if mand else 0), L.mrem - (task.time if mand else 0),
                 L, j, a, b, link, fleet_time(model, L.side, L.k, t2), seq=seq)


def switch_child(model: Model, L: Label, seq=0) -> Label | None:
    """Forward: close vehicle k, start k+1 at the depot. Backward: k -> k-1."""
    if L.side == 0:
        if L.k >= model.C - 1 or L.time + model.to_depot[L.node] > model.T:
            return None
        k = L.k + 1
    else:
        if L.k <= 0 or model.from_depot[L.node] + L.time > model.T:
            return None
        k = L.k - 1
    return Label(L.side, k, model.depot, 0, L.S, L.mcount, L.value, L.vm, L.mrem,
                 L, SWITCH, g=fleet_time(model, L.side, k, 0), seq=seq)


def joinable(model: Model, F: Label, B: Label, require_cover: bool = True):
    """Meeting rule. Returns the connecting time or None.

    Same vehicle, disjoint cleaned sets, mandatory streets covered by the
    union, and t_f + d(u, a) + tau_b <= T.
    """
    if F.k != B.k or F.S & B.S:
        return None
    if require_cover and (F.S | B.S) & model.mmask != model.mmask:
        return None
    slack = model.T - F.time - B.time
    if slack < 0:
        return None
    d = model.dist(F.node, B.node)
    return d if d <= slack else None


def completion_bound(model: Model, L: Label) -> int | None:
    """Admissible upper bound on the value any completion can still add.

    None when the label can provably not be completed (an uncleaned
    mandatory street that no remaining vehicle can clean, or more mandatory
    service time left than fleet time left). The bound is a fractional
    knapsack of the remaining tasks with their best value over the whole
    fleet, ignoring all travel between tasks; rounded up, so it never
    underestimates.
    """
    if L.side == 0:
        remaining = (model.T - L.time) + (model.C - 1 - L.k) * model.T
        max_cap = model.suffix_cap[L.k]
    else:
        remaining = (model.T - L.time) + L.k * model.T
        max_cap = model.prefix_cap[L.k]
    total = 0
    items = []
    for j in range(model.n):
        if L.S >> j & 1:
            continue
        task = model.tasks[j]
        best = model.best_value[j]
        if task.mandatory:
            if task.requirement > max_cap or best is None:
                return None
            remaining -= task.time
            total += best
        elif best is not None and best > 0:
            items.append((best, task.time))
    if remaining < 0:
        return None
    items.sort(key=lambda it: Fraction(it[0], it[1]), reverse=True)
    for value, t in items:
        if t <= remaining:
            total += value
            remaining -= t
        else:
            total += -(-value * remaining // t)  # ceil
            break
    return total


def chain(L: Label) -> list[Label]:
    out = []
    while L is not None:
        out.append(L)
        L = L.parent
    return out


def reconstruct(model: Model, F: Label, B: Label, join_link=None,
                empty_routes: str = "loop") -> list[VehicleRoute]:
    """Concatenate prefix and suffix into one VehicleRoute per vehicle.

    Routes are returned for the model's vehicles (original IDs), with full
    junction sequences including every connecting street.
    """
    segs: list[list[int]] = [[] for _ in range(model.C)]
    cleaned: list[list[int]] = [[] for _ in range(model.C)]
    forward = chain(F)[::-1]                    # root ... F
    for L in forward[1:]:
        P = L.parent
        if L.step == SWITCH:
            segs[P.k] += model.path(P.node, model.depot)
        else:
            segs[L.k] += L.link if L.link is not None else model.path(P.node, L.a)
            segs[L.k].append(model.tasks[L.step].street)
            cleaned[L.k].append(model.tasks[L.step].street)
    segs[F.k] += join_link if join_link is not None else model.path(F.node, B.node)
    opening = False                             # next backward task opens a new vehicle
    for L in chain(B)[:-1]:                     # B ... (root excluded), time order
        P = L.parent
        if L.step == SWITCH:
            opening = True                      # vehicle L.k ended at the depot
            continue
        if opening:
            # backward labels only store the link *after* a task; a vehicle
            # planned entirely backwards still needs depot -> first task
            segs[L.k] += model.path(model.depot, L.a)
            opening = False
        segs[L.k].append(model.tasks[L.step].street)
        cleaned[L.k].append(model.tasks[L.step].street)
        segs[L.k] += L.link if L.link is not None else model.path(L.b, P.node)

    streets = model.instance.streets
    routes = []
    for k in range(model.C):
        vid = model.vehicles[k]
        vtype = model.instance.vehicle_types[vid]
        moves = segs[k]
        if not moves and empty_routes == "loop":
            moves = cheapest_loop(model)
        junctions = [model.depot]
        for sid in moves:
            s, x = streets[sid], junctions[-1]
            if s.a == x:
                junctions.append(s.b)
            elif s.direction == 2 and s.b == x:
                junctions.append(s.a)
            else:
                raise ValueError(f"reconstruction broke at street {sid} from {x}")
        routes.append(VehicleRoute(vid, vtype, VEHICLE_CAPACITIES[vtype], junctions[-1],
                                   junctions, sum(streets[s].time for s in moves),
                                   list(moves), cleaned[k]))
    return routes


def cheapest_loop(model: Model) -> list[int]:
    """Shortest depot -> x -> depot walk with at least one move (no cleaning).

    The official format asks for n >= 1 moves per vehicle (see
    docs/dynamic-programming.md); the repository validator also accepts n = 0,
    which is used when no loop fits within T.
    """
    best, best_moves = INF, []
    for v, t, sid in model.net.out[model.depot]:
        back = model.to_depot[v]
        if t + back < best:
            best, best_moves = t + back, [sid] + model.path(v, model.depot)
    return best_moves if best <= model.T else []


# ============================================================== results
@dataclass
class SearchResult:
    mode: str
    status: str                     # OPTIMAL FEASIBLE TIMEOUT MEMOUT NO_SOLUTION NO_MEETING ERROR
    optimal_proven: bool
    value: int | None = None
    predicted_score: float | None = None
    routes: list | None = None      # VehicleRoute list for the model's vehicles
    stats: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    message: str = ""


def _limit_status(limit: str | None, has_solution: bool) -> str:
    if has_solution:
        return "FEASIBLE"
    return {"time": "TIMEOUT", "memory": "MEMOUT"}.get(limit, "ERROR")


# =============================================================== BDS-Exact
def bds_exact(model: Model, time_limit: float = 60.0, memory_limit_mb: float = 4000.0,
              lower_bound: int | None = None,
              halfway: int | None = None, use_bound: bool = True,
              use_dominance: bool = True, max_labels: int | None = None) -> SearchResult:
    """Exact bidirectional label search (see module and docs).

    ``halfway`` overrides H = ceil(C*T/2) (tests use it as a negative
    control). ``lower_bound`` is the value of a known feasible plan; labels
    that cannot beat it are pruned, so when the search completes without a
    better meeting that plan is proven optimal (stats["lower_bound_optimal"]).
    """
    start = time.perf_counter()
    T, C = model.T, model.C
    H = -(-C * T // 2) if halfway is None else halfway
    if not model.apsp:
        return SearchResult("exact", "ERROR", False, message="exact mode needs the all-pairs table "
                            f"(at most {APSP_NODE_LIMIT} junctions)")
    seq = 0
    root_f, root_b = roots(model)
    heaps: list[list] = [[], []]
    dom: list[dict] = [{}, {}]
    index: list[dict] = [{}, {}]
    stats = dict(generated=2, expanded=0, dominated=0, bound_pruned=0, join_checks=0,
                 compatible_meetings=0, improvements=0, stored=0)
    best_value, best = lower_bound, None
    limit = None

    def bound_ok(L: Label) -> bool:
        if not use_bound:
            return True
        ub = completion_bound(model, L)
        if ub is None:
            return False
        return best_value is None or L.value + ub > best_value

    def register(L: Label) -> bool:
        nonlocal best_value, best
        side = L.side
        key = (L.k, L.node, L.S & model.mmask)
        if use_dominance:
            bucket = dom[side].setdefault(key, [])
            for e in bucket:
                if e.time <= L.time and e.value >= L.value and (e.S & ~L.S) == 0:
                    stats["dominated"] += 1
                    return False
            keep = []
            for e in bucket:
                if L.time <= e.time and L.value >= e.value and (L.S & ~e.S) == 0:
                    e.alive = False
                    index[side][(e.k, e.S & model.mmask)].remove(e)
                    stats["dominated"] += 1
                else:
                    keep.append(e)
            keep.append(L)
            dom[side][key] = keep
        index[side].setdefault((L.k, L.S & model.mmask), []).append(L)
        stats["stored"] += 1
        # meeting with every stored label of the other side
        want = (L.k, model.mmask & ~(L.S & model.mmask))
        for O in index[1 - side].get(want, ()):
            stats["join_checks"] += 1
            F, B = (L, O) if side == 0 else (O, L)
            if joinable(model, F, B) is None:
                continue
            stats["compatible_meetings"] += 1
            if best_value is None or F.value + B.value > best_value:
                best_value, best = F.value + B.value, (F, B, None)
                stats["improvements"] += 1
        return True

    for L in (root_f, root_b):
        register(L)
        heappush(heaps[L.side], (L.g, seq, L))
        seq += 1

    while heaps[0] or heaps[1]:
        tops = [h[0][0] if h else INF for h in heaps]
        side = 0 if tops[0] <= tops[1] else 1
        g, _, L = heappop(heaps[side])
        if not L.alive or g > H:
            continue
        if not bound_ok(L):
            stats["bound_pruned"] += 1
            continue
        stats["expanded"] += 1
        if stats["expanded"] % 500 == 0:
            if time.perf_counter() - start > time_limit:
                limit = "time"
                break
            if _over_memory(memory_limit_mb) or (max_labels and stats["stored"] > max_labels):
                limit = "memory"
                break
        children = []
        for j in model.allowed[L.k]:
            if L.S >> j & 1:
                continue
            for a, b in model.tasks[j].orientations:
                link = model.dist(L.node, a) if side == 0 else model.dist(b, L.node)
                c = task_child(model, L, j, a, b, link, seq=seq)
                if c is not None:
                    children.append(c)
                    seq += 1
        c = switch_child(model, L, seq=seq)
        if c is not None:
            children.append(c)
            seq += 1
        for c in children:
            stats["generated"] += 1
            if not bound_ok(c):
                stats["bound_pruned"] += 1
                continue
            if register(c) and c.g <= H:
                heappush(heaps[side], (c.g, c.seq, c))

    stats["runtime_s"] = time.perf_counter() - start
    stats["halfway"] = H
    params = dict(time_limit=time_limit, memory_limit_mb=memory_limit_mb, halfway=H,
                  use_bound=use_bound, use_dominance=use_dominance)
    stats["lower_bound_optimal"] = int(limit is None and best is None and lower_bound is not None)
    if limit is None:
        if best is not None or lower_bound is not None:
            status = "OPTIMAL"
        else:
            status = "NO_SOLUTION"          # exhaustive search found no plan
        proven = True
    else:
        status = _limit_status(limit, best is not None)
        proven = False
    result = SearchResult("exact", status, proven, best_value if best is not None else None,
                          stats=stats, params=params,
                          message=f"{limit} limit reached" if limit else "")
    if best is not None:
        F, B, link = best
        result.routes = reconstruct(model, F, B, link)
        result.predicted_score = model.score_of(best_value)
    return result


# ============================================================ BDS-Bounded
@dataclass
class BoundedParams:
    bucket_fraction: float = 0.02   # time bucket width = fraction * T (fleet time g)
    width: int = 32                 # W: labels expanded per bucket and side
    candidates: int = 8             # K: candidate tasks per expansion
    diversity: str = "quota"        # "quota" or "none" (top-W by priority)
    coverage_bands: int = 4         # diversity niches: mandatory-coverage bands ...
    regions: int = 4                # ... x depot-distance regions x vehicle
    meeting: str = "partitioned"    # "partitioned" or "free"
    share_split: float = 0.5        # partitioned: forward share of each class's service time
    guidance: float = 0.5           # front-to-front overlap penalty (free meeting)
    mandatory_weight: float = 64.0  # extra priority weight of mandatory value
    rank: str = "nearest"           # "nearest" or "density" candidate ranking
    overlap: float = 1.0            # each side may expand up to H + overlap*T (bounded only)
    mandatory_first: bool = False   # only mandatory candidates until the side's share is done
    join_attempts: int = 32         # partner checks per new label (cost cap)
    bucket_cap: int = 0             # pending labels kept per bucket (0 = 8*W*K)
    time_limit: float = 300.0       # seconds
    memory_limit_mb: float = 6000.0
    seed: int = 0                   # tie-breaking only
    empty_routes: str = "loop"


def _interleaved_order(instance: Instance, vehicle_ids: list[int]) -> list[int]:
    """Round-robin over vehicle types (L, M, S), so both halves get each type."""
    groups: dict[int, list[int]] = {}
    for v in vehicle_ids:
        groups.setdefault(VEHICLE_CAPACITIES[instance.vehicle_types[v]], []).append(v)
    order, lists = [], [groups[c] for c in sorted(groups, reverse=True)]
    while any(lists):
        for lst in lists:
            if lst:
                order.append(lst.pop(0))
    return order


def _partition(model: Model, split: float = 0.5) -> tuple[int, int]:
    """Split the tasks into a forward share and a backward share.

    Tasks are ordered by the DFS pre-order of their start junction in the
    shortest-path tree from the depot (nearby streets get nearby numbers) and
    each requirement class is cut where the fraction ``split`` of its service
    time is reached: a task goes forward while the service time before it is
    below ``split * total`` (exact fractions; 0.5 is the original rule
    ``2 * acc < total``). The two masks are complements, so every task is in
    exactly one share. This RESTRICTS the plans the bounded search can find.
    """
    cut = Fraction(str(split))
    if not 0 <= cut <= 1:
        raise ValueError(f"share_split must be in [0, 1], got {split}")
    n = model.net.n
    children: list[list[int]] = [[] for _ in range(n)]
    for v in range(n):
        p = model.from_par[v]
        if p >= 0:
            children[p].append(v)
    order = [n] * n
    stack, counter = [model.depot], 0
    while stack:
        u = stack.pop()
        order[u] = counter
        counter += 1
        stack.extend(reversed(children[u]))
    share_f = 0
    classes: dict[int, list[int]] = {}
    for j, task in enumerate(model.tasks):
        classes.setdefault(task.requirement, []).append(j)
    for js in classes.values():
        js.sort(key=lambda j: (min(order[a] for a, _ in model.tasks[j].orientations),
                               model.tasks[j].street))
        total = sum(model.tasks[j].time for j in js)
        acc = 0
        for j in js:
            if acc * cut.denominator < cut.numerator * total:
                share_f |= 1 << j
            acc += model.tasks[j].time
    full = (1 << model.n) - 1
    return share_f, full & ~share_f


class _Bounded:
    def __init__(self, model: Model, params: BoundedParams):
        self.m, self.p = model, params
        self.start = time.perf_counter()
        self.rng = random.Random(params.seed)
        T, C = model.T, model.C
        # Expansion limit: the exact halfway point plus a bounded-mode overlap,
        # which gives the two pruned frontiers a window of shared vehicles.
        self.H = min(C * T, -(-C * T // 2) + int(params.overlap * T))
        self.delta = max(1, int(params.bucket_fraction * T))
        if params.meeting == "partitioned":
            self.share = list(_partition(model, params.share_split))
        else:
            full = (1 << model.n) - 1
            self.share = [full, full]
        self.mshare = [s & model.mmask for s in self.share]
        self.mneed = [x.bit_count() for x in self.mshare]
        self.mtime = [sum(model.tasks[j].time for j in range(model.n) if s >> j & 1)
                      for s in self.mshare]
        kf = min(C - 1, self.H // T)
        kb = max(0, C - 1 - self.H // T)
        self.meet_lo, self.meet_hi = max(0, min(kf, kb) - 1), min(C - 1, max(kf, kb) + 1)
        self.index: list[dict] = [{}, {}]
        self.freq = [[0.0] * model.n, [0.0] * model.n]
        self.best = None                    # (value, F, B, link)
        self.stats = dict(generated=2, expanded=0, pruned=0, deduplicated=0, join_checks=0,
                          compatible_meetings=0, improvements=0, stored=0, buckets=0)
        self.seq = 0
        self.limit = None
        self.max_dist_region = max(1, max((d for d in model.from_depot if d < INF), default=1))

    # ------------------------------------------------------------ helpers
    def priority(self, L: Label) -> float:
        p = L.value + self.p.mandatory_weight * L.vm
        if self.p.meeting == "free" and self.p.guidance:
            opp, S, m = self.freq[1 - L.side], L.S & self.m.mmask, self.m
            overlap = 0.0
            while S:
                low = S & -S
                j = low.bit_length() - 1
                overlap += opp[j] * (m.best_value[j] or 0)
                S ^= low
            p -= self.p.guidance * overlap
        return p

    def niche(self, L: Label):
        need = self.mneed[L.side] or 1
        band = min(self.p.coverage_bands - 1, L.mcount * self.p.coverage_bands // need)
        d = (self.m.from_depot if L.side == 0 else self.m.to_depot)[L.node]
        region = min(self.p.regions - 1, d * self.p.regions // (self.max_dist_region + 1))
        return (L.k, band, region)

    def select(self, pool: list[Label], width: int) -> list[Label]:
        seen: dict = {}
        for L in pool:                          # duplicate states: keep the best
            key = (L.k, L.node, L.S)
            old = seen.get(key)
            if old is None or (L.time, -L.value) < (old.time, -old.value):
                if old is not None:
                    self.stats["deduplicated"] += 1
                seen[key] = L
            else:
                self.stats["deduplicated"] += 1
        ranked = sorted(seen.values(), key=lambda L: (-self.priority(L), self.rng.random()))
        if self.p.diversity == "none" or len(ranked) <= width:
            return ranked[:width]
        groups: dict = {}
        for L in ranked:
            groups.setdefault(self.niche(L), []).append(L)
        queues = list(groups.values())          # ordered by each group's best label
        chosen: list[Label] = []
        depth = 0
        while len(chosen) < width:
            progressed = False
            for q in queues:
                if depth < len(q):
                    chosen.append(q[depth])
                    progressed = True
                    if len(chosen) == width:
                        break
            if not progressed:
                break
            depth += 1
        return chosen

    def update_freq(self, side: int, chosen: list[Label]) -> None:
        if self.p.meeting != "free" or not chosen:
            return
        f = [0.0] * self.m.n
        for L in chosen:
            S = L.S & self.m.mmask
            while S:
                low = S & -S
                f[low.bit_length() - 1] += 1.0
                S ^= low
        self.freq[side] = [x / len(chosen) for x in f]

    # ---------------------------------------------------------- expansion
    def candidates(self, L: Label) -> list[tuple[int, int, int, int, object]]:
        """Up to K (task, a, b, link_time, link) moves for L inside its share."""
        m, side, K = self.m, L.side, self.p.candidates
        share = self.share[side] & ~L.S
        if self.p.mandatory_first and share & self.mshare[side]:
            share &= self.mshare[side]
        out = []
        if m.apsp:
            for j in m.allowed[L.k]:
                if not share >> j & 1:
                    continue
                task = m.tasks[j]
                for a, b in task.orientations:
                    d = m.dist(L.node, a) if side == 0 else m.dist(b, L.node)
                    if d >= INF:
                        continue
                    if side == 0 and L.time + d + task.time + m.to_depot[b] > m.T:
                        continue
                    if side == 1 and m.from_depot[a] + task.time + d + L.time > m.T:
                        continue
                    v = m.value[L.k][j] * (1 + self.p.mandatory_weight * task.mandatory)
                    key = d if self.p.rank == "nearest" else -v / (d + task.time)
                    out.append((key, j, a, b, d, task.mandatory))
            # K by rank plus the K nearest mandatory moves: the side must cover
            # its mandatory share for any meeting to exist.
            chosen = heapq.nsmallest(K, out)
            nearest_m = heapq.nsmallest(K, ((x[4],) + x[1:] for x in out if x[5]))
            seen = {(x[1], x[2]) for x in chosen}
            chosen += [x for x in nearest_m if (x[1], x[2]) not in seen]
            return [(j, a, b, d, None) for _, j, a, b, d, _ in chosen]
        # large network: local Dijkstra from the label's junction
        adjacency = m.net.out if side == 0 else m.net.rev
        budget = m.T - L.time
        dist = {L.node: 0}
        par: dict[int, tuple[int, int]] = {}
        heap = [(0, L.node)]
        settled: set[int] = set()
        found = []
        while heap and len(found) < K:
            d, x = heappop(heap)
            if x in settled or d != dist[x]:
                continue
            settled.add(x)
            if d > budget:
                break
            for j, a, b in (self.start_at[x] if side == 0 else self.end_at[x]):
                if not share >> j & 1 or m.value[L.k][j] is None:
                    continue
                task = m.tasks[j]
                if side == 0 and L.time + d + task.time + m.to_depot[b] > m.T:
                    continue
                if side == 1 and m.from_depot[a] + task.time + d + L.time > m.T:
                    continue
                found.append((j, a, b, d, x))
                if len(found) >= K:
                    break
            for y, w, sid in adjacency[x]:
                nd = d + w
                if nd < dist.get(y, INF):
                    dist[y] = nd
                    par[y] = (x, sid)
                    heappush(heap, (nd, y))
        result = []
        for j, a, b, d, x in found:
            streets, node = [], x
            while node != L.node:
                node, sid = par[node]
                streets.append(sid)
            if side == 0:
                streets.reverse()               # L.node -> a
            result.append((j, a, b, d, streets))  # backward: b -> L.node already in order
        return result

    def prepare_large(self) -> None:
        m = self.m
        self.start_at = [[] for _ in range(m.net.n)]
        self.end_at = [[] for _ in range(m.net.n)]
        for j, task in enumerate(m.tasks):
            for a, b in task.orientations:
                self.start_at[a].append((j, a, b))
                self.end_at[b].append((j, a, b))

    def complete(self, L: Label) -> bool:
        return (L.S & self.mshare[L.side]) == self.mshare[L.side]

    def meet(self, L: Label) -> None:
        if not (self.meet_lo <= L.k <= self.meet_hi):
            return
        m, side = self.m, L.side
        if self.p.meeting == "partitioned":
            if not self.complete(L):
                return
            key = L.k
            partners = self.index[1 - side].get(key, ())
        else:
            key = (L.k, L.S & m.mmask)
            partners = self.index[1 - side].get((L.k, m.mmask & ~(L.S & m.mmask)), ())
        bisect.insort(self.index[side].setdefault(key, []), L, key=lambda x: -x.value)
        L.alive = 2                             # stored: keeps its bit-set
        self.stats["stored"] += 1
        for O in partners[:self.p.join_attempts]:   # sorted by value, best first
            F, B = (L, O) if side == 0 else (O, L)
            if self.best is not None and F.value + B.value <= self.best[0]:
                break
            self.stats["join_checks"] += 1
            if F.S & B.S or (F.S | B.S) & m.mmask != m.mmask:
                continue
            slack = m.T - F.time - B.time
            if slack < 0:
                continue
            if m.apsp:
                d, link = m.dist(F.node, B.node), None
            else:
                d, link = bidirectional_dijkstra(m.net, F.node, B.node, slack)
            if d > slack:
                continue
            self.stats["compatible_meetings"] += 1
            self.best = (F.value + B.value, F, B, link)
            self.stats["improvements"] += 1

    def expand(self, L: Label) -> list[Label]:
        out = []
        for j, a, b, d, link in self.candidates(L):
            c = task_child(self.m, L, j, a, b, d, link, seq=self.seq)
            self.seq += 1
            if c is not None:
                out.append(c)
        c = switch_child(self.m, L, seq=self.seq)
        self.seq += 1
        if c is not None:
            out.append(c)
        return out

    def viable(self, L: Label) -> bool:
        """Bounded-mode pruning (partitioned meeting only, not a safe rule):
        the side's remaining mandatory share must fit in the time it has left
        before the halfway limit plus one vehicle."""
        if self.p.meeting != "partitioned":
            return True
        return L.mrem <= self.H + self.m.T - L.g

    # --------------------------------------------------------------- run
    def run(self) -> SearchResult:
        m, p = self.m, self.p
        if not m.apsp:
            self.prepare_large()
        cap = p.bucket_cap or 8 * p.width * max(1, p.candidates)
        f, b = roots(m, tuple(self.mtime))
        buckets: list[dict[int, list[Label]]] = [{}, {}]
        order: list[list[int]] = [[], []]       # heaps of bucket ids per side

        def bucket(side: int, bid: int) -> list[Label]:
            lst = buckets[side].get(bid)
            if lst is None:
                lst = buckets[side][bid] = []
                heappush(order[side], bid)
            return lst

        bucket(0, f.g // self.delta).append(f)
        bucket(1, b.g // self.delta).append(b)
        self.meet(f)
        self.meet(b)
        while True:
            # the side whose next bucket is earlier goes next (balanced growth)
            nxt = [h[0] if h else None for h in order]
            if nxt[0] is None and nxt[1] is None:
                break
            side = 0 if nxt[1] is None or (nxt[0] is not None and nxt[0] <= nxt[1]) else 1
            bucket_id = heappop(order[side])
            pool = buckets[side].pop(bucket_id)
            self.stats["buckets"] += 1
            while pool:
                chosen = self.select(pool, p.width)
                self.update_freq(side, chosen)
                nextpool: list[Label] = []
                for L in chosen:
                    if L.g > self.H:
                        continue
                    self.stats["expanded"] += 1
                    for c in self.expand(L):
                        self.stats["generated"] += 1
                        if not self.viable(c):
                            self.stats["pruned"] += 1
                            continue
                        self.meet(c)
                        if c.g > self.H:
                            continue
                        cb = c.g // self.delta
                        target = nextpool if cb == bucket_id else bucket(side, cb)
                        target.append(c)
                        if len(target) > cap and target is not nextpool:
                            target[:] = self.select(target, max(p.width, cap // 4))
                    if L.alive != 2:
                        L.S = None              # expanded and not stored: free the bit-set
                pool = nextpool
                if len(pool) > cap:
                    pool = self.select(pool, cap)
            if time.perf_counter() - self.start > p.time_limit:
                self.limit = "time"
                break
            if _over_memory(p.memory_limit_mb):
                self.limit = "memory"
                break

        self.stats["runtime_s"] = time.perf_counter() - self.start
        self.stats["halfway"] = self.H
        self.stats["bucket_width"] = self.delta
        params = asdict(p)
        if self.best is None:
            status = "NO_MEETING" if self.limit is None else _limit_status(self.limit, False)
            return SearchResult("bounded", status, False, stats=self.stats, params=params)
        value, F, B, link = self.best
        result = SearchResult("bounded", "FEASIBLE", False, value, stats=self.stats, params=params)
        result.routes = reconstruct(m, F, B, link, p.empty_routes)
        result.predicted_score = m.score_of(value)
        if self.limit:
            result.message = f"{self.limit} limit reached; best meeting so far"
        return result


def bds_bounded(model: Model, params: BoundedParams | None = None) -> SearchResult:
    return _Bounded(model, params or BoundedParams()).run()


# ======================================================== instance level
@dataclass
class RunReport:
    instance: str
    mode: str
    class_reduction: bool
    status: str
    optimal_proven: bool
    valid: bool
    score: float | None
    coverage: float | None
    efficiency: float | None
    predicted_score: float | None
    runtime_s: float
    peak_memory_mb: float
    stats: dict
    params: dict
    errors: list
    message: str = ""
    score_certificate: bool = False     # score == 1.0, the global maximum


def _assemble(instance: Instance, routes_by_vehicle: dict[int, VehicleRoute]) -> Solution:
    return Solution([routes_by_vehicle[v] for v in range(instance.num_vehicles)])


def class_reduction_groups(instance: Instance) -> list[tuple[int, list[int]]] | None:
    """[(requirement, vehicle IDs with exactly that capacity)], or None.

    Applicable only if every requirement that occurs on an eligible street has
    at least one vehicle of exactly that capacity.
    """
    reqs = {s.requirement for s in instance.streets if s.category in ("M", "O")}
    groups = []
    for cap in sorted({VEHICLE_CAPACITIES[t] for t in instance.vehicle_types} | reqs):
        vids = [v for v, t in enumerate(instance.vehicle_types) if VEHICLE_CAPACITIES[t] == cap]
        if cap in reqs and not vids:
            return None
        if vids:
            groups.append((cap, vids))
    return groups


def solve_detailed(instance: Instance, mode: str = "bounded",
                   params: BoundedParams | None = None, class_reduction: bool = False,
                   exact_time_limit: float = 60.0, exact_memory_limit_mb: float = 4000.0,
                   seed_exact: bool = True, name: str = "") -> RunReport:
    """Run BDS on an instance and validate/score with the repository code."""
    start = time.perf_counter()
    params = params or default_params(instance)
    net = Network(instance)
    trees = (net.tree(instance.depot), net.tree(instance.depot, reverse=True))
    results: list[SearchResult] = []
    routes: dict[int, VehicleRoute] = {}
    message = ""

    if class_reduction:
        groups = class_reduction_groups(instance)
        if groups is None:
            return RunReport(name, mode, True, "ERROR", False, False, None, None, None, None,
                             time.perf_counter() - start, memory_mb()[0], {}, asdict(params),
                             [], "class reduction not applicable")
        # the time limit is for the whole instance: split it over the classes
        params = BoundedParams(**{**asdict(params), "time_limit": params.time_limit / len(groups)})
        for cap, vids in groups:
            model = Model(instance, _interleaved_order(instance, vids),
                          task_filter=lambda s, cap=cap: s.requirement == cap,
                          network=net, trees=trees)
            if mode == "exact":
                results.append(bds_exact(model, exact_time_limit, exact_memory_limit_mb))
            else:
                results.append(bds_bounded(model, params))
    else:
        order = (_interleaved_order(instance, list(range(instance.num_vehicles)))
                 if mode == "bounded" else None)
        model = Model(instance, order, network=net, trees=trees)
        if mode == "exact":
            seed = None
            if seed_exact and model.apsp:
                # A feasible plan from BDS-Bounded (same search family) only
                # tightens the exact bound; it never changes what is proven.
                seed_model = Model(instance, _interleaved_order(
                    instance, list(range(instance.num_vehicles))), network=net, trees=trees)
                seed = bds_bounded(seed_model, BoundedParams(
                    time_limit=min(20.0, exact_time_limit / 4)))
                if seed.value is None:
                    seed = None
                else:
                    message = f"exact bound seeded with a BDS-Bounded plan (score {seed.predicted_score:.6f})"
            res = bds_exact(model, exact_time_limit, exact_memory_limit_mb,
                            lower_bound=None if seed is None else seed.value)
            if seed is not None and res.routes is None and res.status in ("OPTIMAL", "FEASIBLE"):
                # Completed without a strictly better meeting: the seed is optimal
                # (OPTIMAL), or the limit was hit and the seed is the best plan known.
                res.routes, res.value, res.predicted_score = seed.routes, seed.value, seed.predicted_score
            elif seed is not None and res.routes is None:   # TIMEOUT / MEMOUT
                which = "memory" if res.status == "MEMOUT" else "time"
                res.status = "FEASIBLE"
                res.routes, res.value, res.predicted_score = seed.routes, seed.value, seed.predicted_score
                res.message = f"{which} limit reached; best plan is the seed, optimality not proven"
            results.append(res)
        else:
            results.append(bds_bounded(model, params))

    stats: dict = {}
    for r in results:
        for k, v in r.stats.items():
            if isinstance(v, (int, float)):
                stats[k] = stats.get(k, 0) + v
    statuses = [r.status for r in results]
    for bad in ("ERROR", "MEMOUT", "TIMEOUT", "NO_MEETING", "NO_SOLUTION"):
        if bad in statuses:
            status = bad
            break
    else:
        status = "OPTIMAL" if all(s == "OPTIMAL" for s in statuses) else "FEASIBLE"
    proven = status == "OPTIMAL" or status == "NO_SOLUTION"
    message = "; ".join(x for x in [message] + [r.message for r in results] if x)
    if status in ("FEASIBLE", "OPTIMAL"):
        for r in results:
            for route in r.routes:
                routes[route.vehicle_id] = route
        solution = _assemble(instance, routes)
        errors = validate_solution(instance, solution)
        if errors:
            return RunReport(name, mode, class_reduction, "ERROR", False, False, None, None, None,
                             None, time.perf_counter() - start, memory_mb()[0], stats,
                             asdict(params), errors[:10], "reconstructed plan failed validation")
        score = calculate_score(instance, solution)
        predicted = None
        if not class_reduction and len(results) == 1:
            predicted = results[0].predicted_score
        certificate = score.coverage == 1.0 and score.efficiency == 1.0
        if class_reduction:
            # The search ran on a restricted problem, so the search itself proves
            # nothing about the original one. Only the score can: 1.0 means
            # coverage 1 and zero water waste, the maximum any plan can reach.
            status, proven = "FEASIBLE", False
            message = (message + "; " if message else "") + (
                "score 1.0 = global maximum (certificate from the score, not the search)"
                if certificate else "below 1.0: no optimality claim (restricted search)")
        report = RunReport(name, mode, class_reduction, status, proven, True, score.score,
                           score.coverage, score.efficiency, predicted,
                           time.perf_counter() - start, memory_mb()[0], stats, asdict(params),
                           [], message, certificate)
        report.solution = solution  # type: ignore[attr-defined]
        return report
    return RunReport(name, mode, class_reduction, status, proven, False, None, None, None, None,
                     time.perf_counter() - start, memory_mb()[0], stats, asdict(params), [],
                     message)


def default_params(instance: Instance) -> BoundedParams:
    """Defaults by size: wide beams on small inputs, narrow ones on cities."""
    tasks = sum(s.category in ("M", "O") for s in instance.streets)
    if tasks <= 2000:
        return BoundedParams()
    return BoundedParams(width=4, candidates=4, bucket_fraction=0.02, time_limit=900.0)


def report_status(report: RunReport) -> str:
    """Benchmark status vocabulary (reporting only; it does not change results).

    OPTIMAL                          exact search completed (proof by search)
    OPTIMAL_BY_OBJECTIVE_UPPER_BOUND valid plan with score 1.0 = maximum possible
    FEASIBLE                         valid plan, search ended normally, no proof
    FEASIBLE_TIMEOUT / FEASIBLE_MEMOUT valid plan, a limit cut the search
    TIMEOUT / MEMOUT                 limit reached, no plan
    NO_MEETING / NO_SOLUTION / ERROR as reported by the search
    """
    if report.valid and report.status == "OPTIMAL":
        return "OPTIMAL"
    if report.valid and report.score_certificate:
        return "OPTIMAL_BY_OBJECTIVE_UPPER_BOUND"
    if report.valid:
        stats_limit = "limit reached" in (report.message or "")
        if "memory" in (report.message or "") and stats_limit:
            return "FEASIBLE_MEMOUT"
        return "FEASIBLE_TIMEOUT" if stats_limit else "FEASIBLE"
    return report.status


class NoMeetingError(ValueError):
    pass


def solve(instance: Instance) -> Solution:
    """Repository interface: ``solve(instance) -> Solution`` (BDS-Bounded).

    Raises NoMeetingError (a ValueError) instead of substituting another
    algorithm when the two searches do not meet.
    """
    report = solve_detailed(instance, "bounded")
    if not report.valid:
        raise NoMeetingError(f"BDS-Bounded: {report.status} {report.message}".strip())
    return report.solution  # type: ignore[attr-defined]


# ===================================================================== CLI
def _instance_name(path: Path) -> str:
    return f"{path.parent.name}_instance" if path.stem == "instance" else path.stem


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bidirectional Search for street cleaning")
    ap.add_argument("instance")
    ap.add_argument("--mode", choices=("bounded", "exact"), default="bounded")
    ap.add_argument("--class-reduction", action="store_true",
                    help="restrict each street to vehicles of exactly its requirement (cities)")
    ap.add_argument("--time-limit", type=float, default=None)
    ap.add_argument("--memory-limit-mb", type=float, default=None)
    ap.add_argument("--width", type=int)
    ap.add_argument("--candidates", type=int)
    ap.add_argument("--bucket-fraction", type=float)
    ap.add_argument("--diversity", choices=("quota", "none"))
    ap.add_argument("--meeting", choices=("partitioned", "free"))
    ap.add_argument("--share-split", type=float,
                    help="partitioned meeting: forward share of each class (default 0.5)")
    ap.add_argument("--rank", choices=("density", "nearest"))
    ap.add_argument("--guidance", type=float)
    ap.add_argument("--mandatory-weight", type=float)
    ap.add_argument("--overlap", type=float, help="bounded only: expand up to H + overlap*T")
    ap.add_argument("--mandatory-first", action="store_const", const=True, default=None)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--no-seed-exact", action="store_true")
    ap.add_argument("--output-dir", default="data/output/bidirectional_search")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true", help="print one JSON line with the report")
    args = ap.parse_args(argv)

    path = Path(args.instance)
    instance = parse_instance(path)
    params = default_params(instance)
    for name in ("width", "candidates", "bucket_fraction", "diversity", "meeting", "share_split", "rank",
                 "guidance", "mandatory_weight", "overlap", "mandatory_first", "seed",
                 "time_limit", "memory_limit_mb"):
        value = getattr(args, name)
        if value is not None:
            setattr(params, name, value)
    report = solve_detailed(
        instance, args.mode, params, args.class_reduction,
        exact_time_limit=args.time_limit or 60.0,
        exact_memory_limit_mb=args.memory_limit_mb or 4000.0,
        seed_exact=not args.no_seed_exact, name=_instance_name(path))
    report.peak_memory_mb = memory_mb()[0]
    if report.valid and not args.no_write:
        tag = "exact" if args.mode == "exact" else "bounded"
        if args.class_reduction:
            tag += "_classred"
        out = Path(args.output_dir) / tag / f"{_instance_name(path)}_solution.txt"
        write_solution(report.solution, out)  # type: ignore[attr-defined]
        report.message = (report.message + "; " if report.message else "") + f"written {out}"
    data = {k: v for k, v in asdict(report).items()}
    data["report_status"] = report_status(report)
    if args.json:
        print(json.dumps(data, default=str))
    else:
        print(f"{data['instance']}: mode={data['mode']} status={data['status']} "
              f"valid={data['valid']} optimal_proven={data['optimal_proven']} "
              f"score={data['score']} runtime={data['runtime_s']:.2f}s "
              f"peak={data['peak_memory_mb']}MiB")
        print("stats:", json.dumps(data["stats"]))
        if data["message"]:
            print(data["message"])
        for e in data["errors"]:
            print("  ", e)
    return 0 if report.valid or report.status == "NO_SOLUTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
