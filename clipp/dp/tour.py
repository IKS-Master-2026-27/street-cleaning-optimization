"""Service tasks (oriented streets) and giant-tour construction.

A task is an oriented street encoded as oid = 2 * street + orientation, where
orientation 0 runs A -> B and orientation 1 runs B -> A (two-way streets only).
"""

from dataclasses import dataclass, field
from heapq import heappop, heappush

from .distances import INF, Oracle
from .io import Problem


def start(problem: Problem, oid: int) -> int:
    j = oid >> 1
    return problem.b[j] if oid & 1 else problem.a[j]


def end(problem: Problem, oid: int) -> int:
    j = oid >> 1
    return problem.a[j] if oid & 1 else problem.b[j]


def orientations(problem: Problem, j: int) -> tuple[int, ...]:
    return (2 * j, 2 * j + 1) if problem.direction[j] == 2 else (2 * j,)


def servable(problem: Problem, oracle: Oracle, oid: int) -> bool:
    """A single-task route depot -> task -> depot fits within the time limit."""
    j = oid >> 1
    return (oracle.from_depot[0][start(problem, oid)] + problem.time[j]
            + oracle.to_depot[0][end(problem, oid)] <= problem.time_limit)


@dataclass
class Selection:
    mandatory: list[int]
    optional: list[int]
    unreachable_mandatory: list[int]


def select_streets(problem: Problem, oracle: Oracle) -> Selection:
    """Streets worth serving: every servable M street, and O streets with a positive
    contribution for some vehicle type present in the fleet."""
    mandatory, optional, unreachable = [], [], []
    for j in range(problem.num_streets):
        cat = problem.category[j]
        if cat == "C":
            continue
        ok = any(servable(problem, oracle, oid) for oid in orientations(problem, j))
        if cat == "M":
            (mandatory if ok else unreachable).append(j)
        elif ok:
            best = problem.best_delta(j)
            if best is not None and best > 0:
                optional.append(j)
    return Selection(mandatory, optional, unreachable)


@dataclass
class Tour:
    """Giant tour: ordered tasks; legs[h] = d(end(task h), start(task h+1))."""
    tasks: list[int]
    legs: list[int]
    leg_paths: list = field(default_factory=list)  # optional cached (nodes, streets)

    def __len__(self) -> int:
        return len(self.tasks)

    def leg_path(self, problem: Problem, oracle: Oracle, h: int):
        if self.leg_paths and self.leg_paths[h] is not None:
            return self.leg_paths[h]
        return oracle.path(end(problem, self.tasks[h]), start(problem, self.tasks[h + 1]))


def legs_for(problem: Problem, oracle: Oracle, tasks: list[int]) -> list[int]:
    return [oracle.d(end(problem, tasks[h]), start(problem, tasks[h + 1]))
            for h in range(len(tasks) - 1)]


def make_tour(problem: Problem, oracle: Oracle, tasks: list[int]) -> Tour:
    return Tour(list(tasks), legs_for(problem, oracle, tasks), [])


def nearest_neighbor(problem: Problem, oracle: Oracle, streets: list[int],
                     second_every: int = 0, origin: int | None = None) -> list[int]:
    """Orientation-aware nearest-neighbour ordering (dense distance rows).

    Deterministic. With second_every = k > 0, every k-th step takes the second
    nearest task instead of the nearest one, which gives
    different (but reproducible) starting tours.
    """
    options = {j: [oid for oid in orientations(problem, j) if servable(problem, oracle, oid)]
               for j in streets}
    remaining = set(j for j in streets if options[j])
    mandatory_first = {j: 0 if problem.category[j] == "M" else 1 for j in streets}
    current = problem.depot if origin is None else origin
    order: list[int] = []
    step = 0
    while remaining:
        row = oracle.from_depot[0] if current == problem.depot else oracle.dist_row(current)
        step += 1
        if second_every > 0 and step % second_every == 0:
            ranked = sorted((row[start(problem, oid)], mandatory_first[j], oid)
                            for j in remaining for oid in options[j])[:2]
            best = ranked[-1][2]
        else:
            best_key, best = None, None
            for j in remaining:
                for oid in options[j]:
                    key = (row[start(problem, oid)], mandatory_first[j], oid)
                    if best_key is None or key < best_key:
                        best_key, best = key, oid
        order.append(best)
        remaining.discard(best >> 1)
        current = end(problem, best)
    return order


def nearest_neighbor_sparse(problem: Problem, oracle: Oracle, streets: list[int]) -> Tour:
    """Nearest-neighbour tour for large networks via incremental multi-target Dijkstra.

    Each step grows a Dijkstra ball from the current position until it reaches the
    start of an unserved task, so no all-pairs distances are needed. The leg paths
    found are cached in the tour.
    """
    adjacency = oracle.net.out
    starts: dict[int, list[int]] = {}
    for j in streets:
        for oid in orientations(problem, j):
            if servable(problem, oracle, oid):
                starts.setdefault(start(problem, oid), []).append(oid)
    pending = set(oid >> 1 for lst in starts.values() for oid in lst)
    tasks: list[int] = []
    legs: list[int] = []
    paths: list = []
    current = problem.depot
    while pending:
        dist = {current: 0}
        parent: dict[int, tuple[int, int]] = {}
        heap = [(0, current)]
        chosen = None
        while heap:
            d, u = heappop(heap)
            if d != dist[u]:
                continue
            bucket = starts.get(u)
            if bucket:
                live = [oid for oid in bucket if (oid >> 1) in pending]
                starts[u] = live
                if live:
                    live.sort(key=lambda oid: (problem.category[oid >> 1] != "M", oid))
                    chosen = live[0]
                    break
            for v, t, j in adjacency[u]:
                nd = d + t
                if nd < dist.get(v, INF):
                    dist[v] = nd
                    parent[v] = (u, j)
                    heappush(heap, (nd, v))
        if chosen is None:  # cannot happen when every task is servable
            raise ValueError("unreachable tasks remain")
        target = start(problem, chosen)
        if tasks:
            nodes, path_streets = [target], []
            x = target
            while x != current:
                x_prev, j = parent[x]
                path_streets.append(j)
                nodes.append(x_prev)
                x = x_prev
            nodes.reverse()
            path_streets.reverse()
            legs.append(dist[target])
            paths.append((nodes, path_streets))
        tasks.append(chosen)
        pending.discard(chosen >> 1)
        current = end(problem, chosen)
    return Tour(tasks, legs, paths)


def concatenate(problem: Problem, oracle: Oracle, parts: list[Tour]) -> Tour:
    tasks, legs, paths = [], [], []
    for part in parts:
        if not part.tasks:
            continue
        if tasks:
            legs.append(oracle.d(end(problem, tasks[-1]), start(problem, part.tasks[0])))
            paths.append(None)
        tasks.extend(part.tasks)
        legs.extend(part.legs)
        paths.extend(part.leg_paths if part.leg_paths else [None] * len(part.legs))
    return Tour(tasks, legs, paths)


def build_tour(problem: Problem, oracle: Oracle, streets: list[int], dense: bool) -> Tour:
    if dense:
        return make_tour(problem, oracle, nearest_neighbor(problem, oracle, streets))
    return nearest_neighbor_sparse(problem, oracle, streets)


def class_of(problem: Problem, j: int) -> int:
    """Smallest capacity present in the fleet that can clean street j (or 0)."""
    for q in problem.fleet_capacities():
        if q >= problem.requirement[j]:
            return q
    return 0
