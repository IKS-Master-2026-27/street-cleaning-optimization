"""Filtered beam search for route construction. See docs/beam-search.md.

A *state* is a partial solution for the whole fleet: every vehicle's position
and elapsed time plus the streets still pending in the current phase. One step
extends every state in the beam by one move (shortest approach path + one
street cleaned) and keeps only the ``width`` best children (beam width). Each
vehicle proposes only its ``candidates`` nearest feasible streets (filter
width). A state keeps its vehicles' proposals in a priority queue, so a step
only recomputes the vehicle that moved and the vehicles whose proposed street
was just cleaned, instead of exploring the full tree.

Phases follow the greedy baseline: mandatory streets by requirement class
30, 20, 10 (vehicles with enough capacity), then optional streets with a
positive score gain. Within a phase every child cleans exactly one street, so
all states in the beam have cleaned the same number of streets and are compared
fairly by

    score = value - rho * cost

value  exact additive score terms: -waste for a mandatory street (its coverage
       is the same in every complete solution) and the full gain
       alpha*L/L_max - (1-alpha)*waste/W_max for an optional street;
cost   closing time of the partial solution (every vehicle's time plus its
       shortest way home); for mandatory streets their service time is left
       out, because every complete solution pays it (deadhead time);
rho    score value of one fleet second, estimated from the instance.

Deterministic: no randomness and no time limits.
"""

from collections import OrderedDict
from heapq import heapify, heappop, heappush

from .graph import build_graph, shortest_path
from .parser import Instance
from .search import ScoreModel
from .solver import VEHICLE_CAPACITIES, Solution, VehicleRoute, depot_return_times

CAPACITIES = (10, 20, 30)
FINAL_CHECKS = 8  # best complete states turned into routes and scored exactly
CACHE_NODES = 2_000_000  # junctions + streets kept in cached Dijkstra searches
_SALT = 0x9E3779B97F4A7C15


class BeamSearchError(ValueError):
    """No beam configuration could clean every mandatory street."""


class _State:
    """A partial solution. Per phase it also keeps a priority queue (``heap``)
    of its vehicles' candidate moves, best local score first. ``version[v]``
    marks vehicle v's current entries (older ones are stale), ``moves[v]`` its
    current candidates and ``watchers[street]`` the vehicles proposing a street.
    Identical idle vehicles (at the depot, time 0) of one capacity are woken one
    at a time: ``idle[q][next_idle[q]]`` is the only one in the queue."""

    __slots__ = ("score", "value", "cost", "pos", "time", "pending", "heap",
                 "version", "moves", "watchers", "idle", "next_idle", "trail",
                 "phash", "vhash")


class _Frontier:
    """Resumable Dijkstra from one junction. ``found`` lists the current
    phase's streets as (approach time, street, entry, exit) in increasing
    approach time; it is extended only as far as a query needs."""

    __slots__ = ("dist", "heap", "found")

    def __init__(self, source: int) -> None:
        self.dist = {source: 0}
        self.heap = [(0, source)]
        self.found: list[tuple[int, int, int, int]] = []

    def size(self) -> int:
        return len(self.dist) + len(self.found)

    def grow(self, graph, entries_at, ceiling: int) -> bool:
        """Settle junctions until a street is found; False when nothing more is
        reachable within ``ceiling``."""
        dist, heap, found = self.dist, self.heap, self.found
        while heap and heap[0][0] <= ceiling:
            reach, node = heappop(heap)
            if reach != dist[node]:
                continue
            for edge in graph[node]:
                step = reach + edge.time
                if step < dist.get(edge.destination, step + 1):
                    dist[edge.destination] = step
                    heappush(heap, (step, edge.destination))
            streets = entries_at.get(node)
            if streets:
                for sid, exit_ in streets:
                    found.append((reach, sid, node, exit_))
                return True
        return False


