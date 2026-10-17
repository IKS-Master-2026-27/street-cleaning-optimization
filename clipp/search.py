
from dataclasses import dataclass
from heapq import heappop, heappush

from .graph import build_graph, shortest_path
from .parser import Instance, Street
from .solver import VEHICLE_CAPACITIES, VehicleRoute, depot_return_times

ELIGIBLE = frozenset({"M", "O"})
MAX_CAPACITY = 30
_INFINITY = float("inf")


@dataclass(frozen=True)
class ScoreModel:

    alpha: float
    l_max: int
    w_max: float

    @classmethod
    def from_instance(cls, instance: Instance) -> "ScoreModel":
        eligible = [s for s in instance.streets if s.category in ELIGIBLE]
        l_max = sum(street.length for street in eligible)
        w_max = sum((MAX_CAPACITY - street.requirement) * (street.length / 1000)
                    for street in eligible)
        # The parser keeps alpha in the historical `water_waste_penalty` field.
        return cls(instance.water_waste_penalty, l_max, w_max)

    def gain(self, street: Street, capacity: int) -> float:
        coverage = (self.alpha * street.length / self.l_max
                    if self.l_max > 0 else 0.0)
        if self.w_max <= 0:
            return coverage
        waste = (capacity - street.requirement) * (street.length / 1000)
        return coverage - (1.0 - self.alpha) * waste / self.w_max


@dataclass(frozen=True)
class Move:

    approach: int
    street: Street
    entry: int
    exit: int
    gain: float
    value: float
    junctions: tuple
    street_ids: tuple

    @property
    def time(self) -> int:
        return self.approach + self.street.time

    @property
    def density(self) -> float:
        total = self.time
        return self.value / total if total else 0.0

    def order_key(self) -> tuple:
        return (self.approach, self.street.id, self.exit)


@dataclass(frozen=True)
class Commit:

    junctions: int
    street_ids: int
    total_time: int
    current: int
    cleaned: tuple
    forced: bool
    gain: float


