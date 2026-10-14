"""Recursive route construction with enumeration. See docs/recursive.md."""

from functools import partial

from .parser import Instance
from .recursive import _raise_recursion_limit, build_solution
from .scoring import calculate_score
from .search import SearchSpace
from .solver import Solution
from .validator import validate_solution


def ladder(instance: Instance, width: int | None = None,
           lookahead: int | None = None) -> list:
    if width is not None or lookahead is not None:
        return [(max(1, width or 1), max(1, lookahead or 1), None)]
    streets = instance.num_streets
    if streets <= 1_500:
        return [(1, 1, (False,)), (1, 1, (True, False)),
                (3, 2, None), (5, 3, None)]
    if streets <= 60_000:
        return [(1, 1, None), (3, 2, None)]
    return [(1, 1, None), (3, 1, None)]


def _lookahead(space: SearchSpace, junction: int, capacity: int, elapsed: int,
               phase: str, exact: bool, width: int, depth: int,
               exclude) -> tuple:
    if depth <= 0:
        return 0.0, 0
    best = (0.0, 0)
    best_density = 0.0
    for move in space.probe(junction, capacity, elapsed, phase, exact, width,
                            exclude):
        sub_value, sub_time = _lookahead(
            space, move.exit, capacity, elapsed + move.time, phase, exact,
            width, depth - 1, exclude | {move.street.id})
        value = move.value + sub_value
        total = move.time + sub_time
        density = value / total if total else 0.0
        if density > best_density:
            best_density, best = density, (value, total)
    return best


def _enumerated(space: SearchSpace, route, phase: str, exact: bool, width: int,
                lookahead: int) -> list:
    moves = space.find_moves(route, phase, exact, width=width)
    if len(moves) <= 1:
        return moves
    ranked = []
    for move in moves:
        sub_value, sub_time = _lookahead(
            space, move.exit, route.capacity, route.total_time + move.time,
            phase, exact, width, lookahead - 1, frozenset([move.street.id]))
        value = move.value + sub_value
        total = move.time + sub_time
        density = value / total if total else 0.0
        ranked.append((-density, move.order_key(), move))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]


def solve(instance: Instance, width: int | None = None,
          lookahead: int | None = None, probe_radius: int | None = None,
          deadline: float | None = None, enhanced: bool = False,
          **_ignored) -> Solution:
    # See clipp.recursive.solve for what `enhanced` switches on.
    _raise_recursion_limit(instance)
    best = None
    failures = []
    for enumerated_width, depth, tiers in ladder(instance, width, lookahead):
        space = SearchSpace(instance, probe_radius=probe_radius,
                            deadline=deadline,
                            tiers=tiers if enhanced else (False,),
                            opportunistic=enhanced)
        candidates = partial(_enumerated, width=enumerated_width,
                             lookahead=depth)
        label = f"width={enumerated_width} lookahead={depth} tiers={tiers}"
        try:
            solution = build_solution(space, candidates,
                                      optional_phase=enhanced)
        except ValueError as exc:
            failures.append(f"{label}: {exc}")
            continue
        errors = validate_solution(instance, solution)
        if errors:
            failures.append(f"{label}: {errors[0]}")
            continue
        score = calculate_score(instance, solution).score
        if best is None or score > best[0]:
            best = (score, solution)
    if best is None:
        raise ValueError("no enumeration budget produced a valid solution: "
                         + "; ".join(failures))
    return best[1]
