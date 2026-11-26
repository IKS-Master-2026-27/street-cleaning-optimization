"""Cold and warm runs of the CLIPP competition model (OR-Tools CP-SAT).

The model itself is the unchanged competition code in
``third_party/clipp_cpsat`` (see its README). This module only

* builds that model exactly as ``clipp_cpsat.model.solve_milp`` does,
* turns an existing solution (the warm-start seed) into a CP-SAT hint
  (``AddHint``) and checks that the hint satisfies every constraint,
* runs the same solve loop with lazy subtour elimination, and records times,
  bounds and every valid solution on the way,
* checks the final routes with this repository's validator and official score.

Score and bounds. The competition model maximises the integer objective

    obj = round(1e9 * score terms)      (the constant 1 - alpha is left out)

so ``score = (1 - alpha) + obj / 1e9``. Every value below is converted to the
score scale. We maximise, so

    lower bound (LB) = score of the best *valid* solution found (connected routes)
    upper bound (UB) = smallest CP-SAT objective bound over the solve rounds;
                       every round solves a relaxation (only some subtour cuts),
                       so each of its bounds is valid for the full problem
    gap              = (UB - LB) / LB

Differences to ``clipp_cpsat.model._iterative_solve`` (the same six points as
in the tool README):

1. Warm start: the seed is given as a *complete* hint (every variable, zeros
   included) and is checked first with all variables fixed to it
   (``check_hint``). If several vehicles clean a street, the smallest keeps it.
2. Hint in later rounds: warm runs hint the better of the seed and the best
   valid solution found so far. The original replaces the hint with the last,
   disconnected, candidate; cold runs keep exactly that behaviour.
3. Time limit: the remaining time is measured against one deadline, so the time
   spent on subtour cuts also counts (the original only subtracts solve time).
4. Valid solutions that CP-SAT finds *during* a round are recorded (time of
   the first valid solution, best valid solution), not only the end of a round.
5. The loop stops as soon as a known valid solution (found, or the warm-start
   seed) reaches the upper bound: it is then proven optimal and further rounds
   cannot improve it.
6. A warm result is never reported below its seed (``final_values``).
"""

from __future__ import annotations

import collections
import math
import time
from dataclasses import dataclass, field
from typing import Callable

from ortools.sat.python import cp_model  # noqa: E402

from clipp_cpsat import model as competition  # noqa: E402  (unchanged model code)
from clipp_cpsat.graph import build_arcs, dijkstra  # noqa: E402

from clipp.solver import Solution, VehicleRoute  # noqa: E402

OBJ_SCALE = competition._OBJ_SCALE
CALLBACK_CHECK_MAX_VARS = 2_000_000   # larger models: check connectivity per round only


# ------------------------------------------------------------------ size

def count_variables(instance: dict) -> int:
    """Variables of the competition model: f[a,k] + clean[j,k] + cleaned[j].

    Cheap to compute, so it is known even when the model cannot be built.
    """

    arcs = sum(2 if s["dir"] == 2 else 1 for s in instance["streets"])
    clean = sum(1 for s in instance["streets"] for v in instance["vehicles"]
                if s["cat"] != "C" and v["cap"] >= s["req"])
    cleaned = sum(1 for s in instance["streets"] if s["cat"] != "C")
    return arcs * instance["C"] + clean + cleaned


# ------------------------------------------------------------------ model

@dataclass
class BuiltModel:
    instance: dict
    model: cp_model.CpModel
    f: dict
    clean: dict
    cleaned: dict
    arcs: list
    out_arcs: dict
    in_arcs: dict
    street_arcs: dict
    arc_cost: list
    arc_max: list
    relaxed_mandatory: set

    @property
    def num_vars(self) -> int:
        return len(self.model.Proto().variables)

    @property
    def num_constraints(self) -> int:
        return len(self.model.Proto().constraints)

    def to_score(self, objective: float) -> float:
        return (1.0 - self.instance["alpha"]) + objective / OBJ_SCALE


def unreachable_mandatory(instance: dict) -> set[int]:
    """Mandatory streets no vehicle can reach and leave within T.

    Same check as the competition ``clipp_solver.py``; these are relaxed
    (treated as optional) there, and so here.
    """

    N, T, S = instance["N"], instance["T"], instance["S"]
    arcs, *_ = build_arcs(instance)
    forward, backward = collections.defaultdict(list), collections.defaultdict(list)
    for u, v, j in arcs:
        cost = instance["streets"][j]["cost"]
        forward[u].append((v, cost))
        backward[v].append((u, cost))
    out_time = dijkstra(S, forward, N)
    back_time = dijkstra(S, backward, N)
    missing = set()
    for s in instance["streets"]:
        if s["cat"] != "M":
            continue
        ok = out_time[s["a"]] + s["cost"] + back_time[s["b"]] <= T
        if s["dir"] == 2:
            ok = ok or out_time[s["b"]] + s["cost"] + back_time[s["a"]] <= T
        if not ok:
            missing.add(s["id"])
    return missing


