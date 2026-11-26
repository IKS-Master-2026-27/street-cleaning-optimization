"""
Route reconstruction from CP-SAT arc-flow solutions.

Builds junction-sequence routes for each vehicle via Hierholzer's algorithm,
with connectivity repair (bridge insertion) when needed.
"""

import collections

from .graph import (
    build_adj_multigraph,
    connected_components,
    shortest_path_nodes,
)

__all__ = ["reconstruct_route"]


def reconstruct_route(
    k: int,
    f_vals: dict,
    arcs: list,
    instance: dict,
    adj_weighted: dict,
) -> tuple[list[int], set[int]]:
    """
    Build the actual junction-sequence route for vehicle *k*.

    Steps
    -----
    1. Build multigraph from *f_vals*.
    2. Detect components; bridge any that miss the depot (if time allows).
    3. Run Hierholzer's algorithm.

    Parameters
    ----------
    k : int
        Vehicle index.
    f_vals : dict
        Arc-flow solution ``{(arc_idx, vehicle_idx): int}``.
    arcs : list
        Directed arcs ``[(u, v, street_id), ...]``.
    instance : dict
        Parsed instance.
    adj_weighted : dict
        Weighted adjacency list for shortest-path queries.

    Returns
    -------
    route : list[int]
        Junction sequence (starts and ends at depot).
    dropped_streets : set[int]
        Streets whose arcs were removed (unreachable / over-budget).
    """
    depot = instance["S"]
    T     = instance["T"]

    adj        = build_adj_multigraph(k, f_vals, arcs)
    total_used = sum(f_vals[a_idx, k] for a_idx in range(len(arcs)))

    if total_used == 0:
        return [depot], set()

    # Current route time (used for budget checks during connectivity repair)
    current_time = sum(
        instance["streets"][arcs[a][2]]["cost"] * f_vals[a, k]
        for a in range(len(arcs))
    )

    dropped_streets: set[int] = set()

    # ---- Connectivity repair -----------------------------------------------
    _repair_connectivity(
        adj, depot, T, current_time, k, f_vals, arcs,
        instance, adj_weighted, dropped_streets,
    )

    # ---- Guard: if depot has no outgoing arcs, nothing to route -------------
    if not adj[depot]:
        return [depot], dropped_streets

    # ---- Eulerian circuit ---------------------------------------------------
    circuit = _hierholzer(adj, depot)

    if not circuit:
        return [depot], dropped_streets
    if circuit[-1] != depot:
        circuit.append(depot)

    return circuit, dropped_streets


# ---------------------------------------------------------------------------
# Hierholzer's algorithm
# ---------------------------------------------------------------------------

def _hierholzer(adj: collections.defaultdict, start: int) -> list[int]:
    """
    Hierholzer's algorithm on a multigraph adjacency dict.

    Modifies *adj* in-place (edge lists are consumed).

    Returns the Eulerian circuit as a node list starting and ending at *start*.
    """
    stack:   list[int] = [start]
    circuit: list[int] = []
    while stack:
        u = stack[-1]
        if adj[u]:
            v = adj[u].pop()[0]
            stack.append(v)
        else:
            circuit.append(stack.pop())
    circuit.reverse()
    return circuit


# ---------------------------------------------------------------------------
# Connectivity repair
# ---------------------------------------------------------------------------

def _repair_connectivity(
    adj, depot, T, current_time, k, f_vals, arcs,
    instance, adj_weighted, dropped_streets,
):
    """
    Bridge isolated components back to the depot when possible; otherwise
    drop their arcs and record affected streets.
    """
    comps = connected_components(adj)

    for comp in comps:
        if depot in comp:
            continue

        # Find cheapest round-trip bridge: depot → best_node_in_comp → depot
        best_cost = float("inf")
        best_path: list[int] = []
        for node in comp:
            c, path = shortest_path_nodes(
                depot, node, adj_weighted, instance["N"],
            )
            if c < best_cost:
                best_cost = c
                best_path = path

        if best_path and 2 * best_cost + current_time <= T:
            # Insert forward path
            for i in range(len(best_path) - 1):
                adj[best_path[i]].append([best_path[i + 1]])
            # Insert backward path
            rev = list(reversed(best_path))
            for i in range(len(rev) - 1):
                adj[rev[i]].append([rev[i + 1]])
            current_time += 2 * best_cost
            print(
                f"  [Repair] Vehicle {k}: bridged isolated component "
                f"(+{2 * best_cost}s, running total {current_time}s)"
            )
        else:
            if not best_path:
                print(
                    f"  [Warning] Vehicle {k}: component {comp} unreachable "
                    f"from depot; dropping its arcs."
                )
            else:
                print(
                    f"  [Warning] Vehicle {k}: bridge cost {2 * best_cost}s "
                    f"would exceed time budget; dropping component {comp}."
                )
            for node in comp:
                adj[node].clear()
            for a_idx, (u, v, j) in enumerate(arcs):
                if u in comp and f_vals[a_idx, k] > 0:
                    dropped_streets.add(j)
