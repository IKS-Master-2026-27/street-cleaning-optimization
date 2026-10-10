from dataclasses import dataclass, field
from heapq import heappop, heappush

from .graph import Adjacency, Edge, build_graph, shortest_path
from .parser import Instance, Street

VEHICLE_CAPACITIES = {"S": 10, "M": 20, "L": 30}


@dataclass
class VehicleRoute:
    vehicle_id: int
    vehicle_type: str
    capacity: int
    current_junction: int
    junctions: list[int]
    total_time: int = 0
    street_ids: list[int] = field(default_factory=list)
    cleaned_street_ids: list[int] = field(default_factory=list)


@dataclass
class Solution:
    routes: list[VehicleRoute]


class GreedyAssignmentError(ValueError):

    def __init__(self, street_id: int, partial_solution: Solution,
                 reasons: list[str]) -> None:
        super().__init__(
            f"Greedy assignment failed for mandatory street {street_id}: "
            "no feasible vehicle and orientation"
        )
        self.street_id = street_id
        self.partial_solution = partial_solution
        self.reasons = reasons


def build_reverse_graph(instance: Instance) -> Adjacency:

    graph: Adjacency = [[] for _ in range(instance.num_junctions)]
    for street in instance.streets:
        graph[street.b].append(Edge(street.a, street.id, street.time))
        if street.direction == 2:
            graph[street.a].append(Edge(street.b, street.id, street.time))
    return graph


def depot_return_times(instance: Instance) -> dict[int, int]:

    graph = build_reverse_graph(instance)
    distances = {instance.depot: 0}
    queue = [(0, instance.depot)]
    while queue:
        elapsed, junction = heappop(queue)
        if elapsed != distances[junction]:
            continue
        for edge in graph[junction]:
            candidate = elapsed + edge.time
            best = distances.get(edge.destination)
            if best is None or candidate < best:
                distances[edge.destination] = candidate
                heappush(queue, (candidate, edge.destination))
    return distances


def _entry_index(level: list[Street]) -> dict[int, list[int]]:

    index: dict[int, list[int]] = {}
    for street in level:
        index.setdefault(street.a, []).append(street.id)
        if street.direction == 2 and street.b != street.a:
            index.setdefault(street.b, []).append(street.id)
    return index


def _drop_from_index(index: dict[int, list[int]], street: Street) -> None:

    for node in (street.a, street.b):
        bucket = index.get(node)
        if bucket is not None and street.id in bucket:
            bucket.remove(street.id)
            if not bucket:
                del index[node]


def _search(graph: Adjacency, source: int, total_time: int,
            index: dict[int, list[int]], streets_by_id: dict[int, Street],
            dist_depot: dict[int, int], max_time: int, min_street_time: int):

    distances = {source: 0}
    previous: dict[int, tuple[int, int]] = {}
    queue = [(0, source)]
    best = None

    while queue:
        elapsed, junction = heappop(queue)
        if elapsed != distances[junction]:
            continue

        if best is not None and elapsed + min_street_time > best[0][0]:
            break

        bucket = index.get(junction)
        if bucket:
            for street_id in bucket:
                street = streets_by_id[street_id]
                end = street.b if street.a == junction else street.a
                return_time = dist_depot.get(end)
                if return_time is None:
                    continue
                incremental = elapsed + street.time
                if total_time + incremental + return_time > max_time:
                    continue
                key = (incremental, street.id, junction, end)
                if best is None or key < best[0]:
                    best = (key, street, junction, end, elapsed)

        for edge in graph[junction]:
            candidate = elapsed + edge.time
            known = distances.get(edge.destination)
            if known is None or candidate < known:
                distances[edge.destination] = candidate
                previous[edge.destination] = (junction, edge.street_id)
                heappush(queue, (candidate, edge.destination))

    if best is None:
        return None
    (incremental, _, _, _), street, start, end, approach = best
    junctions = [start]
    street_ids: list[int] = []
    node = start
    while node != source:
        node, traversed = previous[node]
        junctions.append(node)
        street_ids.append(traversed)
    return (incremental, street, start, end, approach,
            junctions[::-1], street_ids[::-1])


