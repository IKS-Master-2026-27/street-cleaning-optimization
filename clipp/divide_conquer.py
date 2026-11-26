"""Divide and Conquer: split the city into zones. See docs/divide-conquer.md.

Algorithm: workload-balanced Recursive Graph Bisection.

* Divide   - a zone (set of streets + set of vehicles) is cut in two along the
             line between its two "farthest apart" junctions (double sweep,
             pseudo-peripheral nodes). The cut is placed so that each half gets
             a share of the mandatory cleaning time proportional to the
             vehicles it receives.
* Conquer  - recurse on both halves until a zone has one vehicle (base case).
             Each vehicle then routes only inside its own zone.
* Combine  - the zone routes form one solution. Mandatory streets a zone could
             not finish in time are handed to any vehicle that still can
             (repair), then spare time is filled with optional streets and every
             route closes at the depot.
"""

from dataclasses import dataclass
from heapq import heappop, heappush

from .parser import Instance, Street
from .search import SearchSpace
from .scoring import calculate_score
from .solver import VEHICLE_CAPACITIES, GreedyAssignmentError, Solution
from .validator import validate_solution

_INF = float("inf")


@dataclass
class Zone:
    """One part of the city: the streets it holds and the vehicles serving it."""

    vehicle_ids: list[int]
    street_ids: list[int]
    depth: int = 0


# --------------------------------------------------------------------------
# Divide: recursive graph bisection
# --------------------------------------------------------------------------

def _adjacency(streets: dict[int, Street], street_ids) -> dict[int, list]:
    """Undirected adjacency of the sub-graph formed by the zone's streets.

    Direction is ignored on purpose: the zones describe *where* streets are,
    not how a vehicle drives through them (vehicles may use any street).
    """
    adjacency: dict[int, list] = {}
    for street_id in street_ids:
        street = streets[street_id]
        adjacency.setdefault(street.a, []).append((street.b, street.time))
        adjacency.setdefault(street.b, []).append((street.a, street.time))
    return adjacency


def _dijkstra(adjacency: dict[int, list], source: int) -> dict[int, int]:
    distances = {source: 0}
    queue = [(0, source)]
    while queue:
        reach, node = heappop(queue)
        if reach != distances[node]:
            continue
        for neighbour, time in adjacency[node]:
            candidate = reach + time
            if candidate < distances.get(neighbour, _INF):
                distances[neighbour] = candidate
                heappush(queue, (candidate, neighbour))
    return distances


def _farthest(distances: dict[int, int]) -> int:
    # Ties go to the smallest junction id (deterministic).
    return max(distances, key=lambda node: (distances[node], -node))


def _water_fill(loads: dict[int, float], amount: float) -> dict[int, float]:
    """Pour ``amount`` of work onto the vehicles in ``loads`` so the least
    loaded ones are raised first (all end at one common level). Returns the
    work each vehicle receives."""
    received = {vid: 0.0 for vid in loads}
    if amount <= 0 or not loads:
        return received
    ordered = sorted(loads, key=lambda vid: (loads[vid], vid))
    # Find the level L with sum(max(0, L - load)) == amount.
    level, remaining = loads[ordered[0]], amount
    for count in range(1, len(ordered) + 1):
        nxt = loads[ordered[count]] if count < len(ordered) else _INF
        room = (nxt - level) * count
        if room >= remaining:
            level += remaining / count
            break
        remaining -= room
        level = nxt
    for vid in ordered:
        received[vid] = max(0.0, level - loads[vid])
    return received


def expected_shares(instance: Instance, streets, zone: Zone) -> dict:
    """Expected work of each vehicle per requirement class (capacity-aware).

    The hardest class goes first and only to vehicles able to clean it; each
    easier class is water-filled over all vehicles that can clean it, so the
    total expected load per vehicle ends up as even as the capacities allow.
    Returns {requirement: {vehicle_id: work}}.
    """
    work: dict[int, float] = {}
    for sid in zone.street_ids:
        street = streets[sid]
        if street.category == "M":
            work[street.requirement] = work.get(street.requirement, 0.0) + street.time
    loads = {vid: 0.0 for vid in zone.vehicle_ids}
    shares = {}
    for requirement in sorted(work, reverse=True):
        able = {vid: loads[vid] for vid in zone.vehicle_ids
                if VEHICLE_CAPACITIES[instance.vehicle_types[vid]] >= requirement}
        shares[requirement] = _water_fill(able, work[requirement])
        for vid, amount in shares[requirement].items():
            loads[vid] += amount
    return shares