class SearchSpace:

    def __init__(self, instance: Instance, model: ScoreModel | None = None,
                 probe_radius: int | None = None,
                 radius_growth: int = 8) -> None:
        self.instance = instance
        self.graph = build_graph(instance)
        self.dist_depot = depot_return_times(instance)
        self.model = model or ScoreModel.from_instance(instance)
        self.streets_by_id = {street.id: street for street in instance.streets}
        self.cleaned: set[int] = set()
        self.mandatory_pending: set[int] = set()
        self.pending_at: dict[int, list[int]] = {}
        self.pending_by_capacity = {capacity: 0 for capacity in (10, 20, 30)}
        self.probes = 0
        self.popped = 0
        self._exhausted: set[int] = set()

        times = []
        for street in instance.streets:
            times.append(street.time)
            if street.category not in ELIGIBLE:
                continue
            self._index(street)
            if street.category == "M":
                self.mandatory_pending.add(street.id)
            for capacity in self.pending_by_capacity:
                if capacity >= street.requirement:
                    self.pending_by_capacity[capacity] += 1
        average = sum(times) / len(times) if times else 1.0
        self.probe_radius = (max(1, int(4 * average)) if probe_radius is None
                             else max(0, probe_radius))
        self.radius_growth = max(2, radius_growth)

    def new_routes(self) -> list[VehicleRoute]:
        depot = self.instance.depot
        return [
            VehicleRoute(
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                capacity=VEHICLE_CAPACITIES[vehicle_type],
                current_junction=depot,
                junctions=[depot],
            )
            for vehicle_id, vehicle_type in enumerate(self.instance.vehicle_types)
        ]

    def _index(self, street: Street) -> None:
        self.pending_at.setdefault(street.a, []).append(street.id)
        if street.direction == 2 and street.b != street.a:
            self.pending_at.setdefault(street.b, []).append(street.id)

    def _unindex(self, street: Street) -> None:
        for node in (street.a, street.b):
            bucket = self.pending_at.get(node)
            if bucket is not None and street.id in bucket:
                bucket.remove(street.id)
                if not bucket:
                    del self.pending_at[node]

    def _accept(self, street: Street, capacity: int, exclude) -> bool:
        if capacity < street.requirement:
            return False
        if street.id in self.cleaned or street.id in exclude:
            return False
        return street.category == "M"

    def _value(self, street: Street, capacity: int) -> tuple:
        # Mandatory coverage is a hard constraint, so one clean is worth one
        # unit of progress and the score gain only breaks ties.
        gain = self.model.gain(street, capacity)
        return gain, 1.0 + gain

    def probe(self, junction: int, capacity: int, elapsed: int,
              width: int = 1, exclude=frozenset()) -> list:
        if self.pending_by_capacity.get(capacity, 0) <= 0:
            return []
        fresh = junction == self.instance.depot and elapsed == 0
        if fresh and capacity in self._exhausted:
            return []
        moves = self._grow(junction, capacity, elapsed, width, exclude)
        if not moves and fresh and not exclude:
            self._exhausted.add(capacity)
        return moves

    def _grow(self, junction: int, capacity: int, elapsed: int,
              width: int, exclude) -> list:
        ceiling = self.instance.max_time - elapsed
        if ceiling <= 0:
            return []
        radius = min(self.probe_radius, ceiling)
        while True:
            moves = self._dijkstra(junction, capacity, elapsed, width,
                                   exclude, radius)
            if moves or radius >= ceiling:
                return moves
            radius = min(radius * self.radius_growth, ceiling)

    def _dijkstra(self, source: int, capacity: int, elapsed: int,
                  width: int, exclude, radius: int) -> list:
        self.probes += 1
        graph = self.graph
        dist_depot = self.dist_depot
        streets = self.streets_by_id
        pending_at = self.pending_at
        max_time = self.instance.max_time
        accept = self._accept

        distances = {source: 0}
        previous: dict[int, tuple] = {}
        queue = [(0, source)]
        found: list[tuple] = []
        limit = radius

        while queue:
            reach, node = heappop(queue)
            if reach != distances.get(node):
                continue
            if reach > limit:
                break
            self.popped += 1
            bucket = pending_at.get(node)
            if bucket:
                for street_id in bucket:
                    street = streets[street_id]
                    if not accept(street, capacity, exclude):
                        continue
                    end = street.b if street.a == node else street.a
                    home = dist_depot.get(end)
                    if home is None:
                        continue
                    if elapsed + reach + street.time + home > max_time:
                        continue
                    found.append((reach, street_id, end, node))
                if len(found) >= width:
                    found.sort()
                    del found[width:]
                    limit = min(limit, found[-1][0])
            for edge in graph[node]:
                step = reach + edge.time
                if step > limit:
                    continue
                home = dist_depot.get(edge.destination)
                if home is None or elapsed + step + home > max_time:
                    continue
                if step < distances.get(edge.destination, _INFINITY):
                    distances[edge.destination] = step
                    previous[edge.destination] = (node, edge.street_id)
                    heappush(queue, (step, edge.destination))

        found.sort()
        del found[width:]
        moves = []
        for reach, street_id, end, entry in found:
            junctions = [entry]
            street_ids: list[int] = []
            node = entry
            while node != source:
                node, traversed = previous[node]
                junctions.append(node)
                street_ids.append(traversed)
            street = streets[street_id]
            gain, value = self._value(street, capacity)
            moves.append(Move(reach, street, entry, end, gain, value,
                              tuple(reversed(junctions)),
                              tuple(reversed(street_ids))))
        return moves

    def find_moves(self, route: VehicleRoute, width: int = 1,
                   exclude=frozenset()) -> list:
        return self.probe(route.current_junction, route.capacity,
                          route.total_time, width, exclude)

    def _clean(self, route: VehicleRoute, street: Street,
               cleaned: list[int]) -> float:
        route.cleaned_street_ids.append(street.id)
        cleaned.append(street.id)
        self.cleaned.add(street.id)
        self.mandatory_pending.discard(street.id)
        self._unindex(street)
        for capacity in self.pending_by_capacity:
            if capacity >= street.requirement:
                self.pending_by_capacity[capacity] -= 1
        return self.model.gain(street, route.capacity)

    def commit(self, route: VehicleRoute, move: Move) -> Commit:
        token_junctions = len(route.junctions)
        token_streets = len(route.street_ids)
        token_time = route.total_time
        token_current = route.current_junction
        cleaned: list[int] = []

        route.junctions.extend(move.junctions[1:])
        route.street_ids.extend(move.street_ids)
        route.junctions.append(move.exit)
        route.street_ids.append(move.street.id)
        route.total_time += move.time
        route.current_junction = move.exit

        gain, forced = 0.0, False
        if move.street.id not in self.cleaned:
            gain = self._clean(route, move.street, cleaned)
            forced = move.street.category == "M"
        return Commit(token_junctions, token_streets, token_time, token_current,
                      tuple(cleaned), forced, gain)

    def rollback(self, route: VehicleRoute, token: Commit) -> None:
        for street_id in reversed(token.cleaned):
            street = self.streets_by_id[street_id]
            route.cleaned_street_ids.remove(street_id)
            self.cleaned.discard(street_id)
            if street.category == "M":
                self.mandatory_pending.add(street_id)
            self._index(street)
            for capacity in self.pending_by_capacity:
                if capacity >= street.requirement:
                    self.pending_by_capacity[capacity] += 1
        del route.junctions[token.junctions:]
        del route.street_ids[token.street_ids:]
        route.total_time = token.total_time
        route.current_junction = token.current

    def close(self, route: VehicleRoute) -> None:
        depot = self.instance.depot
        if route.current_junction == depot:
            return
        home = shortest_path(self.graph, route.current_junction, depot)
        if home is None:
            raise ValueError(f"Vehicle {route.vehicle_id} cannot return to depot")
        if route.total_time + home.total_time > self.instance.max_time:
            raise ValueError(f"Vehicle {route.vehicle_id} cannot return in time")
        route.junctions.extend(home.junctions[1:])
        route.street_ids.extend(home.street_ids)
        route.total_time += home.total_time
        route.current_junction = depot

    def sweep_traversed(self, routes) -> None:
        # After the routes are closed, clean the eligible streets they already
        # drive over; an optional street only when it raises the score.
        for route in sorted(routes, key=lambda r: (r.capacity, r.vehicle_id)):
            for street_id in sorted(set(route.street_ids)):
                street = self.streets_by_id[street_id]
                if street.id in self.cleaned or street.category not in ELIGIBLE:
                    continue
                if route.capacity < street.requirement:
                    continue
                if (street.category != "M"
                        and self.model.gain(street, route.capacity) <= 0.0):
                    continue
                self._clean(route, street, [])

    def repair_mandatory(self, routes) -> list:
        failures = []
        for street_id in sorted(self.mandatory_pending):
            street = self.streets_by_id[street_id]
            best = None
            for route in sorted(routes, key=lambda r: (r.capacity, r.vehicle_id)):
                if route.capacity < street.requirement:
                    continue
                moves = self.probe(route.current_junction, route.capacity,
                                   route.total_time, 1,
                                   exclude=frozenset(
                                       self.mandatory_pending - {street_id}))
                for move in moves:
                    if move.street.id != street_id:
                        continue
                    key = (move.time, route.capacity, route.vehicle_id)
                    if best is None or key < best[0]:
                        best = (key, route, move)
            if best is None:
                failures.append(street_id)
                continue
            _, route, move = best
            self.commit(route, move)
        return failures
