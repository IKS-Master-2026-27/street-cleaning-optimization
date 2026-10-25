"""Solution A: giant tour + Selective Split DP + optimal assignment + knapsack DP.

Two modes, chosen by instance size:
  * ordered mode (small/medium): fleet sorted by capacity (L, M, S) and a giant
    tour over all useful streets; split_ordered decides route boundaries and
    which optional tasks to drop. Two deterministic tours are tried (one ordered
    by requirement class, one purely nearest-neighbour) and the best is kept.
  * class mode (large): every street is assigned to the smallest vehicle type
    that can clean it (zero avoidable waste), one tour per class, and
    split_min_routes covers each class tour with the fewest vehicles; if a class
    lacks vehicles, split_ordered selects the most valuable subset.
"""

import time
from dataclasses import dataclass

from .assignment import assign_cleaning, fill_idle_vehicles, routes_from_segments
from ..solver import Solution
from .distances import Oracle
from .io import Problem, problem_from_instance
from .knapsack import fill_spare_time
from .objective import Evaluation, Route, evaluate, to_repo_solution
from .split import NEG, Segment, SplitData, split_min_routes, split_ordered
from .tour import Selection, Tour, build_tour, class_of, concatenate, select_streets

DENSE_LIMIT = 2000          # junctions; dense distance rows are cached below this
ORDERED_CELLS = 3_000_000   # max n * C for the fleet-ordered split


@dataclass
class Result:
    routes: list[Route]
    evaluation: Evaluation
    services: list[list[int]]
    log: list[str]
    seconds: float


def _class_tours(problem: Problem, oracle: Oracle, selection: Selection, dense: bool,
                 classes_desc: bool = True) -> dict[int, Tour]:
    groups: dict[int, list[int]] = {}
    for j in selection.mandatory + selection.optional:
        groups.setdefault(class_of(problem, j), []).append(j)
    order = sorted(groups, reverse=classes_desc)
    return {q: build_tour(problem, oracle, groups[q], dense) for q in order}


def plan_ordered(problem: Problem, oracle: Oracle, tour: Tour):
    data = SplitData(problem, oracle, tour)
    caps = sorted(problem.capacities, reverse=True)
    value, segments = split_ordered(data, caps)
    return value, [(data, segments)]


def plan_by_class(problem: Problem, oracle: Oracle, tours: dict[int, Tour], log: list[str],
                  selection: Selection | None = None, dense: bool = False):
    parts = []
    total = 0.0
    counts: dict[int, int] = {}
    for q in problem.capacities:
        counts[q] = counts.get(q, 0) + 1
    for q, tour in tours.items():
        data = SplitData(problem, oracle, tour)
        segments = split_min_routes(data, q)
        if segments is not None and len(segments) <= counts.get(q, 0):
            log.append(f"class {q}: {len(tour)} tasks covered by {len(segments)}/{counts[q]} vehicles")
            value = data.values(q)[data.n]
        else:
            fleet = [q] * counts.get(q, 0)
            value, segments = split_ordered(data, fleet)
            log.append(f"class {q}: fleet short, selective split value {value:.6f}")
            if selection is not None:
                # A route must serve every task of its segment, so optional tasks lying
                # between mandatory ones can make the mixed tour uncoverable. A tour with
                # the class's mandatory streets first and its optional streets after lets
                # the Split DP cover the mandatory part and spend the remaining vehicles
                # on optional streets; keep whichever plan is better.
                mandatory = [j for j in selection.mandatory if class_of(problem, j) == q]
                optional = [j for j in selection.optional if class_of(problem, j) == q]
                first = concatenate(problem, oracle, [build_tour(problem, oracle, mandatory, dense),
                                                      build_tour(problem, oracle, optional, dense)])
                first_data = SplitData(problem, oracle, first)
                first_value, first_segments = split_ordered(first_data, fleet)
                log.append(f"class {q}: mandatory-first tour, selective split value {first_value:.6f}")
                if first_value > value:
                    data, value, segments = first_data, first_value, first_segments
            if value == NEG:
                raise ValueError(f"class {q}: mandatory streets cannot be covered")
        total += value
        parts.append((data, segments))
    return total, parts


def finish(problem: Problem, oracle: Oracle, routes: list[Route], dense: bool,
           log: list[str]) -> Evaluation:
    issues = assign_cleaning(problem, routes)
    if issues:
        log.extend(issues[:5])
    if dense:
        added = fill_spare_time(problem, oracle, routes)
        log.append(f"knapsack DP added {added} optional streets")
        assign_cleaning(problem, routes)
    fill_idle_vehicles(problem, oracle, routes)
    return evaluate(problem, routes)


def solve_simple(problem: Problem, oracle: Oracle | None = None) -> Result:
    started = time.perf_counter()
    log: list[str] = []
    oracle = oracle or Oracle(problem)
    selection = select_streets(problem, oracle)
    largest = max(problem.capacities)
    too_heavy = [j for j in selection.mandatory if problem.requirement[j] > largest]
    if too_heavy:
        raise ValueError(f"no vehicle in the fleet can clean mandatory streets {too_heavy[:10]}")
    if selection.unreachable_mandatory:
        raise ValueError(f"mandatory streets unreachable within T: {selection.unreachable_mandatory[:10]}")
    dense = problem.num_junctions <= DENSE_LIMIT
    n_tasks = len(selection.mandatory) + len(selection.optional)
    log.append(f"tasks: {len(selection.mandatory)} mandatory + {len(selection.optional)} optional")

    if dense and n_tasks * problem.num_vehicles <= ORDERED_CELLS:
        mandatory_only = Selection(selection.mandatory, [], [])
        plans = [
            ("class-ordered tour (M+O)", concatenate(problem, oracle, list(
                _class_tours(problem, oracle, selection, dense).values()))),
            ("nearest-neighbour tour (M+O)", build_tour(
                problem, oracle, selection.mandatory + selection.optional, dense)),
            ("class-ordered tour (M only)", concatenate(problem, oracle, list(
                _class_tours(problem, oracle, mandatory_only, dense).values()))),
            ("nearest-neighbour tour (M only)", build_tour(
                problem, oracle, selection.mandatory, dense)),
        ]
        best = None
        for label, tour in plans:
            value, parts = plan_ordered(problem, oracle, tour)
            if value == NEG:
                log.append(f"{label}: no feasible split")
                continue
            plan_log: list[str] = []
            routes, services = routes_from_segments(problem, oracle, parts)
            evaluation = finish(problem, oracle, routes, dense, plan_log)
            log.append(f"{label}: split {(1 - problem.alpha) + value:.6f} -> "
                       f"final {evaluation.score:.6f} ({plan_log[-1] if plan_log else ''})")
            if evaluation.valid and (best is None or evaluation.score > best[1].score):
                best = (routes, evaluation, services)
        if best is None:
            raise ValueError("no feasible split for any tour")
        routes, evaluation, services = best
    else:
        tours = _class_tours(problem, oracle, selection, dense)
        _, parts = plan_by_class(problem, oracle, tours, log, selection, dense)
        routes, services = routes_from_segments(problem, oracle, parts)
        evaluation = finish(problem, oracle, routes, dense, log)
    return Result(routes, evaluation, services, log, time.perf_counter() - started)


def solve(instance, **_ignored) -> Solution:
    """Solution A behind the shared `main.py --algorithm dp-simple` interface."""
    problem = problem_from_instance(instance)
    return to_repo_solution(problem, solve_simple(problem).routes)
