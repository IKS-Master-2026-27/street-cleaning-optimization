"""Shortest-path oracle: cached Dijkstra trees, reverse tree to the depot."""

from collections import OrderedDict
from heapq import heappop, heappush

from .io import Problem

INF = 1 << 60


class Network:
    def __init__(self, problem: Problem) -> None:
        n = problem.num_junctions
        self.n = n
        self.out: list[list[tuple[int, int, int]]] = [[] for _ in range(n)]
        self.rev: list[list[tuple[int, int, int]]] = [[] for _ in range(n)]
        for j in range(problem.num_streets):
            a, b, t = problem.a[j], problem.b[j], problem.time[j]
            self.out[a].append((b, t, j))
            self.rev[b].append((a, t, j))
            if problem.direction[j] == 2:
                self.out[b].append((a, t, j))
                self.rev[a].append((b, t, j))
        for edges in self.out:
            edges.sort(key=lambda e: (e[1], e[2]))
        for edges in self.rev:
            edges.sort(key=lambda e: (e[1], e[2]))

    def tree(self, source: int, reverse: bool = False):
        """Full Dijkstra. Returns (dist, parent_node, parent_street).

        With reverse=True distances are *to* source and parent pointers give the
        next node/street on a shortest path towards source.
        """
        adjacency = self.rev if reverse else self.out
        dist = [INF] * self.n
        parent = [-1] * self.n
        street = [-1] * self.n
        dist[source] = 0
        heap = [(0, source)]
        while heap:
            d, u = heappop(heap)
            if d != dist[u]:
                continue
            for v, t, j in adjacency[u]:
                nd = d + t
                if nd < dist[v]:
                    dist[v] = nd
                    parent[v] = u
                    street[v] = j
                    heappush(heap, (nd, v))
        return dist, parent, street


class Oracle:
    """Distances d(u, v) and shortest paths, with an LRU cache of Dijkstra trees."""

    def __init__(self, problem: Problem, network: Network | None = None,
                 cache_entries: int | None = None) -> None:
        self.problem = problem
        self.net = network or Network(problem)
        n = self.net.n
        if cache_entries is None:
            cache_entries = n if n <= 2000 else max(16, 20_000_000 // max(1, n))
        self.cache_entries = cache_entries
        self._trees: OrderedDict[int, tuple] = OrderedDict()
        self.depot = problem.depot
        self.dijkstra_runs = 0
        self.from_depot = self._tree(self.depot)
        self.to_depot = self.net.tree(self.depot, reverse=True)
        self.dijkstra_runs += 1

    def _tree(self, source: int):
        tree = self._trees.get(source)
        if tree is not None:
            self._trees.move_to_end(source)
            return tree
        tree = self.net.tree(source)
        self.dijkstra_runs += 1
        self._trees[source] = tree
        if len(self._trees) > self.cache_entries:
            self._trees.popitem(last=False)
        return tree

    def d(self, u: int, v: int) -> int:
        if u == v:
            return 0
        if v == self.depot:
            return self.to_depot[0][u]
        if u == self.depot:
            return self.from_depot[0][v]
        return self._tree(u)[0][v]

    def dist_row(self, u: int) -> list[int]:
        return self._tree(u)[0]

    def path(self, u: int, v: int) -> tuple[list[int], list[int]]:
        """Shortest path u -> v as (nodes incl. both ends, streets)."""
        if u == v:
            return [u], []
        if v == self.depot:
            return self.path_to_depot(u)
        dist, parent, street = self.from_depot if u == self.depot else self._tree(u)
        if dist[v] >= INF:
            raise ValueError(f"junction {v} unreachable from {u}")
        nodes, streets = [v], []
        x = v
        while x != u:
            streets.append(street[x])
            x = parent[x]
            nodes.append(x)
        nodes.reverse()
        streets.reverse()
        return nodes, streets

    def path_to_depot(self, u: int) -> tuple[list[int], list[int]]:
        dist, nxt, street = self.to_depot
        if dist[u] >= INF:
            raise ValueError(f"depot unreachable from {u}")
        nodes, streets = [u], []
        x = u
        while x != self.depot:
            streets.append(street[x])
            x = nxt[x]
            nodes.append(x)
        return nodes, streets