def _seed(adjacency: dict[int, list], streets, street_ids) -> int:
    """A junction of the connected piece that carries the most street time."""
    component: dict[int, int] = {}
    for start in sorted(adjacency):
        if start in component:
            continue
        component[start] = start
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbour, _ in adjacency[node]:
                if neighbour not in component:
                    component[neighbour] = start
                    stack.append(neighbour)
    load: dict[int, float] = {}
    for street_id in street_ids:
        street = streets[street_id]
        root = component[street.a]
        weight = street.time if street.category == "M" else 0.0
        load[root] = load.get(root, 0.0) + weight + 1e-9
    return max(load, key=lambda root: (load[root], -root))


def _order_streets(streets, street_ids) -> list[int]:
    """Streets sorted from one end of the zone to the other.

    Double sweep: from a seed find the farthest junction ``a``, from ``a`` the
    farthest junction ``b``. A street's key is how much closer it is to ``a``
    than to ``b`` (midpoint of its two ends), so sorting by the key sweeps the
    zone from ``a`` towards ``b``. Streets in pieces not connected to ``a``
    (rare, small fragments) come last.
    """
    adjacency = _adjacency(streets, street_ids)
    seed = _seed(adjacency, streets, street_ids)
    end_a = _farthest(_dijkstra(adjacency, seed))
    from_a = _dijkstra(adjacency, end_a)
    end_b = _farthest(from_a)
    from_b = _dijkstra(adjacency, end_b)

    def key(street_id: int) -> tuple:
        street = streets[street_id]
        if street.a not in from_a:
            return (1, 0.0, street_id)
        side = ((from_a[street.a] + from_a[street.b])
                - (from_b[street.a] + from_b[street.b])) / 2
        return (0, side, street_id)

    return sorted(street_ids, key=key)


def _split_vehicles(instance: Instance, vehicle_ids: list[int]):
    """Deal vehicles out alternately, largest capacity first, so both halves
    get a similar mix of vehicle types."""
    ordered = sorted(vehicle_ids, key=lambda vid: (
        -VEHICLE_CAPACITIES[instance.vehicle_types[vid]], vid))
    return sorted(ordered[0::2]), sorted(ordered[1::2])


def _cut(ordered: list[int], weight, share: float) -> int:
    """Number of leading streets that gives the left half ``share`` of the
    total weight (0..len)."""
    total = sum(weight(sid) for sid in ordered)
    target = total * share
    running = 0.0
    best_index, best_error = 0, abs(target)
    for index, sid in enumerate(ordered, start=1):
        running += weight(sid)
        error = abs(running - target)
        if error < best_error:
            best_index, best_error = index, error
    return best_index


def _bisect(instance, streets, zone: Zone, zones: list[Zone],
            max_depth: int | None = None) -> None:
    # Base case: one vehicle, nothing left to divide, or deep enough.
    if (len(zone.vehicle_ids) == 1 or len(zone.street_ids) < 2
            or (max_depth is not None and zone.depth >= max_depth)):
        zones.append(zone)
        return

    left_vehicles, right_vehicles = _split_vehicles(instance, zone.vehicle_ids)
    shares = expected_shares(instance, streets, zone)
    ordered = _order_streets(streets, zone.street_ids)

    # One cut per requirement class: the left half takes exactly the share of
    # that class its vehicles are expected to clean. All cuts walk the same
    # a->b sweep, so both halves stay on their own side of the zone.
    left: list[int] = []
    right: list[int] = []
    classes: dict[int, list[int]] = {}
    for sid in ordered:
        street = streets[sid]
        group = street.requirement if street.category != "C" else 0
        classes.setdefault(group, []).append(sid)
    count_share = len(left_vehicles) / len(zone.vehicle_ids)
    for group, members in sorted(classes.items()):
        if group in shares and sum(shares[group].values()) > 0:
            share = (sum(shares[group].get(vid, 0.0) for vid in left_vehicles)
                     / sum(shares[group].values()))
            weight = (lambda sid: float(streets[sid].time)
                      if streets[sid].category == "M" else 0.0)
        else:
            # Connectors / optional-only classes: split by vehicle count
            # (optional ones only between vehicles able to clean them).
            able = [vid for vid in zone.vehicle_ids
                    if VEHICLE_CAPACITIES[instance.vehicle_types[vid]] >= group]
            share = (sum(vid in able for vid in left_vehicles) / len(able)
                     if able else count_share)
            weight = lambda sid: 1.0
        index = _cut(members, weight, share)
        left.extend(members[:index])
        right.extend(members[index:])

    _bisect(instance, streets, Zone(left_vehicles, sorted(left), zone.depth + 1),
            zones, max_depth)
    _bisect(instance, streets, Zone(right_vehicles, sorted(right), zone.depth + 1),
            zones, max_depth)