class _BeamSearch:

    def __init__(self, instance: Instance) -> None:
        self.instance = instance
        self.graph = build_graph(instance)
        self.home = depot_return_times(instance)
        self.depot = instance.depot
        self.max_time = instance.max_time
        self.caps = [VEHICLE_CAPACITIES[kind] for kind in instance.vehicle_types]
        self.num_vehicles = len(self.caps)
        streets = instance.streets
        self.street_time = [s.time for s in streets]
        self.requirement = [s.requirement for s in streets]
        self.hash = [hash((s.id, _SALT)) for s in streets]

        model = ScoreModel.from_instance(instance)
        self.gain = {}   # capacity -> per-street score gain (optional)
        self.waste = {}  # capacity -> per-street waste penalty (mandatory)
        for q in CAPACITIES:
            gains, wastes = [0.0] * len(streets), [0.0] * len(streets)
            for s in streets:
                if s.category in ("M", "O") and q >= s.requirement:
                    gains[s.id] = model.gain(s, q)
                    wastes[s.id] = (model.alpha * s.length / model.l_max
                                    if model.l_max > 0 else 0.0) - gains[s.id]
            self.gain[q], self.waste[q] = gains, wastes

        fleet = set(self.caps)
        mandatory = [s for s in streets if s.category == "M"]
        largest = max(fleet, default=0)
        too_heavy = [s.id for s in mandatory if s.requirement > largest]
        if too_heavy:
            raise BeamSearchError(
                f"no vehicle can clean mandatory streets {too_heavy[:10]}")
        self.phases = [
            (level, True, [s.id for s in mandatory if s.requirement == level])
            for level in sorted({s.requirement for s in mandatory}, reverse=True)
        ]
        optional = [s.id for s in streets if s.category == "O"
                    and any(self.gain[q][s.id] > 0.0 for q in fleet)]
        if optional:
            self.phases.append((0, False, optional))

        # rho: optional value obtainable per spare fleet second, scaled by how
        # scarce time is (optional service time / spare time, at most 1). When
        # the fleet has far more time than the optional streets need, a fleet
        # second is worth little and water waste should dominate.
        fleet_time = self.num_vehicles * self.max_time
        spare = fleet_time - sum(s.time for s in mandatory)
        best_optional = sum(max(self.gain[q][sid] for q in fleet)
                            for sid in optional)
        demand = sum(self.street_time[sid] for sid in optional)
        if spare > 0 and best_optional > 0:
            self.rho0 = best_optional / spare * min(1.0, demand / spare)
        else:
            self.rho0 = 1.0 / max(1, fleet_time)
        self.paths: dict = {}

    # Candidate generation ----------------------------------------------

    def _set_phase(self, street_ids: list[int]) -> None:
        """Index the phase's streets by entry junction (both orientations)."""
        entries: dict[int, list[tuple[int, int]]] = {}
        home = self.home
        for sid in street_ids:
            s = self.instance.streets[sid]
            if s.b in home:
                entries.setdefault(s.a, []).append((sid, s.b))
            if s.direction == 2 and s.a != s.b and s.a in home:
                entries.setdefault(s.b, []).append((sid, s.a))
        self.entries_at = entries
        self.frontiers: OrderedDict = OrderedDict()
        self.cached_nodes = 0

    def _moves(self, pos: int, elapsed: int, capacity: int, pending,
               optional: bool, k: int) -> tuple:
        """The k nearest feasible pending streets for a vehicle at ``pos``
        (exact: candidates come in increasing approach time)."""
        ceiling = self.max_time - elapsed
        if ceiling < 0:
            return ()
        frontiers = self.frontiers
        frontier = frontiers.get(pos)
        if frontier is None:
            frontier = frontiers[pos] = _Frontier(pos)
        else:
            frontiers.move_to_end(pos)
            self.cached_nodes -= frontier.size()
        moves = self._walk(frontier, elapsed, capacity, pending, optional, k,
                           ceiling)
        # Keep the cached searches within a memory budget (least recent first).
        self.cached_nodes += frontier.size()
        while self.cached_nodes > CACHE_NODES and len(frontiers) > 1:
            _, old = frontiers.popitem(last=False)
            self.cached_nodes -= old.size()
        return moves

    def _walk(self, frontier: "_Frontier", elapsed: int, capacity: int,
              pending, optional: bool, k: int, ceiling: int) -> tuple:
        home, street_time = self.home, self.street_time
        positive = self.gain[capacity]
        requirement = self.requirement
        max_time = self.max_time
        found = frontier.found
        moves = []
        i = 0
        while True:
            while i < len(found):
                move = found[i]
                i += 1
                reach, sid, _, exit_ = move
                if reach > ceiling:
                    return tuple(moves)
                if sid not in pending or requirement[sid] > capacity:
                    continue
                if optional and positive[sid] <= 0.0:
                    continue
                if elapsed + reach + street_time[sid] + home[exit_] > max_time:
                    continue
                moves.append(move)
                if len(moves) == k:
                    return tuple(moves)
            if not frontier.grow(self.graph, self.entries_at, ceiling):
                return tuple(moves)

    # Beam ------------------------------------------------------------------

    def _refresh(self, state: _State, v: int) -> bool:
        """Recompute vehicle v's candidates and queue them; False if it has none."""
        watchers = state.watchers
        for move in state.moves[v]:
            holders = watchers.get(move[1])
            if holders is not None:
                rest = tuple(w for w in holders if w != v)
                if rest:
                    watchers[move[1]] = rest
                else:
                    del watchers[move[1]]
        version = state.version[v] + 1
        state.version[v] = version
        p, q = state.pos[v], self.caps[v]
        moves = self._moves(p, state.time[v], q, state.pending, self.optional,
                            self.k)
        state.moves[v] = moves
        home, street_time, rho = self.home, self.street_time, self.rho
        base = home[p]
        values = (self.gain if self.optional else self.waste)[q]
        for move in moves:
            reach, sid, entry, exit_ = move
            cost = reach + home[exit_] - base
            if self.optional:
                cost += street_time[sid]
                value = values[sid]
            else:
                value = -values[sid]
            watchers[sid] = watchers.get(sid, ()) + (v,)
            heappush(state.heap, ((-(value - rho * cost), cost, v, sid, entry),
                                  version, move, value))
        return bool(moves)

    def _idle_rep(self, state: _State, q: int) -> int | None:
        group = state.idle.get(q, ())
        i = state.next_idle.get(q, 0)
        return group[i] if i < len(group) else None

    def _wake(self, state: _State, q: int) -> None:
        """Queue the next idle vehicle of capacity q. If it has no move, its
        identical idle twins have none either, so the group is closed."""
        v = self._idle_rep(state, q)
        if v is not None and not self._refresh(state, v):
            state.next_idle[q] = len(state.idle[q])

    def _start_phase(self, state: _State, active: list[int],
                     street_ids: list[int]) -> None:
        state.pending = set(street_ids)
        state.heap = []
        state.version = [0] * self.num_vehicles
        state.moves = [()] * self.num_vehicles
        state.watchers = {}
        idle: dict[int, list[int]] = {}
        for v in active:
            if state.time[v] == 0 and state.pos[v] == self.depot:
                idle.setdefault(self.caps[v], []).append(v)
            else:
                self._refresh(state, v)
        state.idle = {q: tuple(group) for q, group in idle.items()}
        state.next_idle = {q: 0 for q in idle}
        for q in state.idle:
            self._wake(state, q)

    def _expand(self, state: _State, width: int) -> list:
        """The ``width`` best children of ``state`` as unmaterialised tuples."""
        heap, version = state.heap, state.version
        if len(heap) > self.compact_limit:  # drop stale entries
            heap[:] = [e for e in heap if version[e[0][2]] == e[1]]
            heapify(heap)
        chosen = []
        while heap and len(chosen) < width:
            entry = heappop(heap)
            if version[entry[0][2]] == entry[1]:
                chosen.append(entry)
        for entry in chosen:  # still valid for the children
            heappush(heap, entry)
        children = []
        for local, _, move, value in chosen:
            neg_gain, cost, v, sid, entry = local
            children.append(((neg_gain - state.score, state.cost + cost, v, sid,
                              entry), state, v, move, value, cost))
        return children

    def _select(self, pool: list, width: int) -> list:
        """Best ``width`` distinct children, materialised as states."""
        pool.sort(key=lambda child: child[0])
        chosen, seen = [], set()
        for child in pool:
            key, parent, v, move, value, cost = child
            reach, sid, _, exit_ = move
            new_time = parent.time[v] + reach + self.street_time[sid]
            vhash = (parent.vhash ^ hash((v, parent.pos[v], parent.time[v]))
                     ^ hash((v, exit_, new_time)))
            signature = (parent.phash ^ self.hash[sid], vhash)
            if signature in seen:
                continue
            seen.add(signature)
            chosen.append((child, new_time, signature))
            if len(chosen) == width:
                break

        # The first child of a parent takes over its per-phase structures;
        # further children copy them first.
        by_parent: dict[int, list] = {}
        for item in chosen:
            by_parent.setdefault(id(item[0][1]), []).append(item)
        states = []
        for items in by_parent.values():
            parent = items[0][0][1]
            parts = [(parent.pending.copy(), parent.heap.copy(),
                      parent.version.copy(), parent.moves.copy(),
                      parent.watchers.copy(), parent.next_idle.copy())
                     for _ in items[1:]]
            parts.insert(0, (parent.pending, parent.heap, parent.version,
                             parent.moves, parent.watchers, parent.next_idle))
            for (child, new_time, signature), part in zip(items, parts):
                key, _, v, move, value, cost = child
                reach, sid, entry, exit_ = move
                state = _State()
                state.score = -key[0]
                state.value = parent.value + value
                state.cost = key[1]
                state.pos = parent.pos[:v] + (exit_,) + parent.pos[v + 1:]
                state.time = parent.time[:v] + (new_time,) + parent.time[v + 1:]
                (state.pending, state.heap, state.version, state.moves,
                 state.watchers, state.next_idle) = part
                state.idle = parent.idle
                state.trail = (parent.trail, v, sid, entry, exit_, reach)
                state.phash, state.vhash = signature
                self._apply(state, v, sid)
                states.append(state)
        states.sort(key=lambda s: (-s.score, s.cost))
        return states

    def _apply(self, state: _State, v: int, sid: int) -> None:
        """Update the queue after vehicle v (already moved) cleaned ``sid``:
        only v and the vehicles that proposed ``sid`` get new candidates."""
        q = self.caps[v]
        moved_rep = self._idle_rep(state, q) == v
        if moved_rep:
            state.next_idle[q] += 1
        state.pending.discard(sid)
        affected = set(state.watchers.pop(sid, ()))
        affected.add(v)
        for w in sorted(affected):
            if not self._refresh(state, w) and self._idle_rep(state, self.caps[w]) == w:
                state.next_idle[self.caps[w]] = len(state.idle[self.caps[w]])
        if moved_rep:
            self._wake(state, q)

    def run(self, width: int, k: int, rho: float) -> list[_State]:
        """Beam search over all phases; returns the best complete states."""
        self.k, self.rho = k, rho
        self.compact_limit = 4 * self.num_vehicles * k + 256
        start = _State()
        start.score = start.value = 0.0
        start.cost = 0
        start.pos = (self.depot,) * self.num_vehicles
        start.time = (0,) * self.num_vehicles
        start.trail = None
        start.vhash = 0
        for v in range(self.num_vehicles):
            start.vhash ^= hash((v, self.depot, 0))
        beam = [start]

        for level, mandatory, street_ids in self.phases:
            self.optional = not mandatory
            self._set_phase(street_ids)
            active = [v for v in range(self.num_vehicles)
                      if self.caps[v] >= level]
            for state in beam:
                self._start_phase(state, active, street_ids)
                state.phash = 0
            finished = []
            while beam:
                pool = []
                for state in beam:
                    children = self._expand(state, width) if state.pending else []
                    if children:
                        pool.extend(children)
                    elif not mandatory or not state.pending:
                        finished.append(state)
                    # else: a mandatory street is unreachable -> state dropped
                if mandatory and finished:
                    break  # all states finish a mandatory phase together
                if not pool:
                    if mandatory:
                        left = len(beam[0].pending)
                        raise BeamSearchError(
                            f"requirement {level}: {left} mandatory streets "
                            f"cannot be reached in time by any vehicle")
                    break
                beam = self._select(pool, width)
                if not mandatory and len(finished) > width:
                    finished.sort(key=lambda s: (-s.value, s.cost))
                    del finished[width:]
            beam = finished
            for state in beam:  # release per-phase memory
                state.heap = state.moves = state.watchers = state.version = None
        beam.sort(key=lambda s: (-s.value, s.cost))
        return beam[:width]

    # Solution --------------------------------------------------------------

    def to_solution(self, state: _State, cache_paths: bool = False) -> Solution:
        moves = []
        trail = state.trail
        while trail is not None:
            trail, *move = trail
            moves.append(move)
        moves.reverse()

        routes = [
            VehicleRoute(vehicle_id=v, vehicle_type=kind, capacity=self.caps[v],
                         current_junction=self.depot, junctions=[self.depot])
            for v, kind in enumerate(self.instance.vehicle_types)
        ]
        for v, sid, entry, exit_, reach in moves:
            route = routes[v]
            path = self._path(route.current_junction, entry, cache_paths)
            if path is None or path.total_time != reach:
                raise RuntimeError(f"approach path to street {sid} changed")
            route.junctions.extend(path.junctions[1:])
            route.street_ids.extend(path.street_ids)
            route.junctions.append(exit_)
            route.street_ids.append(sid)
            route.total_time += reach + self.street_time[sid]
            route.current_junction = exit_
        for route in routes:
            if route.current_junction == self.depot:
                continue
            path = self._path(route.current_junction, self.depot, cache_paths)
            if path is None:
                raise RuntimeError(f"vehicle {route.vehicle_id} cannot return")
            route.junctions.extend(path.junctions[1:])
            route.street_ids.extend(path.street_ids)
            route.total_time += path.total_time
            route.current_junction = self.depot
        self._assign_cleaning(routes)
        return Solution(routes)

    def _path(self, source: int, target: int, cache: bool):
        if not cache:
            return shortest_path(self.graph, source, target)
        key = (source, target)
        path = self.paths.get(key)
        if path is None:
            path = self.paths[key] = shortest_path(self.graph, source, target)
        return path

    def _assign_cleaning(self, routes: list[VehicleRoute]) -> None:
        """Give every traversed street to the smallest capable vehicle that
        drives over it (largest score gain); optional ones only if gain > 0.
        Optimal for fixed routes because the score is additive per street."""
        streets = self.instance.streets
        best: dict[int, tuple[int, int]] = {}
        for route in routes:
            for sid in set(route.street_ids):
                street = streets[sid]
                if street.category == "C" or route.capacity < street.requirement:
                    continue
                key = (route.capacity, route.vehicle_id)
                if sid not in best or key < best[sid]:
                    best[sid] = key
        for sid in sorted(best):
            capacity, v = best[sid]
            if streets[sid].category == "M" or self.gain[capacity][sid] > 0.0:
                routes[v].cleaned_street_ids.append(sid)


