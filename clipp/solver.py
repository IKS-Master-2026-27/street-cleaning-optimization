
from dataclasses import dataclass, field
from heapq import heappop, heappush

from .graph import Adjacency, Edge, build_graph, shortest_path
from .parser import Instance, Street
from .preprocessing import (
    PreprocessedGraph,
    candidate_junctions,
    preprocess_graph,
    precompute_water_waste,
)

VEHICLE_CAPACITIES = {"S": 10, "M": 20, "L": 30}
INF = 1 << 62


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
    def __init__(
        self,
        street_id: int,
        partial_solution: Solution,
        reasons: list[str],
    ) -> None:
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


def _search(
    graph: Adjacency,
    source: int,
    total_time: int,
    index: dict[int, list[int]],
    streets_by_id: dict[int, Street],
    dist_depot: dict[int, int],
    max_time: int,
    min_street_time: int,
    preprocessed: PreprocessedGraph | None = None,
    candidate_nodes: list[int] | None = None,
):
    # Fast path: reuse shortest-path information computed in preprocessing.
    if preprocessed is not None:
        n = preprocessed.num_junctions
        row = preprocessed.offset(source)
        best = None

        nodes_to_check = (
            candidate_nodes if candidate_nodes is not None else range(n)
        )

        for junction in nodes_to_check:
            elapsed = preprocessed.distances[row + junction]

            if elapsed == INF:
                continue

            bucket = index.get(junction)

            if not bucket:
                continue

            for street_id in bucket:
                street = streets_by_id[street_id]

                # _entry_index only contains valid entry endpoints.
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

        if best is None:
            return None

        (incremental, _, _, _), street, start, end, approach = best

        junctions = [start]
        street_ids: list[int] = []
        node = start

        while node != source:
            offset = row + node
            parent = preprocessed.previous_junction[offset]
            traversed = preprocessed.previous_street[offset]

            if parent < 0 or traversed < 0:
                return None

            junctions.append(parent)
            street_ids.append(traversed)
            node = parent

        return (
            incremental,
            street,
            start,
            end,
            approach,
            junctions[::-1],
            street_ids[::-1],
        )

    # Fallback for large graphs: use on-demand Dijkstra.
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
                previous[edge.destination] = (
                    junction,
                    edge.street_id,
                )
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

    return (
        incremental,
        street,
        start,
        end,
        approach,
        junctions[::-1],
        street_ids[::-1],
    )


def _candidate_for(
    route: VehicleRoute,
    memo: dict,
    graph: Adjacency,
    index: dict[int, list[int]],
    streets_by_id: dict[int, Street],
    dist_depot: dict[int, int],
    max_time: int,
    min_street_time: int,
    water_waste_costs,
    num_vehicles: int,
    preprocessed: PreprocessedGraph | None = None,
    candidate_nodes: list[int] | None = None,
    strategy: str = "time",
):
    shared = (route.current_junction, route.total_time)

    if shared not in memo:
        memo[shared] = _search(
            graph,
            route.current_junction,
            route.total_time,
            index,
            streets_by_id,
            dist_depot,
            max_time,
            min_street_time,
            preprocessed,
            candidate_nodes,
        )

    found = memo[shared]

    if found is None:
        return None

    (
        incremental,
        street,
        start,
        end,
        approach,
        junctions,
        street_ids,
    ) = found

    water_cost = water_waste_costs[street.id * num_vehicles + route.vehicle_id]

    # Both strategies retain feasibility checks in _search.
    if strategy == "water":
        key = (water_cost, incremental, street.id, route.vehicle_id, start, end)
    else:
        key = (incremental, water_cost, street.id, route.vehicle_id, start, end)

    return (
        key,
        street,
        start,
        end,
        approach,
        junctions,
        street_ids,
    )


def _solve_once(instance: Instance, strategy: str = "time") -> Solution:
    graph = build_graph(instance)

    # Precompute shortest paths and candidate water-waste costs.
    preprocessed = preprocess_graph(graph)
    dist_depot = depot_return_times(instance)

    water_waste_costs = precompute_water_waste(
        instance.streets,
        instance.vehicle_types,
    )

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

    streets_by_id = {
        street.id: street for street in instance.streets
    }

    mandatory = sorted(
        (
            street
            for street in instance.streets
            if street.category == "M"
        ),
        key=lambda street: (-street.requirement, street.id),
    )

    for requirement in sorted(
        {street.requirement for street in mandatory},
        reverse=True,
    ):
        level = [
            street
            for street in mandatory
            if street.requirement == requirement
        ]

        pending = {street.id for street in level}
        index = _entry_index(level)
        candidate_nodes = candidate_junctions(
            level,
            instance.num_junctions,
        )

        min_street_time = min(street.time for street in level)

        eligible = [
            route
            for route in routes
            if route.capacity >= requirement
        ]

        memo: dict = {}
        best = {}

        for route in eligible:
            best[route.vehicle_id] = _candidate_for(
                route,
                memo,
                graph,
                index,
                streets_by_id,
                dist_depot,
                instance.max_time,
                min_street_time,
                water_waste_costs,
                len(instance.vehicle_types),
                preprocessed,
                candidate_nodes,
                strategy,
            )

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
                    remaining[0],
                    Solution(routes),
                    [
                        (
                            f"No feasible candidate in requirement "
                            f"{requirement}; {len(remaining)} streets left: "
                            f"{remaining[:20]}"
                            f"{'...' if len(remaining) > 20 else ''}"
                        ),
                        (
                            f"All {len(eligible)} vehicles with capacity "
                            f">= {requirement} are time-exhausted."
                        ),
                    ],
                )

            (
                _,
                street,
                _,
                end,
                approach,
                junctions,
                street_ids,
            ), route = winner

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

                if (
                    other.vehicle_id == route.vehicle_id
                    or (
                        entry is not None
                        and entry[1].id == street.id
                    )
                ):
                    best[other.vehicle_id] = _candidate_for(
                        other,
                        memo,
                        graph,
                        index,
                        streets_by_id,
                        dist_depot,
                        instance.max_time,
                        min_street_time,
                        water_waste_costs,
                        len(instance.vehicle_types),
                        preprocessed,
                        candidate_nodes,
                        strategy,
                    )

    # Return every vehicle to the depot.
    for route in routes:
        if route.current_junction == instance.depot:
            continue

        home = shortest_path(
            graph,
            route.current_junction,
            instance.depot,
        )

        if home is None:
            raise ValueError(
                f"Vehicle {route.vehicle_id} cannot return to depot"
            )

        route.junctions.extend(home.junctions[1:])
        route.street_ids.extend(home.street_ids)
        route.total_time += home.total_time
        route.current_junction = instance.depot

    # Clean optional streets that the routes have already traversed.
    cleaned = {
        street_id
        for route in routes
        for street_id in route.cleaned_street_ids
    }

    for route in sorted(
        routes,
        key=lambda item: (item.capacity, item.vehicle_id),
    ):
        for street_id in sorted(set(route.street_ids)):
            street = streets_by_id[street_id]

            if (
                street.category == "O"
                and route.capacity >= street.requirement
                and street_id not in cleaned
            ):
                route.cleaned_street_ids.append(street_id)
                cleaned.add(street_id)

    return Solution(routes)


