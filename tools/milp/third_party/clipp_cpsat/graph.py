"""
Graph construction and shortest-path utilities for CLIPP.
"""

import collections
import heapq

__all__ = [
    "build_arcs",
    "dijkstra",
    "dijkstra_with_prev",
    "shortest_path_nodes",
    "build_adj_multigraph",
    "connected_components",
]


# ---------------------------------------------------------------------------
# Arc construction
# ---------------------------------------------------------------------------

def build_arcs(instance: dict):
    """
    Create a directed-arc representation of the street network.

    A two-way street *j* produces two arcs at indices ``2j`` and ``2j+1``.

    Parameters
    ----------
    instance : dict
        Parsed instance (as returned by :func:`clipp.parser.parse_instance`).

    Returns
    -------
    arcs : list[tuple[int, int, int]]
        ``(u, v, street_id)`` per directed arc.
    out_arcs : dict[int, list[int]]
        Node → list of arc indices **leaving** that node.
    in_arcs : dict[int, list[int]]
        Node → list of arc indices **entering** that node.
    street_arcs : dict[int, list[int]]
        Street id → list of arc indices belonging to that street.
    arc_cost : list[int]
        Traversal time for each arc (same as its street's cost).
    """
    arcs: list[tuple[int, int, int]] = []
    out_arcs:    dict[int, list[int]] = collections.defaultdict(list)
    in_arcs:     dict[int, list[int]] = collections.defaultdict(list)
    street_arcs: dict[int, list[int]] = collections.defaultdict(list)

    for s in instance["streets"]:
        j = s["id"]
        a, b = s["a"], s["b"]

        # Forward arc
        fwd = len(arcs)
        arcs.append((a, b, j))
        out_arcs[a].append(fwd)
        in_arcs[b].append(fwd)
        street_arcs[j].append(fwd)

        # Backward arc (two-way streets only)
        if s["dir"] == 2:
            bwd = len(arcs)
            arcs.append((b, a, j))
            out_arcs[b].append(bwd)
            in_arcs[a].append(bwd)
            street_arcs[j].append(bwd)

    arc_cost = [
        instance["streets"][arcs[a][2]]["cost"] for a in range(len(arcs))
    ]
    return arcs, out_arcs, in_arcs, street_arcs, arc_cost


# ---------------------------------------------------------------------------
# Dijkstra
# ---------------------------------------------------------------------------

def dijkstra(source: int, adj_weighted: dict, N: int) -> list[float]:
    """
    Standard Dijkstra from *source*.

    Parameters
    ----------
    adj_weighted : dict[int, list[tuple[int, int]]]
        ``adj_weighted[u]`` is a list of ``(v, cost)`` pairs.
    N : int
        Number of nodes (used to size the distance array).

    Returns
    -------
    list[float]
        ``dist[u]`` = shortest time from *source* to *u* (``inf`` if
        unreachable).
    """
    dist = [float("inf")] * N
    dist[source] = 0
    heap = [(0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, c in adj_weighted.get(u, []):
            nd = d + c
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def dijkstra_with_prev(
    source: int, adj_weighted: dict, N: int
) -> tuple[list[float], list[int]]:
    """Dijkstra returning ``(dist, prev)`` for path reconstruction."""
    dist = [float("inf")] * N
    prev = [-1] * N
    dist[source] = 0
    heap = [(0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, c in adj_weighted.get(u, []):
            nd = d + c
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    return dist, prev


def shortest_path_nodes(
    source: int, target: int, adj_weighted: dict, N: int
) -> tuple[float, list[int]]:
    """
    Return ``(cost, [node_sequence])`` for the shortest path from *source* to
    *target*, or ``(inf, [])`` if unreachable.
    """
    dist, prev = dijkstra_with_prev(source, adj_weighted, N)
    if dist[target] == float("inf"):
        return float("inf"), []
    path: list[int] = []
    cur = target
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return dist[target], path


# ---------------------------------------------------------------------------
# Multigraph helpers (used by both model & reconstruction)
# ---------------------------------------------------------------------------

def build_adj_multigraph(
    k: int, f_vals: dict, arcs: list
) -> dict[int, list[list[int]]]:
    """
    Build an adjacency multigraph for vehicle *k* from flow values.

    Each entry ``adj[u]`` is a list of ``[v]`` singletons (one per traversal).
    """
    adj: dict[int, list[list[int]]] = collections.defaultdict(list)
    for a_idx, (u, v, _j) in enumerate(arcs):
        cnt = f_vals[a_idx, k]
        for _ in range(cnt):
            adj[u].append([v])
    return adj


def connected_components(adj: dict) -> list[set[int]]:
    """
    Return weakly-connected components of the directed multigraph *adj*
    (arc direction is ignored for connectivity analysis).
    """
    all_nodes: set[int] = set(adj.keys())
    undirected: dict[int, set[int]] = collections.defaultdict(set)

    for u, edges in adj.items():
        all_nodes.add(u)
        for edge in edges:
            v = edge[0]
            all_nodes.add(v)
            # Weak connectivity: ignore edge direction for component search.
            undirected[u].add(v)
            undirected[v].add(u)

    visited: set[int] = set()
    components: list[set[int]] = []

    for start in all_nodes:
        if start in visited:
            continue
        comp: set[int] = set()
        queue = collections.deque([start])
        comp.add(start)
        visited.add(start)
        while queue:
            u = queue.popleft()
            for v in undirected.get(u, set()):
                if v not in visited:
                    visited.add(v)
                    comp.add(v)
                    queue.append(v)
        components.append(comp)

    return components
