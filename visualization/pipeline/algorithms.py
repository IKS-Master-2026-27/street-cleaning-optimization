"""The solving algorithms the 3D tool can run, and where their solutions are kept.

To add a new algorithm, write a function that takes a ``clipp.parser.Instance``
and returns a ``clipp.solver.Solution`` (the same types the greedy uses), then
add one entry to ALGORITHMS:

    ALGORITHMS = {
        "greedy": Algorithm("Greedy", "clipp.solver", "solve"),
        "better": Algorithm("Better heuristic", "clipp.better", "solve"),
    }

and run ``python visualization/pipeline/build.py Presheva --algorithm better``.
Every algorithm's solution is written in the validator's format to
data/output/<algorithm>/<City>_instance_solution.txt, so it can also be checked with the
course validator.
"""

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SOLUTIONS = ROOT / "data" / "output"


@dataclass(frozen=True)
class Algorithm:
    label: str      # shown in the app
    module: str     # Python module, imported from the repository root
    function: str   # function(Instance) -> Solution


ALGORITHMS = {
    "greedy": Algorithm("Greedy", "clipp.solver", "solve"),
}


def solution_path(algorithm: str, city: str) -> Path:
    return SOLUTIONS / algorithm / f"{city}_instance_solution.txt"  # the team's naming


def run_algorithm(algorithm: str, instance_path: Path, output: Path) -> float:
    """Solve the instance, check the solution with clipp's validator and write it.

    Returns the solving time in seconds. Raises ValueError when the algorithm
    fails or its solution is not valid, so no invalid file is ever written.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from clipp.output import write_solution
    from clipp.parser import parse_instance
    from clipp.validator import validate_solution

    spec = ALGORITHMS[algorithm]
    solve = getattr(importlib.import_module(spec.module), spec.function)
    instance = parse_instance(instance_path)
    started = time.time()
    solution = solve(instance)
    seconds = time.time() - started
    errors = validate_solution(instance, solution)
    if errors:
        raise ValueError(f"{algorithm} produced an invalid solution: " + "; ".join(errors[:5]))
    write_solution(solution, output)
    return seconds
