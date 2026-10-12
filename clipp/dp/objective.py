"""Route model, independent validator (per the official statement) and score."""

from dataclasses import dataclass, field

from ..solver import Solution, VehicleRoute
from .io import Problem


@dataclass
class Route:
    vehicle: int
    capacity: int
    nodes: list[int]
    streets: list[int] = field(default_factory=list)
    cleaned: list[int] = field(default_factory=list)

    def duration(self, problem: Problem) -> int:
        return sum(problem.time[j] for j in self.streets)


@dataclass(frozen=True)
class Evaluation:
    score: float
    coverage: float
    efficiency: float
    cleaned_length: int
    waste: float
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def evaluate(problem: Problem, routes: list[Route]) -> Evaluation:
    """Validate literally against the statement's rules and compute the score."""
    errors: list[str] = []
    if len(routes) != problem.num_vehicles:
        errors.append(f"expected {problem.num_vehicles} routes, got {len(routes)}")
    cleaned: set[int] = set()
    waste = 0.0
    for v, route in enumerate(routes):
        label = f"vehicle {v}"
        if route.capacity != problem.capacities[v]:
            errors.append(f"{label}: capacity mismatch")
        if not route.nodes or route.nodes[0] != problem.depot or route.nodes[-1] != problem.depot:
            errors.append(f"{label}: must start and end at depot")
        if len(route.streets) != len(route.nodes) - 1:
            errors.append(f"{label}: {len(route.streets)} streets for {len(route.nodes)} nodes")
        traversed = set()
        total = 0
        for k, j in enumerate(route.streets):
            if not 0 <= j < problem.num_streets:
                errors.append(f"{label}: unknown street {j}")
                continue
            u, w = route.nodes[k], route.nodes[k + 1]
            forward = (u, w) == (problem.a[j], problem.b[j])
            backward = problem.direction[j] == 2 and (u, w) == (problem.b[j], problem.a[j])
            if not (forward or backward):
                errors.append(f"{label}: illegal move {u}->{w} on street {j}")
            traversed.add(j)
            total += problem.time[j]
        if total > problem.time_limit:
            errors.append(f"{label}: time {total} > {problem.time_limit}")
        for j in route.cleaned:
            if j not in traversed:
                errors.append(f"{label}: cleans untraversed street {j}")
            elif problem.category[j] == "C":
                errors.append(f"{label}: cleans connector {j}")
            elif route.capacity < problem.requirement[j]:
                errors.append(f"{label}: capacity too low for street {j}")
            else:
                cleaned.add(j)
                waste += (route.capacity - problem.requirement[j]) * problem.length[j] / 1000
    missing = [j for j in range(problem.num_streets)
               if problem.category[j] == "M" and j not in cleaned]
    if missing:
        errors.append(f"{len(missing)} mandatory streets not cleaned (first: {missing[:10]})")
    length = sum(problem.length[j] for j in cleaned)
    coverage = length / problem.l_max if problem.l_max > 0 else 0.0
    efficiency = 1.0 - waste / problem.w_max if problem.w_max > 0 else 1.0
    score = problem.alpha * coverage + (1.0 - problem.alpha) * efficiency
    return Evaluation(score, coverage, efficiency, length, waste, tuple(errors))


def read_solution(problem: Problem, path) -> list[Route]:
    """Read a submission file (repository/official convention: n = number of moves)."""
    edge: dict[tuple[int, int], int] = {}
    for j in range(problem.num_streets):
        edge[(problem.a[j], problem.b[j])] = j
        if problem.direction[j] == 2:
            edge[(problem.b[j], problem.a[j])] = j
    with open(path, encoding="utf-8") as source:
        lines = source.read().split("\n")
    count = int(lines[0])
    routes, row = [], 1
    for v in range(count):
        nodes = list(map(int, lines[row + 1].split()))
        cleaned = list(map(int, lines[row + 2].split()))
        row += 3
        streets = [edge.get((u, w), -1) for u, w in zip(nodes, nodes[1:])]
        routes.append(Route(v, problem.capacities[v], nodes, streets, cleaned))
    return routes


def additive_score(problem: Problem, routes: list[Route]) -> float:
    """Score via the additive identity (1 - alpha) + sum of delta (no duplicates)."""
    total = 1.0 - problem.alpha
    for route in routes:
        for j in route.cleaned:
            total += problem.delta(j, route.capacity)
    return total


def to_repo_solution(problem: Problem, routes: list[Route]) -> Solution:
    """Convert to the repository's Solution so validator.py/scoring.py/output.py apply."""
    return Solution([
        VehicleRoute(
            vehicle_id=v,
            vehicle_type=problem.fleet[v],
            capacity=route.capacity,
            current_junction=route.nodes[-1],
            junctions=list(route.nodes),
            total_time=route.duration(problem),
            street_ids=list(route.streets),
            cleaned_street_ids=list(route.cleaned),
        )
        for v, route in enumerate(routes)
    ])