def partition(instance: Instance, max_depth: int | None = None) -> list[Zone]:
    """Divide the city into zones by recursive graph bisection.

    Without ``max_depth`` the recursion runs until every zone has one vehicle.
    With ``max_depth = d`` it stops after d levels, so a zone may be shared by
    several vehicles (``d = 0``: the whole city is one zone).
    Every street belongs to exactly one zone. Connector streets are included so
    the zones stay connected pieces of the street network.
    """
    streets = {street.id: street for street in instance.streets}
    root = Zone(list(range(instance.num_vehicles)),
                [street.id for street in instance.streets])
    zones: list[Zone] = []
    _bisect(instance, streets, root, zones, max_depth)
    return zones


def full_depth(instance: Instance) -> int:
    """Depth at which every zone has a single vehicle: ceil(log2 k)."""
    return max(0, (instance.num_vehicles - 1).bit_length())


# --------------------------------------------------------------------------
# Conquer: route every vehicle inside its zone
# --------------------------------------------------------------------------

class _ZoneSpace(SearchSpace):
    """SearchSpace whose targets are limited to the streets of one zone."""

    allowed: set | None = None
    optional_phase = False

    def restrict(self, allowed: set | None, optional_phase: bool) -> None:
        self.allowed = allowed
        self.optional_phase = optional_phase
        # The "nothing reachable from the depot" cache is per capacity only,
        # so it is no longer valid once the zone changes.
        self._exhausted.clear()

    def _accept(self, street, capacity, exclude) -> bool:
        if self.allowed is not None and street.id not in self.allowed:
            return False
        if self.optional_phase:
            return (street.category == "O" and capacity >= street.requirement
                    and street.id not in self.cleaned
                    and street.id not in exclude
                    and self.model.gain(street, capacity) > 0.0)
        return super()._accept(street, capacity, exclude)


def _route_zone(space: _ZoneSpace, routes, zone: Zone, optional: bool) -> None:
    """Conquer one zone with a greedy that never leaves the zone.

    Mandatory phase: requirement classes hardest first (30, 20, 10) so large
    vehicles are not used up on streets a small one could clean; the vehicle
    with the nearest next street moves. Optional phase: best score gain per
    second. A move is only offered while the vehicle can still get back to the
    depot in time (guaranteed by SearchSpace).
    """
    if optional:
        _route_level(space, routes, zone, set(zone.street_ids), 0, True)
        return
    if len(zone.vehicle_ids) == 1:
        # One vehicle: no class conflicts, just take the nearest street.
        _route_level(space, routes, zone, set(zone.street_ids), 0, False)
        return
    levels = sorted({space.streets_by_id[sid].requirement
                     for sid in zone.street_ids
                     if space.streets_by_id[sid].category == "M"}, reverse=True)
    for level in levels:
        allowed = {sid for sid in zone.street_ids
                   if space.streets_by_id[sid].requirement == level}
        _route_level(space, routes, zone, allowed, level, False)


