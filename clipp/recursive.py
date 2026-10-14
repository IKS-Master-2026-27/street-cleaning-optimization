"""Recursive route construction. See docs/recursive.md."""

import sys

from .parser import Instance
from .search import MANDATORY, OPTIONAL, SearchSpace
from .solver import Solution


def _raise_recursion_limit(instance: Instance) -> None:
    needed = 10_000 + 4 * instance.num_streets
    if sys.getrecursionlimit() < needed:
        sys.setrecursionlimit(min(needed, 2_000_000))


def _nearest(space: SearchSpace, route, phase: str, exact: bool) -> list:
    return space.find_moves(route, phase, exact, width=1)


def _extend(space: SearchSpace, route, phase: str, exact: bool,
            candidates) -> float:
    for move in candidates(space, route, phase, exact):
        token = space.commit(route, move, exact)
        gained = token.gain + _extend(space, route, phase, exact, candidates)
        if gained > 0.0 or token.forced:
            return gained
        space.rollback(route, token)
    return 0.0


def build_solution(space: SearchSpace, candidates, routes=None,
                   optional_phase: bool = True) -> Solution:
    routes = space.new_routes() if routes is None else routes
    order = sorted(routes, key=lambda route: (route.capacity, route.vehicle_id))
    tiers = space.tiers()

    for exact in tiers:
        if not space.mandatory_pending:
            break
        for route in order:
            _extend(space, route, MANDATORY, exact, candidates)
            if not space.mandatory_pending:
                break
    if space.mandatory_pending:
        failures = space.repair_mandatory(order)
        if failures:
            raise ValueError(
                f"{len(failures)} mandatory streets could not be assigned: "
                f"{failures[:20]}{'...' if len(failures) > 20 else ''}")

    if optional_phase:
        for exact in tiers:
            for route in order:
                if space.expired():
                    break
                _extend(space, route, OPTIONAL, exact, candidates)

    for route in routes:
        space.close(route)
    space.sweep_traversed(order)
    return Solution(routes)


def solve(instance: Instance, probe_radius: int | None = None,
          deadline: float | None = None, enhanced: bool = False,
          **_ignored) -> Solution:
    # Without `enhanced` the cleaning rules are the greedy baseline's, so only
    # the search strategy differs; with it the solver also cleans the streets it
    # drives over, matches capacity to requirement and spends the leftover fleet
    # time on optional streets.
    _raise_recursion_limit(instance)
    space = SearchSpace(instance, probe_radius=probe_radius, deadline=deadline,
                        tiers=None if enhanced else (False,),
                        opportunistic=enhanced)
    return build_solution(space, _nearest, optional_phase=enhanced)