def settings(instance: Instance) -> list[tuple[int, int, float]]:
    """(width, candidates, rho_scale) tried, cheapest first, by instance size.

    Width is not monotone (a wider beam can end lower), so several widths and
    rho scales are tried and the best valid solution is kept.
    """
    work = instance.num_streets * max(1, instance.num_vehicles)
    if work <= 20_000:
        widths, scales = (1, 8, 32, 128), (0.5, 1.0, 2.0)
    elif work <= 2_000_000:
        widths, scales = (1, 4, 16), (0.5, 1.0, 2.0)
    elif work <= 10_000_000:
        widths, scales = (1, 4), (1.0,)
    else:
        widths, scales = (1,), (1.0,)
    return [(w, 3 if w > 1 else 1, r) for w in widths for r in scales]


def solve(instance: Instance, width: int | None = None,
          candidates: int | None = None, rho_scale: float | None = None,
          **_ignored) -> Solution:
    """Run the beam-search ladder and keep the best valid solution."""
    from .scoring import calculate_score
    from .validator import validate_solution

    if width is not None or candidates is not None or rho_scale is not None:
        w = max(1, width or 1)
        ladder = [(w, max(1, candidates or (3 if w > 1 else 1)),
                   1.0 if rho_scale is None else rho_scale)]
    else:
        ladder = settings(instance)
    search = _BeamSearch(instance)
    best, failures = None, []
    for w, k, scale in ladder:
        label = f"width={w} candidates={k} rho_scale={scale}"
        try:
            states = search.run(w, k, scale * search.rho0)
        except BeamSearchError as exc:
            failures.append(f"{label}: {exc}")
            continue
        states = states[:FINAL_CHECKS]
        for state in states:
            solution = search.to_solution(state, cache_paths=len(states) > 1)
            errors = validate_solution(instance, solution)
            if errors:
                failures.append(f"{label}: {errors[0]}")
                continue
            score = calculate_score(instance, solution).score
            if best is None or score > best[0]:
                best = (score, solution)
        search.paths.clear()
        if best is not None and best[0] >= 1.0 - 1e-12:
            break  # the score cannot exceed 1
    if best is None:
        raise BeamSearchError("beam search found no valid solution: "
                              + "; ".join(failures[:5]))
    return best[1]
