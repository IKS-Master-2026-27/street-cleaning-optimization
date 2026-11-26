"""Warm start: read an existing algorithm's solution (the seed).

``clipp.milp.cpsat`` turns the seed into a complete CP-SAT hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..parser import Instance
from ..scoring import calculate_score
from ..solver import Solution, VehicleRoute, VEHICLE_CAPACITIES
from ..validator import validate_solution

# Folders in data/output that are not independent algorithms on the original
# instances (this tool's own outputs).
EXCLUDED_SEED_FOLDERS = {"milp", "milp_cold", "milp_warm"}


@dataclass(frozen=True)
class Seed:
    algorithm: str      # folder name, e.g. "dp_simple"
    path: Path
    solution: Solution
    score: float


def solution_file_name(instance_path: str | Path) -> str:
    """File name used by main.py: instance_A_solution.txt / Presheva_instance_solution.txt."""

    path = Path(instance_path)
    name = path.stem
    if name == "instance":
        name = f"{path.parent.name}_instance"
    return f"{name}_solution.txt"


def read_solution(instance: Instance, path: str | Path) -> Solution:
    """Read a solution file into a Solution.

    The file format (per vehicle: step count, junction list, cleaned streets)
    lists junctions, not streets. Each move a -> b is mapped back to a street;
    if several streets connect a and b, we prefer one the vehicle cleans (and
    has not matched yet), then the fastest one.
    """

    lines = Path(path).read_text(encoding="utf-8").split("\n")
    vehicle_count = int(lines[0])

    streets_between: dict[tuple[int, int], list] = {}
    for street in instance.streets:
        streets_between.setdefault((street.a, street.b), []).append(street)
        if street.direction == 2:
            streets_between.setdefault((street.b, street.a), []).append(street)

    routes = []
    line = 1
    for vehicle_id in range(vehicle_count):
        junctions = [int(value) for value in lines[line + 1].split()]
        cleaned = [int(value) for value in lines[line + 2].split()]
        line += 3

        not_matched = set(cleaned)
        street_ids = []
        for a, b in zip(junctions, junctions[1:]):
            options = streets_between.get((a, b))
            if not options:
                raise ValueError(f"vehicle {vehicle_id}: no street for move {a}->{b}")
            street = min(options, key=lambda s: (s.id not in not_matched, s.time, s.id))
            not_matched.discard(street.id)
            street_ids.append(street.id)

        vehicle_type = instance.vehicle_types[vehicle_id]
        routes.append(VehicleRoute(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            capacity=VEHICLE_CAPACITIES[vehicle_type],
            current_junction=junctions[-1],
            junctions=junctions,
            total_time=sum(instance.streets[i].time for i in street_ids),
            street_ids=street_ids,
            cleaned_street_ids=cleaned,
        ))
    return Solution(routes)


def find_best_seed(instance: Instance, instance_path: str | Path,
                   output_root: str | Path = "data/output",
                   algorithm: str | None = None) -> Seed | None:
    """Return the highest-scoring valid solution for this instance.

    Looks in ``output_root/<algorithm>/`` for every algorithm folder, or only in
    the given ``algorithm`` folder (``-`` and ``_`` are the same). Invalid or
    unreadable files are skipped. Ties go to the first folder in name order.
    """

    root = Path(output_root)
    file_name = solution_file_name(instance_path)
    if algorithm is not None:
        folders = [root / algorithm.replace("-", "_")]
    else:
        folders = sorted(folder for folder in root.iterdir()
                         if folder.is_dir() and folder.name not in EXCLUDED_SEED_FOLDERS
                         and not folder.name.endswith("_8h"))
    best = None
    for folder in folders:
        path = folder / file_name
        if not path.is_file():
            continue
        try:
            solution = read_solution(instance, path)
            if validate_solution(instance, solution):
                continue  # not valid: never use it as a seed
            score = calculate_score(instance, solution).score
        except (ValueError, IndexError, KeyError):
            continue
        if best is None or score > best.score:
            best = Seed(folder.name, path, solution, score)
    return best
