"""Solution B (detyra 13): Dynamic Programming with Memoization.

Improvement of Solution A (`dp-simple`, simple.py). Solution A fills its DP
tables bottom-up and recomputes everything for each of the 4 plans it tries.
This solver stores the results of earlier computations and reuses them:

  1. Top-down Split DP with a memo table.
         P(k, i) = best value covering tour prefix 0..i-1 with vehicles 1..k
     is a recursive function; every state (k, i) is computed once and then read
     from the memo. Only states reachable from P(K, n) are ever evaluated.

  2. Memoized range maximum (sparse table built on demand).
     The Split transition needs max_{s in [lo, i-1]} (P(k-1, s) - V_q[s]).
     ST(k, j, s) = max over the 2^j positions starting at s is memoized with
         ST(k, j, s) = max(ST(k, j-1, s), ST(k, j-1, s + 2^(j-1))),
     so each window maximum costs two memo lookups instead of a scan.

  3. Memo shared between plans (across the whole run):
       * delta(j, q) scores           key (street, capacity)
       * giant tours                  key (streets, construction rule)
       * Split results                key (tour tasks, fleet order)
       * finished plans (routes, score) key (served tasks of every vehicle)
     Different tours / fleet orders often lead to the same routes; the second
     time the expensive route building + knapsack DP is skipped.

Because repeated work is free, the solver explores many more plans than
Solution A: every order of the vehicle classes x several nearest-neighbour
variants x matching fleet orders (hundreds of Split runs instead of 4). Each
per-class tour is built once and reused by every permutation. Solution A's
plans are always included, so the search covers everything Solution A tries.

  4. Route-level DPs on the 10 best plans (route_dp.py):
       * windowed Held-Karp, f(mask, last) over subsets of 6 consecutive tasks,
         memoized under (entry node, exit node, streets) - repeated windows in
         later sweeps and in other plans are read from the memo (60-76% hits);
       * multiple-choice knapsack DP that inserts optional streets into the
         gaps between served tasks within the remaining time.

This module is DP + memoization only. The extension with local search (not part
of task 13) is `memo_ls.py`, registered separately as `dp-memo-ls`.

Large networks (above DENSE_LIMIT junctions or ORDERED_CELLS) use Solution A's
class mode with the memoized delta; on the city instances it already reaches
score 1.0.
"""

import sys
import threading
import time
from dataclasses import dataclass, field
from itertools import permutations

from ..solver import Solution
from .assignment import route_from_tasks, routes_from_segments
from .distances import Oracle
from .route_dp import RouteDP
from .io import Problem, problem_from_instance
from .objective import Evaluation, Route, to_repo_solution
from .simple import DENSE_LIMIT, ORDERED_CELLS, _class_tours, finish, plan_by_class
from .split import NEG, Segment, SplitData, vehicles_for
from .tour import (Selection, Tour, build_tour, class_of, concatenate, make_tour,
                   nearest_neighbor, select_streets)


# --------------------------------------------------------------------------- memo

@dataclass
class Memo:
    """A dictionary of stored results with hit / miss counters."""
    name: str
    store: dict = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key, compute):
        try:
            value = self.store[key]
        except KeyError:
            self.misses += 1
            value = self.store[key] = compute()
            return value
        self.hits += 1
        return value

    def report(self) -> str:
        total = self.hits + self.misses
        rate = 100.0 * self.hits / total if total else 0.0
        return f"{self.name}: {len(self.store)} stored, {self.hits} hits / {total} lookups ({rate:.1f}%)"


@dataclass
class Stats:
    split_states: int = 0       # P(k, i) states computed by the top-down Split
    split_hits: int = 0         # P(k, i) reads answered from the memo
    table_states: int = 0       # states a full bottom-up table would fill (sum of n * K)
    rmq_states: int = 0
    rmq_hits: int = 0
    plans: int = 0
    log: list[str] = field(default_factory=list)


class MemoProblem(Problem):
    """Problem whose delta(j, q) results are memoized."""

    _delta_memo: Memo

    def delta(self, j: int, capacity: int) -> float | None:
        memo = self._delta_memo
        key = (j, capacity)
        try:
            value = memo.store[key]
        except KeyError:
            memo.misses += 1
            value = memo.store[key] = Problem.delta(self, j, capacity)
            return value
        memo.hits += 1
        return value


def memo_problem(problem: Problem) -> MemoProblem:
    problem.__class__ = MemoProblem
    problem._delta_memo = Memo("delta(j, q)")
    return problem


# ------------------------------------------------------- top-down memoized Split

