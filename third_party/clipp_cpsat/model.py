"""
CP-SAT MILP formulation for the CLIPP problem.
"""

import time

from ortools.sat.python import cp_model

from .graph import (
    build_arcs,
    build_adj_multigraph,
    connected_components,
)

__all__ = ["solve_milp"]


def solve_milp(
    instance: dict,
    time_limit_sec: int,
    num_workers: int,
    relaxed_mandatory: set | None = None,
):
    """
    Build and solve the CP-SAT MILP for the CLIPP problem.

    Parameters
    ----------
    instance : dict
        Parsed instance.
    time_limit_sec : int
        Wall-clock time budget for the solver (seconds).
    num_workers : int
        Number of parallel solver workers.
    relaxed_mandatory : set[int] | None
        Street indices that are mandatory but provably unreachable.  These are
        treated as optional (soft) rather than hard constraints.

    Returns
    -------
    f_vals : dict | None
        Arc-flow values ``{(arc_idx, vehicle_idx): int}``.
    clean_vals : dict | None
        Cleaning assignments ``{(street_idx, vehicle_idx): int}``.
    graph_info : tuple | None
        ``(arcs, out_arcs, in_arcs, street_arcs, arc_cost)``.
    status_name : str | None
        Human-readable solver status string.

    Formulation
    -----------
    **Variables**
        - ``f[a, k]``     integer >= 0 – times vehicle *k* traverses arc *a*
        - ``clean[j, k]`` binary       – vehicle *k* cleans street *j*
        - ``cleaned[j]``  binary       – street *j* is cleaned by any vehicle

    **Constraints**
        1. Flow conservation at every node for each vehicle (closed walk).
        2. Route time <= T for each vehicle.
        3. ``clean[j, k] = 0`` if vehicle cannot clean street *j*.
        4. ``clean[j, k] <= traversals`` of street *j* by vehicle *k*.
        5. ``cleaned[j] <-> exists k: clean[j, k]``.
        6. Each street cleaned by at most one vehicle.
        7. All mandatory streets must be cleaned.
        8. Depot-inclusion (big-M): a vehicle that uses any arc must visit depot.

    **Objective**
        Maximise ``alpha * Coverage + (1-alpha) * Efficiency`` (normalized).
    """
    if relaxed_mandatory is None:
        relaxed_mandatory = set()

    N, M, T, C, S, alpha = (instance[k] for k in ("N", "M", "T", "C", "S", "alpha"))
    streets  = instance["streets"]
    vehicles = instance["vehicles"]

    arcs, out_arcs, in_arcs, street_arcs, arc_cost = build_arcs(instance)
    A = len(arcs)

    # Per-arc traversal upper bounds
    arc_max = [min(T // max(arc_cost[a], 1), 50) for a in range(A)]

    model = cp_model.CpModel()

    # ---- Decision variables ------------------------------------------------
    f     = _create_flow_vars(model, A, C, arc_max)
    clean = _create_clean_vars(model, M, C, streets, vehicles)
    cleaned = _create_cleaned_vars(model, M, streets)

    # ---- Constraints -------------------------------------------------------
    _add_flow_conservation(model, f, N, C, out_arcs, in_arcs)
    _add_time_constraints(model, f, A, C, T, arc_cost)
    _add_traversal_requirements(model, f, clean, M, C, streets, street_arcs)
    _add_cleaned_linkage(model, clean, cleaned, M, C, streets)
    _add_single_cleaner(model, clean, M, C, streets)
    _add_mandatory_constraints(model, cleaned, M, streets, relaxed_mandatory)
    _add_depot_inclusion(model, f, A, C, S, out_arcs, arc_max)

    # ---- Objective ---------------------------------------------------------
    _set_objective(model, clean, cleaned, M, C, streets, vehicles, alpha)

    # ---- Iterative solve with subtour elimination --------------------------
    print(f"\n[Solver] CP-SAT  |  time_limit={time_limit_sec}s  |  workers={num_workers}")
    print(f"[Model]  {A} arcs  |  {M} streets  |  {C} vehicles")

    return _iterative_solve(
        model, f, clean, arcs, arc_cost, arc_max,
        A, M, C, S, num_workers,
        time_limit_sec, out_arcs, in_arcs, street_arcs,
    )


# ---------------------------------------------------------------------------
# Variable creation helpers
# ---------------------------------------------------------------------------

def _create_flow_vars(model, A, C, arc_max):
    """``f[a, k]``: number of times vehicle *k* traverses arc *a*."""
    f = {}
    for k in range(C):
        for a in range(A):
            f[a, k] = model.new_int_var(0, arc_max[a], f"f_{a}_{k}")
    return f


def _create_clean_vars(model, M, C, streets, vehicles):
    """
    ``clean[j, k]``: BoolVar if vehicle *k* can clean street *j*, else
    plain ``0``.
    """
    clean = {}
    for j in range(M):
        s = streets[j]
        for k in range(C):
            if s["cat"] != "C" and vehicles[k]["cap"] >= s["req"]:
                clean[j, k] = model.new_bool_var(f"clean_{j}_{k}")
            else:
                clean[j, k] = 0
    return clean


def _create_cleaned_vars(model, M, streets):
    """``cleaned[j]``: BoolVar for non-connector streets."""
    cleaned = {}
    for j in range(M):
        if streets[j]["cat"] != "C":
            cleaned[j] = model.new_bool_var(f"cleaned_{j}")
        else:
            cleaned[j] = 0
    return cleaned


# ---------------------------------------------------------------------------
# Constraint helpers
# ---------------------------------------------------------------------------

def _add_flow_conservation(model, f, N, C, out_arcs, in_arcs):
    """(1) For each vehicle at each node: total out-flow == total in-flow."""
    for k in range(C):
        for u in range(N):
            out_f = [f[a, k] for a in out_arcs.get(u, [])]
            in_f  = [f[a, k] for a in in_arcs.get(u, [])]
            if out_f or in_f:
                model.add(sum(out_f) == sum(in_f))


def _add_time_constraints(model, f, A, C, T, arc_cost):
    """(2) Route time <= T for each vehicle."""
    for k in range(C):
        model.add(sum(arc_cost[a] * f[a, k] for a in range(A)) <= T)


def _add_traversal_requirements(model, f, clean, M, C, streets, street_arcs):
    """(3)+(4) If vehicle *k* cleans street *j* it must have traversed it."""
    for j in range(M):
        if streets[j]["cat"] == "C":
            continue
        for k in range(C):
            if not isinstance(clean[j, k], int):
                traversals = [f[a, k] for a in street_arcs[j]]
                if traversals:
                    model.add(sum(traversals) >= clean[j, k])


def _add_cleaned_linkage(model, clean, cleaned, M, C, streets):
    """(5) ``cleaned[j] <-> OR_k clean[j, k]``."""
    for j in range(M):
        if streets[j]["cat"] == "C":
            continue
        bool_vars = [
            clean[j, k] for k in range(C)
            if isinstance(clean[j, k], cp_model.IntVar)
        ]
        if bool_vars:
            for bv in bool_vars:
                model.add_implication(bv, cleaned[j])
            model.add_bool_or(bool_vars + [cleaned[j].Not()])
        else:
            model.add(cleaned[j] == 0)


def _add_single_cleaner(model, clean, M, C, streets):
    """(6) Each street cleaned by at most one vehicle."""
    for j in range(M):
        if streets[j]["cat"] == "C":
            continue
        bool_vars = [
            clean[j, k] for k in range(C)
            if isinstance(clean[j, k], cp_model.IntVar)
        ]
        if len(bool_vars) > 1:
            model.add(sum(bool_vars) <= 1)


def _add_mandatory_constraints(model, cleaned, M, streets, relaxed_mandatory):
    """(7) All mandatory streets must be cleaned (unless relaxed)."""
    for j in range(M):
        if streets[j]["cat"] == "M":
            if j in relaxed_mandatory:
                continue
            assert isinstance(cleaned[j], cp_model.IntVar), (
                f"Street {j} is mandatory but no vehicle can clean it!"
            )
            model.add(cleaned[j] == 1)


def _add_depot_inclusion(model, f, A, C, S, out_arcs, arc_max):
    """(8) Big-M: a vehicle using any arc must visit the depot."""
    big_M_val = sum(arc_max) + 1
    for k in range(C):
        depot_out_arcs = out_arcs.get(S, [])
        if depot_out_arcs:
            depot_out_sum  = sum(f[a, k] for a in depot_out_arcs)
            total_flow_sum = sum(f[a, k] for a in range(A))
            model.add(total_flow_sum <= big_M_val * depot_out_sum)


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------

_OBJ_SCALE = 1_000_000_000


def _set_objective(model, clean, cleaned, M, C, streets, vehicles, alpha):
    """
    Maximise weighted sum of normalized coverage and efficiency.

    Score = alpha * (total_cleaned_length / L_max)
            + (1 - alpha) * (1 - total_waste / W_max)

    The additive constant ``(1-alpha)`` is omitted because it does not affect
    argmax decisions.

    Scaled by :data:`_OBJ_SCALE` to keep integer arithmetic.
    """
    L_max = sum(s["length"] for s in streets if s["cat"] != "C")
    W_max = sum(
        max(0, 30 - s["req"]) * s["length"] / 1000.0
        for s in streets if s["cat"] != "C"
    )

    cov_weight = (alpha / L_max) if L_max > 0 else 0.0
    eff_penalty_weight = ((1.0 - alpha) / W_max) if W_max > 0 else 0.0

    obj_terms = []

    for j in range(M):
        s = streets[j]
        if s["cat"] == "C":
            continue

        # Positive: normalized coverage contribution
        if isinstance(cleaned[j], cp_model.IntVar):
            coeff = int(round(_OBJ_SCALE * cov_weight * s["length"]))
            if coeff > 0:
                obj_terms.append(coeff * cleaned[j])

        # Negative: normalized efficiency loss from water waste
        for k in range(C):
            if not isinstance(clean[j, k], cp_model.IntVar):
                continue
            excess = vehicles[k]["cap"] - s["req"]
            if excess > 0 and eff_penalty_weight > 0:
                waste_liters = excess * s["length"] / 1000.0
                penalty = int(round(_OBJ_SCALE * eff_penalty_weight * waste_liters))
                if penalty > 0:
                    obj_terms.append(-penalty * clean[j, k])

    model.maximize(sum(obj_terms) if obj_terms else 0)


# ---------------------------------------------------------------------------
# Iterative solve with subtour elimination
# ---------------------------------------------------------------------------

def _iterative_solve(
    model, f, clean, arcs, arc_cost, arc_max,
    A, M, C, S, num_workers,
    time_limit_sec, out_arcs, in_arcs, street_arcs,
):
    """
    Solve the model iteratively, adding subtour-elimination constraints
    until the solution is connected or the time budget runs out.
    """
    remaining_time = float(time_limit_sec)
    # Allow more subtour-cut rounds on harder instances, while keeping a cap.
    max_iterations = max(20, min(500, int(max(time_limit_sec, 1) // 5)))
    f_vals = None
    clean_vals = None
    status_name = None
    best_connected_f_vals = None
    best_connected_clean_vals = None
    best_connected_status = None

    for iteration in range(max_iterations):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(remaining_time, 1.0)
        solver.parameters.num_workers         = num_workers
        solver.parameters.log_search_progress = (iteration == 0)

        t0      = time.time()
        status  = solver.solve(model)
        elapsed = time.time() - t0
        remaining_time -= elapsed

        status_name = solver.status_name(status)
        obj_val = solver.objective_value if status in (
            cp_model.OPTIMAL, cp_model.FEASIBLE) else 0
        print(
            f"[Iter {iteration + 1}] {status_name}  |  wall={elapsed:.1f}s  "
            f"|  obj={obj_val:.0f} (scaled*{_OBJ_SCALE})  "
            f"|  remaining={remaining_time:.1f}s"
        )

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if best_connected_f_vals is not None:
                print("  Using best connected solution from previous iteration.")
                f_vals = best_connected_f_vals
                clean_vals = best_connected_clean_vals
                status_name = best_connected_status
                break
            return None, None, None, status_name

        # Extract current solution
        cand_f_vals = {
            (a, k): solver.value(f[a, k])
            for k in range(C) for a in range(A)
        }
        cand_clean_vals = {}
        for j in range(M):
            for k in range(C):
                v = clean[j, k]
                cand_clean_vals[j, k] = (
                    solver.value(v) if isinstance(v, cp_model.IntVar) else 0
                )

        # ---- Subtour elimination -------------------------------------------
        subtours_found = _eliminate_subtours(
            model, f, cand_f_vals, arcs, arc_max, A, C, S,
        )

        if not subtours_found:
            print("  No subtours - all vehicle flows are connected.")
            f_vals = cand_f_vals
            clean_vals = cand_clean_vals
            best_connected_f_vals = cand_f_vals
            best_connected_clean_vals = cand_clean_vals
            best_connected_status = status_name
            break

        if remaining_time <= 2.0:
            print("  [Warning] Time budget exhausted during subtour elimination.")
            if best_connected_f_vals is not None:
                print("  Returning last connected solution.")
                f_vals = best_connected_f_vals
                clean_vals = best_connected_clean_vals
                status_name = best_connected_status
                break

            print("  No connected solution found within time budget.")
            return None, None, None, status_name

        # Hint solver with current solution for faster re-solve
        if hasattr(model, "clear_hints"):
            model.clear_hints()
        for k in range(C):
            for a in range(A):
                model.add_hint(f[a, k], cand_f_vals[a, k])
            for j in range(M):
                if isinstance(clean[j, k], cp_model.IntVar):
                    model.add_hint(clean[j, k], cand_clean_vals[j, k])

    if f_vals is None and remaining_time > 2.0:
        print(
            f"  [Warning] Iteration limit reached ({max_iterations}) "
            "before finding a connected solution."
        )
        return None, None, None, status_name

    return (
        f_vals,
        clean_vals,
        (arcs, out_arcs, in_arcs, street_arcs, arc_cost),
        status_name,
    )


def _eliminate_subtours(model, f, f_vals, arcs, arc_max, A, C, S):
    """
    Detect and cut disconnected subtours for every vehicle.

    Returns ``True`` if at least one subtour constraint was added.
    """
    subtours_found = False

    for k in range(C):
        total_used = sum(f_vals[a, k] for a in range(A))
        if total_used == 0:
            continue

        adj_k = build_adj_multigraph(k, f_vals, arcs)
        comps = connected_components(adj_k)

        for comp in comps:
            if S in comp:
                continue

            internal = [
                a for a in range(A)
                if arcs[a][0] in comp and arcs[a][1] in comp
            ]
            entering = [
                a for a in range(A)
                if arcs[a][0] not in comp and arcs[a][1] in comp
            ]
            if not internal:
                continue

            if entering:
                big_M_sub = sum(arc_max[a] for a in internal) + 1
                model.add(
                    sum(f[a, k] for a in internal)
                    <= big_M_sub * sum(f[a, k] for a in entering)
                )
            else:
                for a in internal:
                    model.add(f[a, k] == 0)

            subtours_found = True
            print(f"  [Subtour] Vehicle {k}: eliminated component {comp}")

    return subtours_found
