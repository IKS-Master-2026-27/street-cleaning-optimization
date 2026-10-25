"""Provable upper bound on the optimal score (Theorem 3 in the proposal).

Score = (1 - alpha) + sum_{cleaned j} delta(j, q_j). Every cleaned street is
traversed at least once (t_j seconds) and the whole fleet has C * T seconds.
Streets that no single depot -> street -> depot trip can serve within T can
never be cleaned. Hence

  UB = (1 - alpha) + sum_{j in M} delta*_j
       + fractional knapsack over {j in O : delta*_j > 0, servable}
         with capacity C*T - sum_{j in M} t_j,

where delta*_j is the best contribution over vehicle types in the fleet.
"""

from .distances import Oracle
from .io import Problem
from .tour import orientations, servable


def upper_bound(problem: Problem, oracle: Oracle) -> float:
    total = 1.0 - problem.alpha
    capacity = problem.num_vehicles * problem.time_limit
    items = []
    for j in range(problem.num_streets):
        if problem.category[j] == "C":
            continue
        best = problem.best_delta(j)
        if best is None:
            continue
        if not any(servable(problem, oracle, oid) for oid in orientations(problem, j)):
            continue
        if problem.category[j] == "M":
            total += best
            capacity -= problem.time[j]
        elif best > 0:
            items.append((best / problem.time[j], best, problem.time[j]))
    items.sort(reverse=True)
    for _, value, weight in items:
        if capacity <= 0:
            break
        take = min(1.0, capacity / weight)
        total += take * value
        capacity -= weight
    return min(1.0, total)