def split_memo(data: SplitData, capacities: list[int], stats: Stats) -> tuple[float, list[Segment]]:
    """Selective Split (same recurrence as split.split_ordered), top-down with memoization.

        P(0, i) = 0 if the prefix 0..i-1 has no mandatory task, else -inf
        P(k, 0) = P(k-1, 0)
        P(k, i) = max( P(k-1, i),                                  vehicle k unused
                       P(k, i-1)            if task i-1 optional,  task skipped
                       V_q[i] + max_{s in [lo(i-1), i-1]} (P(k-1, s) - V_q[s]) )
    """
    n, K = data.n, len(capacities)
    values = [data.values(q) for q in capacities]
    windows = [data.window(q) for q in capacities]
    mandatory = data.mandatory
    P: dict[tuple[int, int], tuple[float, int]] = {}    # (k, i) -> (value, choice)
    ST: dict[tuple[int, int, int], tuple[float, int]] = {}  # (k, j, s) -> (max key, argmax)
    counters = [0, 0, 0, 0]  # P computed, P hits, ST computed, ST hits

    def best(k: int, i: int) -> float:
        key = (k, i)
        stored = P.get(key)
        if stored is not None:
            counters[1] += 1
            return stored[0]
        counters[0] += 1
        if k == 0:
            result = (NEG if data.prefix_has_mandatory(i) else 0.0, -1)
        elif i == 0:
            result = (best(k - 1, 0), -1)
        else:
            value, how = best(k - 1, i), -1
            if not mandatory[i - 1]:
                skip = best(k, i - 1)
                if skip > value:
                    value, how = skip, -2
            lo = windows[k - 1][i - 1]
            if lo <= i - 1:
                key_max, s = window_max(k, lo, i - 1)
                if key_max > NEG:
                    route = values[k - 1][i] + key_max
                    if route > value:
                        value, how = route, s
            result = (value, how)
        P[key] = result
        return result[0]

    def table(k: int, j: int, s: int) -> tuple[float, int]:
        """max of P(k-1, x) - V_q[x] for x in [s, s + 2^j), memoized."""
        key = (k, j, s)
        stored = ST.get(key)
        if stored is not None:
            counters[3] += 1
            return stored
        counters[2] += 1
        if j == 0:
            p = best(k - 1, s)
            result = (p - values[k - 1][s] if p > NEG else NEG, s)
        else:
            half = 1 << (j - 1)
            left, right = table(k, j - 1, s), table(k, j - 1, s + half)
            result = right if right[0] >= left[0] else left
        ST[key] = result
        return result

    def window_max(k: int, lo: int, hi: int) -> tuple[float, int]:
        j = (hi - lo + 1).bit_length() - 1
        left, right = table(k, j, lo), table(k, j, hi - (1 << j) + 1)
        return right if right[0] >= left[0] else left

    # Fill the memo in a cheap order first (keeps recursion shallow), then ask
    # for the answer; every state is still computed at most once.
    for k in range(K + 1):
        for i in range(0, n + 1, 64):
            best(k, i)
    total = best(K, n)

    stats.split_states += counters[0]
    stats.split_hits += counters[1]
    stats.rmq_states += counters[2]
    stats.rmq_hits += counters[3]
    stats.table_states += (n + 1) * (K + 1)
    if total == NEG:
        return NEG, []
    segments: list[Segment] = []
    i, k = n, K
    while i > 0 and k > 0:
        how = P[(k, i)][1]
        if how == -1:
            k -= 1
        elif how == -2:
            i -= 1
        else:
            segments.append(Segment(capacities[k - 1], how, i - 1))
            i, k = how, k - 1
    segments.reverse()
    return total, segments


def _with_deep_stack(function, *args):
    """Run a deeply recursive function in a thread with a large stack."""
    result: list = []
    error: list = []

    def target():
        try:
            result.append(function(*args))
        except BaseException as exc:  # re-raised in the caller
            error.append(exc)

    old_limit = sys.getrecursionlimit()
    old_size = threading.stack_size()
    sys.setrecursionlimit(max(old_limit, 1_000_000))
    for megabytes in (256, 128, 64):
        try:
            threading.stack_size(megabytes * 1024 * 1024)
            break
        except ValueError:
            continue
    try:
        worker = threading.Thread(target=target)
        worker.start()
        worker.join()
    finally:
        threading.stack_size(old_size)
        sys.setrecursionlimit(old_limit)
    if error:
        raise error[0]
    return result[0]


# ---------------------------------------------------------------- the solver

@dataclass
class Result:
    routes: list[Route]
    evaluation: Evaluation
    log: list[str]
    seconds: float
    memos: list[Memo]
    stats: Stats