def build(instance: dict) -> BuiltModel:
    """Build the competition model, line for line as ``solve_milp`` does."""

    relaxed = unreachable_mandatory(instance)
    N, M, T, C, S, alpha = (instance[k] for k in ("N", "M", "T", "C", "S", "alpha"))
    streets, vehicles = instance["streets"], instance["vehicles"]
    arcs, out_arcs, in_arcs, street_arcs, arc_cost = build_arcs(instance)
    A = len(arcs)
    arc_max = [min(T // max(arc_cost[a], 1), 50) for a in range(A)]

    model = cp_model.CpModel()
    f = competition._create_flow_vars(model, A, C, arc_max)
    clean = competition._create_clean_vars(model, M, C, streets, vehicles)
    cleaned = competition._create_cleaned_vars(model, M, streets)
    competition._add_flow_conservation(model, f, N, C, out_arcs, in_arcs)
    competition._add_time_constraints(model, f, A, C, T, arc_cost)
    competition._add_traversal_requirements(model, f, clean, M, C, streets, street_arcs)
    competition._add_cleaned_linkage(model, clean, cleaned, M, C, streets)
    competition._add_single_cleaner(model, clean, M, C, streets)
    competition._add_mandatory_constraints(model, cleaned, M, streets, relaxed)
    competition._add_depot_inclusion(model, f, A, C, S, out_arcs, arc_max)
    competition._set_objective(model, clean, cleaned, M, C, streets, vehicles, alpha)
    return BuiltModel(instance, model, f, clean, cleaned, arcs, out_arcs, in_arcs,
                      street_arcs, arc_cost, arc_max, relaxed)


# ------------------------------------------------------------------ hint

@dataclass
class Values:
    """A full assignment of the model: arc counts and cleaning decisions."""

    f: dict          # (arc, vehicle) -> count, only non-zero entries
    clean: dict      # (street, vehicle) -> 1, only ones


def seed_values(built: BuiltModel, solution: Solution) -> Values:
    """Turn a solution (this repo's routes) into model values.

    If several vehicles clean the same street, only the smallest truck keeps
    it: the model allows one cleaner per street, coverage stays the same and
    the waste can only drop.
    """

    arc_index = {arc: index for index, arc in enumerate(built.arcs)}
    f: dict = {}
    for k, route in enumerate(solution.routes):
        for step, street_id in enumerate(route.street_ids):
            key = (route.junctions[step], route.junctions[step + 1], street_id)
            a = arc_index[key]
            f[a, k] = f.get((a, k), 0) + 1
    cleaner: dict[int, int] = {}
    for k, route in enumerate(solution.routes):
        for j in route.cleaned_street_ids:
            if built.instance["streets"][j]["cat"] == "C":
                continue
            current = cleaner.get(j)
            if current is None or route.capacity < solution.routes[current].capacity:
                cleaner[j] = k
    return Values(f, {(j, k): 1 for j, k in cleaner.items()})


def set_hint(built: BuiltModel, values: Values) -> None:
    """Hint every variable (a complete hint: zeros included)."""

    model = built.model
    model.clear_hints()
    for key, var in built.f.items():
        model.add_hint(var, values.f.get(key, 0))
    cleaned = {j for j, _ in values.clean}
    for key, var in built.clean.items():
        if isinstance(var, cp_model.IntVar):
            model.add_hint(var, values.clean.get(key, 0))
    for j, var in built.cleaned.items():
        if isinstance(var, cp_model.IntVar):
            model.add_hint(var, 1 if j in cleaned else 0)


def check_hint(built: BuiltModel, values: Values, workers: int,
               time_limit: float) -> tuple[bool, str, float | None]:
    """Is the hint a feasible solution of the model?

    Solves the model with every variable fixed to its hinted value
    (``fix_variables_to_their_hinted_value``) and checks that the routes are
    connected to the depot. Returns (feasible, CP-SAT status, objective).
    """

    set_hint(built, values)
    solver = cp_model.CpSolver()
    solver.parameters.fix_variables_to_their_hinted_value = True
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    status = solver.solve(built.model)
    name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return False, name, None
    if not routes_connected(built, values.f):
        return False, name + " but disconnected", None
    return True, name, solver.objective_value


# ------------------------------------------------------------------ connectivity

def routes_connected(built: BuiltModel, f: dict) -> bool:
    """Every vehicle's driven arcs are (weakly) connected to the depot.

    Flow conservation makes every junction balanced, so weakly connected
    means one closed walk through the depot: exactly the subtour test of the
    competition code (``_eliminate_subtours`` finds no component).
    """

    depot = built.instance["S"]
    neighbours: dict[int, dict[int, list[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for (a, k), count in f.items():
        if count:
            u, v, _ = built.arcs[a]
            neighbours[k][u].append(v)
            neighbours[k][v].append(u)
    for graph in neighbours.values():
        seen = {depot}
        queue = collections.deque([depot])
        while queue:
            node = queue.popleft()
            for other in graph.get(node, ()):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        if len(seen) < len(graph) or any(node not in seen for node in graph):
            return False
    return True


# ------------------------------------------------------------------ solve

@dataclass
class SolveRecord:
    rounds: int = 0
    cuts_rounds: int = 0
    statuses: list[str] = field(default_factory=list)
    best: Values | None = None
    best_objective: float | None = None       # model objective (integer scale)
    best_seconds: float | None = None
    first_valid_seconds: float | None = None
    first_solution_seconds: float | None = None   # any CP-SAT solution, maybe disconnected
    upper_objective: float | None = None
    proven_optimal: bool = False
    seed_proven_optimal: bool = False   # the solver found nothing better than the seed,
                                        # and its bound proves the seed optimal
    stop_reason: str = ""
    solve_seconds: float = 0.0
    awake_seconds: float = 0.0


class _Watcher(cp_model.CpSolverSolutionCallback):
    """Records every CP-SAT solution of one round; keeps the valid ones."""

    def __init__(self, built: BuiltModel, record: SolveRecord, offset: float,
                 check: bool, log: Callable[..., None]) -> None:
        super().__init__()
        self.built, self.record, self.offset = built, record, offset
        self.check, self.log = check, log

    def on_solution_callback(self) -> None:
        seconds = self.offset + self.wall_time
        objective, bound = self.objective_value, self.best_objective_bound
        record = self.record
        if record.first_solution_seconds is None:
            record.first_solution_seconds = seconds
        valid = None
        if self.check and (record.best_objective is None or objective > record.best_objective):
            f = {key: value for key, var in self.built.f.items()
                 if (value := self.value(var))}
            valid = routes_connected(self.built, f)
            if valid:
                clean = {key: 1 for key, var in self.built.clean.items()
                         if isinstance(var, cp_model.IntVar) and self.value(var)}
                _keep(record, Values(f, clean), objective, seconds)
        self.log("solution", seconds, objective, bound, valid)


def _keep(record: SolveRecord, values: Values, objective: float, seconds: float) -> None:
    if record.first_valid_seconds is None:
        record.first_valid_seconds = seconds
    if record.best_objective is None or objective > record.best_objective:
        record.best, record.best_objective, record.best_seconds = values, objective, seconds


def solve(built: BuiltModel, *, time_limit: float, workers: int,
          seed: Values | None = None, seed_objective: float | None = None,
          random_seed: int = 0,
          progress: Callable[[str, float, float | None, float | None, bool | None, int], None]
          | None = None) -> SolveRecord:
    """The competition solve loop (CP-SAT + lazy subtour cuts), with a hint if warm."""

    record = SolveRecord()
    C, A, M, S = built.instance["C"], len(built.arcs), built.instance["M"], built.instance["S"]
    check = len(built.f) <= CALLBACK_CHECK_MAX_VARS
    max_iterations = max(20, min(500, int(max(time_limit, 1) // 5)))   # as the original
    wall_start, awake_start = time.time(), time.perf_counter()
    deadline = awake_start + time_limit
    if seed is not None:
        set_hint(built, seed)
    else:
        built.model.clear_hints()

    def log(event, seconds, objective, bound, valid):
        if progress:
            progress(event, seconds, objective, bound, valid, record.rounds)

    for iteration in range(max_iterations):
        remaining = deadline - time.perf_counter()
        if remaining <= 1.0:
            record.stop_reason = "time_limit"
            break
        record.rounds = iteration + 1
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_workers = workers
        solver.parameters.random_seed = random_seed
        solver.parameters.log_search_progress = (iteration == 0)
        offset = time.perf_counter() - awake_start
        status = solver.solve(built.model, _Watcher(built, record, offset, check, log))
        name = solver.status_name(status)
        record.statuses.append(name)
        bound = solver.best_objective_bound
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and math.isfinite(bound):
            record.upper_objective = (bound if record.upper_objective is None
                                      else min(record.upper_objective, bound))
        known = max((v for v in (record.best_objective, seed_objective) if v is not None),
                    default=None)
        if (known is not None and record.upper_objective is not None
                and known >= record.upper_objective - 0.5):
            record.stop_reason = "optimal"
            log("round_end", time.perf_counter() - awake_start, solver.objective_value
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None, bound, None)
            break
        if status == cp_model.INFEASIBLE:
            record.stop_reason = "infeasible"
            break
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            record.stop_reason = "time_limit" if deadline - time.perf_counter() <= 1.0 \
                else name.lower()
            break

        candidate_f = {(a, k): solver.value(built.f[a, k]) for k in range(C) for a in range(A)}
        # the competition subtour step: adds a cut for every component that misses the depot
        found = competition._eliminate_subtours(
            built.model, built.f, candidate_f, built.arcs, built.arc_max, A, C, S)
        log("round_end", time.perf_counter() - awake_start, solver.objective_value,
            bound, not found)
        if not found:
            clean = {(j, k): 1 for j in range(M) for k in range(C)
                     if isinstance(built.clean[j, k], cp_model.IntVar)
                     and solver.value(built.clean[j, k])}
            _keep(record, Values({key: v for key, v in candidate_f.items() if v}, clean),
                  solver.objective_value, time.perf_counter() - awake_start)
            record.proven_optimal = status == cp_model.OPTIMAL
            record.stop_reason = "optimal" if record.proven_optimal else "time_limit"
            break
        record.cuts_rounds += 1
        if deadline - time.perf_counter() <= 2.0:
            record.stop_reason = "time_limit"
            break
        if seed is not None:
            # warm: keep hinting the best valid solution (the seed or better)
            better = (record.best is not None and (
                seed_objective is None or record.best_objective >= seed_objective))
            set_hint(built, record.best if better else seed)
        else:
            # cold: as the original, hint the last (disconnected) candidate
            built.model.clear_hints()
            for k in range(C):
                for a in range(A):
                    built.model.add_hint(built.f[a, k], candidate_f[a, k])
                for j in range(M):
                    if isinstance(built.clean[j, k], cp_model.IntVar):
                        built.model.add_hint(built.clean[j, k], solver.value(built.clean[j, k]))
    else:
        record.stop_reason = "iteration_limit"

    record.awake_seconds = time.perf_counter() - awake_start
    record.solve_seconds = time.time() - wall_start
    if record.upper_objective is not None:
        if (record.best_objective is not None
                and record.best_objective >= record.upper_objective - 0.5):
            record.proven_optimal = True
            record.stop_reason = "optimal"
        elif seed_objective is not None and seed_objective >= record.upper_objective - 0.5:
            record.seed_proven_optimal = True
            record.stop_reason = "optimal"
    return record


def final_values(record: SolveRecord, seed: Values | None,
                 seed_objective: float | None) -> tuple[Values | None, float | None, bool]:
    """The solution to report: the solver's best valid one, unless the seed is better.

    Returns (values, model objective, came from the solver). A warm run is never
    reported below its seed: if CP-SAT found only worse valid solutions (or
    none), the seed is the result.
    """

    if seed is not None and seed_objective is not None and (
            record.best is None or record.best_objective < seed_objective):
        return seed, seed_objective, False
    return record.best, record.best_objective, record.best is not None


# ------------------------------------------------------------------ routes

def to_solution(built: BuiltModel, values: Values) -> Solution:
    """Routes from arc counts (Hierholzer), keeping the street of every step."""

    instance = built.instance
    depot = instance["S"]
    routes = []
    for k, vehicle in enumerate(instance["vehicles"]):
        unused: dict[int, list[int]] = collections.defaultdict(list)
        for (a, kk), count in sorted(values.f.items()):
            if kk == k:
                unused[built.arcs[a][0]].extend([a] * int(count))
        for arcs in unused.values():
            arcs.reverse()
        stack: list[tuple[int, int | None]] = [(depot, None)]
        walk: list[tuple[int, int | None]] = []
        while stack:
            node = stack[-1][0]
            if unused.get(node):
                a = unused[node].pop()
                stack.append((built.arcs[a][1], a))
            else:
                walk.append(stack.pop())
        walk.reverse()
        if any(unused.values()):
            raise ValueError(f"vehicle {k}: arcs not connected to the depot")
        steps = [a for _, a in walk[1:]]
        routes.append(VehicleRoute(
            vehicle_id=k, vehicle_type=vehicle["type"], capacity=vehicle["cap"],
            current_junction=walk[-1][0], junctions=[node for node, _ in walk],
            total_time=sum(built.arc_cost[a] for a in steps),
            street_ids=[built.arcs[a][2] for a in steps],
            cleaned_street_ids=sorted(j for (j, kk) in values.clean if kk == k)))
    return Solution(routes)
