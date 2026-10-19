"""Array-only shortest-path and water-cost preprocessing (no hashes or heaps)."""
from array import array
from dataclasses import dataclass
from .graph import Adjacency

INF = 1 << 62
DEFAULT_MAX_JUNCTIONS = 300

@dataclass
class PreprocessedGraph:
    num_junctions: int
    distances: array
    previous_junction: array
    previous_street: array

    def offset(self, source: int) -> int:
        return source * self.num_junctions


def preprocess_graph(graph: Adjacency, max_junctions: int = DEFAULT_MAX_JUNCTIONS):
    n = len(graph)
    if n == 0 or n > max_junctions:
        return None
    size = n * n
    all_distances = array('q', [INF]) * size
    all_previous_junctions = array('i', [-1]) * size
    all_previous_streets = array('i', [-1]) * size
    for source in range(n):
        distances = [INF] * n
        previous = [-1] * n
        previous_street = [-1] * n
        visited = bytearray(n)
        distances[source] = 0
        for _ in range(n):
            current = -1
            for node in range(n):
                if not visited[node] and (current == -1 or distances[node] < distances[current]):
                    current = node
            if current < 0 or distances[current] == INF:
                break
            visited[current] = 1
            for edge in graph[current]:
                target = edge.destination
                candidate = distances[current] + edge.time
                if candidate < distances[target]:
                    distances[target] = candidate
                    previous[target] = current
                    previous_street[target] = edge.street_id
        row = source * n
        all_distances[row:row+n] = array('q', distances)
        all_previous_junctions[row:row+n] = array('i', previous)
        all_previous_streets[row:row+n] = array('i', previous_street)
    return PreprocessedGraph(n, all_distances, all_previous_junctions, all_previous_streets)


def candidate_junctions(streets, num_junctions: int) -> list[int]:
    marked = bytearray(num_junctions)
    for street in streets:
        marked[street.a] = 1
        if street.direction == 2:
            marked[street.b] = 1
    return [i for i in range(num_junctions) if marked[i]]


def precompute_water_waste(streets, vehicle_types):
    """Flat array indexed by street.id * vehicle_count + vehicle_id."""
    vehicle_count = len(vehicle_types)
    size = (max((street.id for street in streets), default=-1) + 1) * vehicle_count
    result = array('d', [float('inf')]) * size
    for street in streets:
        for vehicle_id, kind in enumerate(vehicle_types):
            if kind == 'S':
                capacity = 10
            elif kind == 'M':
                capacity = 20
            elif kind == 'L':
                capacity = 30
            else:
                raise ValueError(f'Unknown vehicle type: {kind}')
            if capacity >= street.requirement:
                result[street.id * vehicle_count + vehicle_id] = (
                    (capacity - street.requirement) * street.length / 1000
                )
    return result
