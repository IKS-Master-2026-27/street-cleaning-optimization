"""Route construction from Split segments and the optimal cleaning assignment.

Lemma 1: once every vehicle's movement is fixed, choosing for each traversed
street the vehicle with the largest delta (mandatory: always; optional: only if
delta > 0) maximises the score, because the score is a sum of independent
per-street terms (1 - alpha) + sum delta(j, q_j).
"""

from .distances import Oracle
from .io import Problem
from .objective import Route
from .split import Segment, SplitData, vehicles_for
from .tour import Tour, end, start


def route_from_tasks(problem: Problem, oracle: Oracle, vehicle: int, tasks: list[int],
                     tour: Tour | None = None, first_index: int = 0) -> Route:
    """depot -> tasks (in order, connected by shortest paths) -> depot.

    When the tasks are a contiguous slice of `tour` starting at `first_index`, the
    tour's cached leg paths are reused.
    """
    capacity = problem.capacities[vehicle]
    if not tasks:
        return Route(vehicle, capacity, [problem.depot], [], [])
    nodes, streets = oracle.path(problem.depot, start(problem, tasks[0]))
    nodes, streets = list(nodes), list(streets)
    for k, oid in enumerate(tasks):
        nodes.append(end(problem, oid))
        streets.append(oid >> 1)
        if k + 1 < len(tasks):
            if tour is not None:
                leg_nodes, leg_streets = tour.leg_path(problem, oracle, first_index + k)
            else:
                leg_nodes, leg_streets = oracle.path(end(problem, oid), start(problem, tasks[k + 1]))
            nodes.extend(leg_nodes[1:])
            streets.extend(leg_streets)
    back_nodes, back_streets = oracle.path_to_depot(end(problem, tasks[-1]))
    nodes.extend(back_nodes[1:])
    streets.extend(back_streets)
    return Route(vehicle, capacity, nodes, streets, [])


def routes_from_segments(problem: Problem, oracle: Oracle,
                         parts: list[tuple[SplitData, list[Segment]]]
                         ) -> tuple[list[Route], list[list[int]]]:
    """Materialise Split segments (possibly of several tours) as routes.

    Also returns each vehicle's ordered service list."""
    routes = [Route(v, problem.capacities[v], [problem.depot], [], [])
              for v in range(problem.num_vehicles)]
    services: list[list[int]] = [[] for _ in range(problem.num_vehicles)]
    all_segments = [(data, seg) for data, segs in parts for seg in segs]
    vehicles = vehicles_for(problem, [seg for _, seg in all_segments])
    for (data, seg), (vehicle, _) in zip(all_segments, vehicles):
        tasks = data.tour.tasks[seg.first:seg.last + 1]
        routes[vehicle] = route_from_tasks(problem, oracle, vehicle, tasks, data.tour, seg.first)
        services[vehicle] = tasks
    return routes, services


def assign_cleaning(problem: Problem, routes: list[Route]) -> list[str]:
    """Optimal cleaning assignment (Lemma 1). Overwrites route.cleaned.

    Returns a list of problems (mandatory streets nobody can clean)."""
    best: dict[int, tuple[float, int]] = {}
    for v, route in enumerate(routes):
        q = route.capacity
        for j in set(route.streets):
            d = problem.delta(j, q)
            if d is None:
                continue
            current = best.get(j)
            # tie-break: lower capacity, then lower vehicle id (deterministic)
            if current is None or (d, -q, -v) > (current[0], -routes[current[1]].capacity, -current[1]):
                best[j] = (d, v)
    for route in routes:
        route.cleaned = []
    for j, (d, v) in sorted(best.items()):
        if problem.category[j] == "M" or d > 0:
            routes[v].cleaned.append(j)
    missing = [j for j in range(problem.num_streets)
               if problem.category[j] == "M" and j not in best]
    return [f"mandatory street {j} not traversed by a capable vehicle" for j in missing]


def fill_idle_vehicles(problem: Problem, oracle: Oracle, routes: list[Route]) -> None:
    """Give vehicles without any move the cheapest depot -> x -> depot loop, so that
    every route has n >= 1 steps as the official format requires."""
    best = None
    for v_next, t, j in oracle.net.out[problem.depot]:
        back = oracle.to_depot[0][v_next]
        total = t + back
        if total <= problem.time_limit and (best is None or total < best[0]):
            best = (total, v_next, j)
    if best is None:
        return
    _, x, j = best
    for route in routes:
        if not route.streets:
            back_nodes, back_streets = oracle.path_to_depot(x)
            route.nodes = [problem.depot] + back_nodes
            route.streets = [j] + back_streets
