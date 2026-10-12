"""Tolerant instance reader and the problem model used by the DP solvers.

Accepts both input layouts: with the N coordinate lines described in the
official statement, and without them (as in the repository's instances).
"""

from dataclasses import dataclass, field
from pathlib import Path

CAPACITY = {"S": 10, "M": 20, "L": 30}
TYPE_OF_CAPACITY = {10: "S", 20: "M", 30: "L"}


@dataclass
class Problem:
    num_junctions: int
    num_streets: int
    time_limit: int
    num_vehicles: int
    depot: int
    alpha: float
    a: list[int]
    b: list[int]
    direction: list[int]
    time: list[int]
    length: list[int]
    category: list[str]
    requirement: list[int]
    fleet: list[str]
    coords: list[tuple[float, float]] | None = None
    name: str = "instance"
    l_max: float = 0.0
    w_max: float = 0.0
    capacities: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.capacities = [CAPACITY[v] for v in self.fleet]
        self.l_max = float(sum(self.length[j] for j in range(self.num_streets)
                               if self.category[j] != "C"))
        self.w_max = sum((30 - self.requirement[j]) * self.length[j] / 1000
                         for j in range(self.num_streets) if self.category[j] != "C")

    def cleanable(self, j: int) -> bool:
        return self.category[j] != "C"

    def delta(self, j: int, capacity: int) -> float | None:
        """Exact score contribution of cleaning street j with this capacity.

        Score = (1 - alpha) + sum of delta over cleaned streets (each once).
        None means the street cannot be cleaned by this capacity.
        """
        if self.category[j] == "C" or capacity < self.requirement[j]:
            return None
        coverage = self.alpha * self.length[j] / self.l_max if self.l_max > 0 else 0.0
        waste = 0.0
        if self.w_max > 0:
            waste = ((1.0 - self.alpha) * (capacity - self.requirement[j])
                     * self.length[j] / 1000 / self.w_max)
        return coverage - waste

    def fleet_capacities(self) -> list[int]:
        return sorted(set(self.capacities))

    def best_delta(self, j: int) -> float | None:
        """Best contribution of street j over vehicle types present in the fleet."""
        values = [d for q in self.fleet_capacities()
                  if (d := self.delta(j, q)) is not None]
        return max(values) if values else None


def instance_name(path: str | Path) -> str:
    path = Path(path)
    return path.parent.name if path.stem == "instance" else path.stem


def read_problem(path: str | Path) -> Problem:
    with open(path, encoding="utf-8") as source:
        lines = [line for line in source.read().split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    try:
        n, m, t, c, s = map(int, lines[0].split()[:5])
        alpha = float(lines[0].split()[5])
    except (ValueError, IndexError) as exc:
        raise ValueError("Invalid header: expected N M T C S alpha") from exc

    row = 1
    coords = None
    # Official layout has N coordinate lines (2 numbers) before the streets.
    if len(lines) > row and len(lines[row].split()) == 2:
        coords = []
        for i in range(n):
            x, y = lines[row + i].split()
            coords.append((float(x), float(y)))
        row += n

    a, b, d, tm, ln, cat, req = [], [], [], [], [], [], []
    for j in range(m):
        parts = lines[row + j].split()
        if len(parts) != 7:
            raise ValueError(f"Invalid street record {j} on line {row + j + 1}")
        a.append(int(parts[0]))
        b.append(int(parts[1]))
        d.append(int(parts[2]))
        tm.append(int(parts[3]))
        ln.append(int(parts[4]))
        cat.append(parts[5])
        req.append(int(parts[6]))
    row += m
    fleet = lines[row].split() if row < len(lines) else []
    if len(fleet) != c:
        raise ValueError(f"Expected a final line with {c} vehicle types")
    return Problem(n, m, t, c, s, alpha, a, b, d, tm, ln, cat, req, fleet,
                   coords, instance_name(path))
