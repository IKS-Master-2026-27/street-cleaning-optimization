"""Depot-centred shortest travel times shared by validation and features."""

from dataclasses import dataclass
from heapq import heappop, heappush
from math import inf

from .model import Instance, Street


@dataclass(frozen=True, slots=True)
class DepotDistances:
    """Shortest travel times from the depot and back to it for every junction.

    ``outbound[v]`` is the fastest time depot -> v and ``inbound[v]`` the
    fastest time v -> depot. Unreachable junctions hold ``math.inf``.
    """

    outbound: tuple[float, ...]
    inbound: tuple[float, ...]

    def round_trip_time(self, street: Street) -> float:
        """Fastest depot -> traverse ``street`` -> depot time in seconds.

        Two-way streets may be traversed in either orientation; the better one
        is returned. ``math.inf`` means no closed route can contain the street.
        """

        best = self.outbound[street.start] + street.travel_time + self.inbound[street.end]
        if street.direction == 2:
            reverse = (
                self.outbound[street.end]
                + street.travel_time
                + self.inbound[street.start]
            )
            best = min(best, reverse)
        return best


def _dijkstra(start: int, adjacency: list[list[tuple[int, int]]]) -> tuple[float, ...]:
    distance = [inf] * len(adjacency)
    distance[start] = 0.0
    heap = [(0.0, start)]
    while heap:
        current, node = heappop(heap)
        if current > distance[node]:
            continue
        for neighbor, weight in adjacency[node]:
            candidate = current + weight
            if candidate < distance[neighbor]:
                distance[neighbor] = candidate
                heappush(heap, (candidate, neighbor))
    return tuple(distance)


def depot_distances(instance: Instance) -> DepotDistances:
    """Compute depot distances in O((N + M) log N) time and O(N + M) memory.

    Street records with out-of-range endpoints, invalid directions or
    non-positive travel times are skipped so that validation can report them
    separately instead of failing here.
    """

    n = instance.num_junctions
    forward: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    reverse: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for street in instance.streets:
        if not (0 <= street.start < n and 0 <= street.end < n):
            continue
        if street.direction not in (1, 2) or street.travel_time <= 0:
            continue
        forward[street.start].append((street.end, street.travel_time))
        reverse[street.end].append((street.start, street.travel_time))
        if street.direction == 2:
            forward[street.end].append((street.start, street.travel_time))
            reverse[street.start].append((street.end, street.travel_time))
    return DepotDistances(
        outbound=_dijkstra(instance.depot, forward),
        inbound=_dijkstra(instance.depot, reverse),
    )