class MemoSolver:
    def __init__(self, problem: Problem) -> None:
        self.problem = memo_problem(problem)
        self.oracle = Oracle(problem)
        self.dense = problem.num_junctions <= DENSE_LIMIT
        self.stats = Stats()
        self.tours = Memo("giant tours")
        self.splits = Memo("Split results")
        self.plans = Memo("finished plans")
        self.refinements = Memo("route-DP refined plans")
        self.route_dp = RouteDP(self.problem, self.oracle, window=6)
        self.refine_top = 10
        self.insert_rounds = 6

    # -- memoized building blocks ------------------------------------------
    def tour(self, rule: str, streets: list[int], param: int = 0) -> Tour:
        problem, oracle = self.problem, self.oracle

        def build() -> Tour:
            if rule == "nn":
                return build_tour(problem, oracle, streets, self.dense)
            if rule == "nn-second":
                return make_tour(problem, oracle,
                                 nearest_neighbor(problem, oracle, streets, second_every=param))
            raise ValueError(rule)
        return self.tours.get((rule, param, tuple(streets)), build)

    def groups(self, streets: list[int]) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for j in streets:
            groups.setdefault(class_of(self.problem, j), []).append(j)
        return groups

    def class_tour(self, selection: Selection, descending: bool, param: int = 0,
                   order: tuple[int, ...] | None = None) -> Tour:
        groups = self.groups(selection.mandatory + selection.optional)
        rule = "nn-second" if param else "nn"
        if order is None:
            order = tuple(sorted(groups, reverse=descending))
        parts = [self.tour(rule, groups[q], param) for q in order if q in groups]
        return concatenate(self.problem, self.oracle, parts)

    def split(self, tour: Tour, capacities: list[int]):
        def compute():
            data = SplitData(self.problem, self.oracle, tour)
            value, segments = split_memo(data, capacities, self.stats)
            return value, data, segments
        return self.splits.get((tuple(tour.tasks), tuple(capacities)), compute)

    @staticmethod
    def signature(data: SplitData, segments: list[Segment]) -> tuple:
        return tuple(sorted((seg.capacity, tuple(data.tour.tasks[seg.first:seg.last + 1]))
                            for seg in segments))

    def plan(self, data: SplitData, segments: list[Segment]):
        """Routes + knapsack DP + evaluation, memoized on what each vehicle serves."""
        def compute():
            self.stats.plans += 1
            routes, _ = routes_from_segments(self.problem, self.oracle, [(data, segments)])
            evaluation = finish(self.problem, self.oracle, routes, self.dense, [])
            return routes, evaluation
        return self.plans.get(self.signature(data, segments), compute)

    # -- search -----------------------------------------------------------
    def candidate_tours(self, selection: Selection):
        problem = self.problem
        mandatory_only = Selection(selection.mandatory, [], [])
        everything = selection.mandatory + selection.optional
        yield "class-ordered (M+O)", self.class_tour(selection, True)
        yield "nearest-neighbour (M+O)", self.tour("nn", everything)
        yield "class-ordered (M only)", self.class_tour(mandatory_only, True)
        yield "nearest-neighbour (M only)", self.tour("nn", selection.mandatory)
        yield "class-ascending (M+O)", self.class_tour(selection, False)
        yield "class-ascending (M only)", self.class_tour(mandatory_only, False)
        mandatory_first = concatenate(problem, self.oracle, [
            self.tour("nn", selection.mandatory), self.tour("nn", selection.optional)])
        yield "mandatory-first (M, then O)", mandatory_first
        # Every order of the vehicle classes x several nearest-neighbour variants.
        # The per-class tours are memoized, so each permutation only concatenates
        # tours that were already built.
        classes = sorted(self.groups(selection.mandatory))
        for k in (0, 2, 3, 4, 5, 7):
            for order in permutations(classes):
                names = ",".join(str(q) for q in order)
                yield f"classes {names} nn-{k} (M only)", self.class_tour(mandatory_only, True, k, order)
                yield f"classes {names} nn-{k} (M+O)", self.class_tour(selection, True, k, order)

    def fleet_orders(self) -> list[tuple[str, list[int]]]:
        caps = self.problem.capacities
        orders = [("L,M,S", sorted(caps, reverse=True)), ("S,M,L", sorted(caps)), ("as given", list(caps))]
        for order in permutations(sorted(set(caps))):
            rank = {q: r for r, q in enumerate(order)}
            orders.append((",".join(map(str, order)), sorted(caps, key=lambda q: rank[q])))
        unique, seen = [], set()
        for label, order in orders:
            if tuple(order) not in seen:
                seen.add(tuple(order))
                unique.append((label, order))
        return unique

    def solve(self) -> Result:
        started = time.perf_counter()
        problem, oracle, log = self.problem, self.oracle, self.stats.log
        selection = select_streets(problem, oracle)
        largest = max(problem.capacities)
        too_heavy = [j for j in selection.mandatory if problem.requirement[j] > largest]
        if too_heavy:
            raise ValueError(f"no vehicle in the fleet can clean mandatory streets {too_heavy[:10]}")
        if selection.unreachable_mandatory:
            raise ValueError(f"mandatory streets unreachable within T: {selection.unreachable_mandatory[:10]}")
        n_tasks = len(selection.mandatory) + len(selection.optional)
        log.append(f"tasks: {len(selection.mandatory)} mandatory + {len(selection.optional)} optional")

        if self.dense and n_tasks * problem.num_vehicles <= ORDERED_CELLS:
            best = None
            pool: dict[tuple, tuple] = {}   # distinct DP plans -> (score, data, segments, label)
            for label, tour in self.candidate_tours(selection):
                for fleet_label, capacities in self.fleet_orders():
                    value, data, segments = self.split(tour, capacities)
                    if value == NEG:
                        continue
                    routes, evaluation = self.plan(data, segments)
                    if not evaluation.valid:
                        continue
                    pool.setdefault(self.signature(data, segments),
                                    (evaluation.score, data, segments, f"{label}, fleet {fleet_label}"))
                    if best is None or evaluation.score > best[1].score + 1e-12:
                        best = (routes, evaluation)
                        log.append(f"new best {evaluation.score:.6f}: {label}, fleet {fleet_label}")
            if best is None:
                raise ValueError("no feasible split for any tour")
            log.append(f"DP phase best {best[1].score:.6f} from {len(pool)} distinct plans")
            routes, evaluation = self.after_dp(pool, best)
        else:
            # Large networks: Solution A's class mode (already optimal score on the
            # repository's city instances), run with the memoized delta / oracle.
            tours = _class_tours(problem, oracle, selection, self.dense)
            _, parts = plan_by_class(problem, oracle, tours, log, selection, self.dense)
            routes, _ = routes_from_segments(problem, oracle, parts)
            evaluation = finish(problem, oracle, routes, self.dense, log)
        memos = [problem._delta_memo, *self.memos()]
        return Result(routes, evaluation, log, time.perf_counter() - started, memos, self.stats)

    def after_dp(self, pool: dict[tuple, tuple], best: tuple) -> tuple:
        """Refine the best DP plans with the route-level DPs of route_dp.py
        (windowed Held-Karp + multiple-choice knapsack insertion), memoized."""
        log = self.stats.log
        top = sorted(pool.values(), key=lambda x: -x[0])[:self.refine_top]
        for score, data, segments, label in top:
            if best[1].score >= 1.0 - 1e-12:
                break
            routes, evaluation = self.refined(data, segments)
            if evaluation.valid and evaluation.score > best[1].score + 1e-12:
                best = (routes, evaluation)
                log.append(f"new best {evaluation.score:.6f}: route DP on {label} (Split {score:.6f})")
        return best

    def refined(self, data: SplitData, segments: list[Segment]):
        problem, oracle, rdp = self.problem, self.oracle, self.route_dp

        def compute():
            seqs: list[list[int]] = [[] for _ in range(problem.num_vehicles)]
            for vehicle, seg in vehicles_for(problem, segments):
                seqs[vehicle] = list(data.tour.tasks[seg.first:seg.last + 1])
            seqs = [rdp.reorder(s) for s in seqs]
            order = sorted(range(problem.num_vehicles), key=lambda v: (problem.capacities[v], v))
            for _ in range(self.insert_rounds):
                routes = [route_from_tasks(problem, oracle, v, s) for v, s in enumerate(seqs)]
                traversed = {j for r in routes for j in r.streets}
                candidates = {j for j in range(problem.num_streets)
                              if problem.category[j] != "C" and j not in traversed}
                before = sum(len(s) for s in seqs)
                for v in order:
                    seqs[v] = rdp.reorder(rdp.insert(seqs[v], problem.capacities[v], candidates))
                if sum(len(s) for s in seqs) == before:
                    break
            routes = [route_from_tasks(problem, oracle, v, s) for v, s in enumerate(seqs)]
            return routes, finish(problem, oracle, routes, self.dense, [])
        return self.refinements.get(self.signature(data, segments), compute)

    def memos(self) -> list[Memo]:
        hk = Memo("Held-Karp windows", self.route_dp.memo, self.route_dp.hits, self.route_dp.misses)
        return [self.tours, self.splits, self.plans, self.refinements, hk]


def solve_memo(problem: Problem, solver_class: type = MemoSolver) -> Result:
    return _with_deep_stack(lambda: solver_class(problem).solve())


last_result: Result | None = None


def solve(instance, **_ignored) -> Solution:
    """Solution B behind the shared `main.py --algorithm dp-memo` interface."""
    global last_result
    problem = problem_from_instance(instance)
    last_result = solve_memo(problem)
    return to_repo_solution(problem, last_result.routes)