def _candidate_for(route: VehicleRoute, memo: dict, graph: Adjacency,
                   index: dict[int, list[int]],
                   streets_by_id: dict[int, Street],
                   dist_depot: dict[int, int], max_time: int,
                   min_street_time: int):

    shared = (route.current_junction, route.total_time)
    if shared not in memo:
        memo[shared] = _search(graph, route.current_junction, route.total_time,
                               index, streets_by_id, dist_depot, max_time,
                               min_street_time)
    found = memo[shared]
    if found is None:
        return None
    incremental, street, start, end, approach, junctions, street_ids = found
    key = (incremental, street.id, route.vehicle_id, start, end)
    return key, street, start, end, approach, junctions, street_ids


def solve(instance: Instance) -> Solution:

    graph = build_graph(instance)
    dist_depot = depot_return_times(instance)

    routes = [
        VehicleRoute(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            capacity=VEHICLE_CAPACITIES[vehicle_type],
            current_junction=instance.depot,
            junctions=[instance.depot],
        )
        for vehicle_id, vehicle_type in enumerate(instance.vehicle_types)
    ]
    streets_by_id = {street.id: street for street in instance.streets}
    mandatory = sorted(
        (street for street in instance.streets if street.category == "M"),
        key=lambda street: (-street.requirement, street.id),
    )

    for requirement in sorted({s.requirement for s in mandatory}, reverse=True):
        level = [s for s in mandatory if s.requirement == requirement]
        pending = {s.id for s in level}
        index = _entry_index(level)

        min_street_time = min(s.time for s in level)
        eligible = [r for r in routes if r.capacity >= requirement]

        memo: dict = {}
        best = {}
        for route in eligible:
            best[route.vehicle_id] = _candidate_for(
                route, memo, graph, index, streets_by_id, dist_depot,
                instance.max_time, min_street_time)

        while pending:
            winner = None
            for route in eligible:
                entry = best[route.vehicle_id]
                if entry is None:
                    continue
                if winner is None or entry[0] < winner[0][0]:
                    winner = (entry, route)

            if winner is None:
                remaining = sorted(pending)
                raise GreedyAssignmentError(
                    remaining[0], Solution(routes),
                    [f"No feasible candidate in requirement {requirement}; "
                     f"{len(remaining)} streets left: {remaining[:20]}"
                     f"{'...' if len(remaining) > 20 else ''}",
                     f"All {len(eligible)} vehicles with capacity >= "
                     f"{requirement} are time-exhausted."])

            (_, street, _, end, approach, junctions, street_ids), route = winner

            route.junctions.extend(junctions[1:])
            route.street_ids.extend(street_ids)
            route.junctions.append(end)
            route.street_ids.append(street.id)
            route.total_time += approach + street.time
            route.current_junction = end
            route.cleaned_street_ids.append(street.id)
            pending.discard(street.id)
            _drop_from_index(index, street)

            memo = {}
            for other in eligible:
                entry = best[other.vehicle_id]
                if other.vehicle_id == route.vehicle_id or (
                        entry is not None and entry[1].id == street.id):
                    best[other.vehicle_id] = _candidate_for(
                        other, memo, graph, index, streets_by_id, dist_depot,
                        instance.max_time, min_street_time)

    for route in routes:
        if route.current_junction == instance.depot:
            continue
        home = shortest_path(graph, route.current_junction, instance.depot)
        if home is None:
            raise ValueError(f"Vehicle {route.vehicle_id} cannot return to depot")
        route.junctions.extend(home.junctions[1:])
        route.street_ids.extend(home.street_ids)
        route.total_time += home.total_time
        route.current_junction = instance.depot

    cleaned = {street_id for route in routes for street_id in route.cleaned_street_ids}
    for route in sorted(routes, key=lambda route: (route.capacity, route.vehicle_id)):
        for street_id in sorted(set(route.street_ids)):
            street = streets_by_id[street_id]
            if (street.category == "O" and route.capacity >= street.requirement
                    and street_id not in cleaned):
                route.cleaned_street_ids.append(street_id)
                cleaned.add(street_id)

    return Solution(routes)