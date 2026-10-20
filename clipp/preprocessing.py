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


def precompute_score_gain(instance):
    """Score contribution for each eligible street/vehicle pair, in a flat array.

    No hash tables, heaps, or trees are used. Unavailable pairs have -inf.
    """
    streets = instance.streets
    vehicle_types = instance.vehicle_types
    count = len(vehicle_types)
    max_id = max((street.id for street in streets), default=-1)
    gains = array('d', [float('-inf')]) * ((max_id + 1) * count)
    eligible = [s for s in streets if s.category in ('M', 'O')]
    max_length = sum(s.length for s in eligible)
    max_waste = sum((30 - s.requirement) * s.length / 1000 for s in eligible)
    alpha = instance.water_waste_penalty
    for street in eligible:
        coverage = alpha * street.length / max_length if max_length > 0 else 0.0
        for vehicle_id, kind in enumerate(vehicle_types):
            if kind == 'S':
                capacity = 10
            elif kind == 'M':
                capacity = 20
            elif kind == 'L':
                capacity = 30
            else:
                raise ValueError(f'Unknown vehicle type: {kind}')
            if capacity < street.requirement:
                continue
            waste = (capacity - street.requirement) * street.length / 1000
            penalty = (1 - alpha) * waste / max_waste if max_waste > 0 else 0.0
            gains[street.id * count + vehicle_id] = coverage - penalty
    return gains


def precompute_capacity_gains(instance):
    """Flat score-gain table indexed by street ID and S/M/L capacity slot.

    Pure array-based preprocessing.  Mandatory streets retain a positive
    progress priority in the search layer regardless of their score gain.
    """
    eligible = [s for s in instance.streets if s.category in ("M", "O")]
    total_length = sum(s.length for s in eligible)
    max_waste = sum((30 - s.requirement) * s.length / 1000 for s in eligible)
    alpha = instance.water_waste_penalty
    count = max((s.id for s in instance.streets), default=-1) + 1
    result = array("d", [float("-inf")]) * (count * 3)
    for street in eligible:
        coverage = alpha * street.length / total_length if total_length else 0.0
        for slot, capacity in enumerate((10, 20, 30)):
            if capacity < street.requirement:
                continue
            waste = (capacity - street.requirement) * street.length / 1000
            penalty = ((1 - alpha) * waste / max_waste) if max_waste else 0.0
            result[street.id * 3 + slot] = coverage - penalty
    return result


def rank_mandatory_candidates(found, gains, capacity, width):
    """Rank already feasible mandatory candidates by precomputed score/time.

    `found` entries are (approach_time, street_id, exit, entry, street_time).
    All entries must already satisfy time/depot/capacity constraints.
    """
    if width <= 0:
        return []
    slot = capacity // 10 - 1
    if slot not in (0, 1, 2):
        return sorted(found, key=lambda x: (x[0], x[1], x[2], x[3]))[:width]
    return sorted(
        found,
        key=lambda x: (
            -(1.0 + gains[x[1] * 3 + slot]) / max(1, x[0] + x[4]),
            x[0], x[1], x[2], x[3],
        ),
    )[:width]


def choose_optional_depot_trip(instance, pre, routes, cleaned, gain_table):
    """Select a score-positive feasible optional depot excursion using arrays only.

    Returns (route_index, street_id, entry, exit) or None. This is a
    preprocessing-driven postprocessing choice, not a change to recursion.
    """
    if pre is None:
        return None
    n = pre.num_junctions
    depot = instance.depot
    outward = pre.offset(depot)
    best = None
    best_density = 0.0
    for street in instance.streets:
        if street.category != 'O' or cleaned[street.id]:
            continue
        for route_index, route in enumerate(routes):
            if route.capacity < street.requirement:
                continue
            slot = route.capacity // 10 - 1
            gain = gain_table[street.id * 3 + slot]
            if gain <= 1e-14:
                continue
            for entry, exit in ((street.a, street.b), (street.b, street.a)):
                if entry == street.b and street.direction != 2:
                    continue
                to_entry = pre.distances[outward + entry]
                home = pre.distances[pre.offset(exit) + depot]
                if to_entry == INF or home == INF:
                    continue
                added = to_entry + street.time + home
                if route.total_time + added > instance.max_time:
                    continue
                density = gain / max(1, added)
                key = (added, route.capacity, street.id, route_index)
                if density > best_density + 1e-16 or (abs(density - best_density) <= 1e-16 and (best is None or key < best[0])):
                    best_density = density
                    best = (key, route_index, street.id, entry, exit)
    return None if best is None else best[1:]