def _improve_optional_detours(instance: Instance, solution: Solution) -> Solution:
    """Add score-positive depot-to-optional-street-to-depot trips.

    Run only on small/medium inputs. Every accepted trip explicitly traverses
    the optional street in its permitted direction and respects max_time.
    """
    from .scoring import calculate_score

    if len(instance.streets) > 600:
        return solution

    graph = build_graph(instance)
    depot = instance.depot
    optional = [s for s in instance.streets if s.category == "O"]
    if not optional:
        return solution

    already = {sid for r in solution.routes for sid in r.cleaned_street_ids}
    current_score = calculate_score(instance, solution).score

    # Search only a limited shortlist per vehicle to keep runtime predictable.
    for route in solution.routes:
        remaining = instance.max_time - route.total_time
        if remaining <= 0:
            continue

        candidates = []
        for street in optional:
            if street.id in already or street.requirement > route.capacity:
                continue
            # Higher length offers more coverage; smaller water waste is better.
            waste = (route.capacity - street.requirement) * street.length / 1000
            candidates.append((-street.length / (1 + waste), street.id, street))
        candidates.sort(key=lambda x: (x[0], x[1]))

        best_trip = None
        best_score = current_score
        for _, _, street in candidates[:40]:
            orientations = [(street.a, street.b)]
            if street.direction == 2 and street.a != street.b:
                orientations.append((street.b, street.a))
            for start, end in orientations:
                outward = shortest_path(graph, depot, start)
                if outward is None:
                    continue
                home = shortest_path(graph, end, depot)
                if home is None:
                    continue
                added_time = outward.total_time + street.time + home.total_time
                if added_time > remaining:
                    continue

                # Temporarily append the actual route and evaluate real score.
                old_j, old_s, old_c, old_time = (
                    len(route.junctions), len(route.street_ids),
                    len(route.cleaned_street_ids), route.total_time
                )
                route.junctions.extend(outward.junctions[1:])
                route.junctions.append(end)
                route.junctions.extend(home.junctions[1:])
                route.street_ids.extend(outward.street_ids)
                route.street_ids.append(street.id)
                route.street_ids.extend(home.street_ids)
                route.cleaned_street_ids.append(street.id)
                route.total_time += added_time
                try:
                    trial_score = calculate_score(instance, solution).score
                finally:
                    del route.junctions[old_j:]
                    del route.street_ids[old_s:]
                    del route.cleaned_street_ids[old_c:]
                    route.total_time = old_time

                if trial_score > best_score + 1e-12:
                    best_score = trial_score
                    best_trip = (street, end, outward, home, added_time)

        if best_trip is not None:
            street, end, outward, home, added_time = best_trip
            route.junctions.extend(outward.junctions[1:])
            route.junctions.append(end)
            route.junctions.extend(home.junctions[1:])
            route.street_ids.extend(outward.street_ids)
            route.street_ids.append(street.id)
            route.street_ids.extend(home.street_ids)
            route.cleaned_street_ids.append(street.id)
            route.total_time += added_time
            already.add(street.id)
            current_score = best_score

    return solution


def solve(instance: Instance) -> Solution:
    """Keep the valid baseline, and accept a water-aware run only if its score improves.

    The extra strategy is limited to moderately sized inputs to avoid doubling
    runtime for very large city graphs. No hash tables or heaps are used by
    preprocessing.py; the original solver's fallback remains unchanged.
    """
    baseline = _solve_once(instance, "time")
    if len(instance.streets) > 1500:
        return baseline

    from .scoring import calculate_score
    best = baseline
    best_score = calculate_score(instance, baseline).score
    try:
        alternative = _solve_once(instance, "water")
        alternative_score = calculate_score(instance, alternative).score
        if alternative_score > best_score:
            best = alternative
    except (GreedyAssignmentError, ValueError):
        pass
    return _improve_optional_detours(instance, best)