def _route_level(space, routes, zone, allowed, level, optional) -> None:
    space.restrict(allowed, optional)
    fleet = [routes[vid] for vid in zone.vehicle_ids
             if routes[vid].capacity >= level]

    def best_move(route):
        moves = space.find_moves(route, width=4 if optional else 1)
        if not moves:
            return None
        if optional:
            return min(moves, key=lambda m: (-m.gain / m.time if m.time else 0.0,
                                             m.order_key()))
        return moves[0]

    def rank(move, route):
        first = ((-move.gain / move.time if move.time else 0.0) if optional
                 else move.approach)
        return (first, move.order_key(), route.vehicle_id)

    plan = {route.vehicle_id: best_move(route) for route in fleet}
    while True:
        winner = None
        for route in fleet:
            move = plan[route.vehicle_id]
            if move is not None:
                key = rank(move, route)
                if winner is None or key < winner[0]:
                    winner = (key, route, move)
        if winner is None:
            return
        _, route, move = winner
        space.commit(route, move)
        for other in fleet:
            planned = plan[other.vehicle_id]
            if other is route or (planned is not None
                                  and planned.street.id == move.street.id):
                plan[other.vehicle_id] = best_move(other)


# --------------------------------------------------------------------------
# Combine
# --------------------------------------------------------------------------

def build(instance: Instance, max_depth: int | None = None) -> Solution:
    """Divide into zones, conquer each zone, combine into one solution."""
    zones = partition(instance, max_depth)
    space = _ZoneSpace(instance)
    routes = space.new_routes()

    # Conquer: mandatory streets, zone by zone (zones are independent).
    for zone in zones:
        _route_zone(space, routes, zone, optional=False)

    # Combine 1: mandatory streets a zone could not finish go to any vehicle
    # with time left, wherever its zone is (one city-wide greedy pass over the
    # leftovers, then a street-by-street repair for anything still open).
    city = Zone(list(range(instance.num_vehicles)),
                [street.id for street in instance.streets])
    if space.mandatory_pending:
        _route_zone(space, routes, city, optional=False)
    if space.mandatory_pending:
        space.restrict(None, False)
        failures = space.repair_mandatory(routes)
        if failures:
            raise GreedyAssignmentError(
                failures[0], Solution(routes),
                [f"{len(failures)} mandatory streets could not be assigned "
                 f"with {len(zones)} zones (depth {max_depth}): "
                 f"{failures[:20]}"])

    # Combine 2: spare time goes to optional streets, first in the vehicle's
    # own zone, then anywhere in the city.
    for zone in zones:
        _route_zone(space, routes, zone, optional=True)
    _route_zone(space, routes, city, optional=True)

    # Combine 3: return to depot, clean what the routes already drive over.
    space.restrict(None, False)
    for route in routes:
        space.close(route)
    space.sweep_traversed(routes)
    return Solution(routes)


def solve(instance: Instance, max_depth: int | None = None,
          **_ignored) -> Solution:
    """Try zone depths from finest (one vehicle per zone) to coarsest.

    Finer zones mean shorter routes but no help between neighbours; if a depth
    cannot finish every mandatory street, sibling zones are merged by trying
    one level less. Small instances try every depth and keep the best score;
    large ones stop at the first valid depth.
    """
    depths = ([max_depth] if max_depth is not None
              else list(range(full_depth(instance), -1, -1)))
    exhaustive = instance.num_streets <= 5_000
    best, failure = None, None
    for depth in depths:
        try:
            solution = build(instance, depth)
        except ValueError as exc:
            failure = exc
            continue
        if validate_solution(instance, solution):
            continue
        score = calculate_score(instance, solution).score
        if best is None or score > best[0]:
            best = (score, solution)
        if not exhaustive:
            break
    if best is None:
        if failure is not None:
            raise failure
        raise ValueError("divide and conquer produced no valid solution")
    return best[1]


def zone_report(instance: Instance, zones: list[Zone]) -> list[dict]:
    """Per-zone summary (vehicles, streets, mandatory workload) for reports."""
    streets = {street.id: street for street in instance.streets}
    rows = []
    for index, zone in enumerate(zones):
        mandatory = [streets[sid] for sid in zone.street_ids
                     if streets[sid].category == "M"]
        rows.append({
            "zone": index,
            "depth": zone.depth,
            "vehicles": [f"{vid}:{instance.vehicle_types[vid]}"
                         for vid in zone.vehicle_ids],
            "streets": len(zone.street_ids),
            "mandatory": len(mandatory),
            "mandatory_time": sum(s.time for s in mandatory),
        })
    return rows
