"""Recursive route construction. See docs/recursive.md."""

import sys

from .parser import Instance
from .search import SearchSpace
from .solver import Solution


def _raise_recursion_limit(instance: Instance) -> None:
    needed = 10_000 + 4 * instance.num_streets
    if sys.getrecursionlimit() < needed:
        sys.setrecursionlimit(min(needed, 2_000_000))


def _nearest(space: SearchSpace, route) -> list:
    return space.find_moves(route, width=1)


def _extend(space: SearchSpace, route, candidates) -> float:
    for move in candidates(space, route):
        token = space.commit(route, move)
        gained = token.gain + _extend(space, route, candidates)
        if gained > 0.0 or token.forced:
            return gained
        space.rollback(route, token)
    return 0.0


def build_solution(space: SearchSpace, candidates, routes=None) -> Solution:
    routes = space.new_routes() if routes is None else routes
    order = sorted(routes, key=lambda route: (route.capacity, route.vehicle_id))

    for route in order:
        _extend(space, route, candidates)
        if not space.mandatory_pending:
            break
    if space.mandatory_pending:
        failures = space.repair_mandatory(order)
        if failures:
            raise ValueError(
                f"{len(failures)} mandatory streets could not be assigned: "
                f"{failures[:20]}{'...' if len(failures) > 20 else ''}")

    for route in routes:
        space.close(route)
    space.sweep_traversed(order)
    return Solution(routes)


def solve(instance: Instance, probe_radius: int | None = None,
          **_ignored) -> Solution:
    _raise_recursion_limit(instance)
    space = SearchSpace(instance, probe_radius=probe_radius)
    return build_solution(space, _nearest)
