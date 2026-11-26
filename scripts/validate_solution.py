"""Validate saved solution files and print their scores.

Usage (from the repository root):
    python scripts/validate_solution.py <instance.txt> <solution.txt>
    python scripts/validate_solution.py --algorithm dp_memo      # all 15 instances
    python scripts/validate_solution.py --algorithm dp_memo --realistic   # 10 realistic cities

Each file is checked twice: by the repository's validator (clipp/validator.py)
and by the independent validator in clipp/dp/objective.py.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipp.dp.io import problem_from_instance  # noqa: E402
from clipp.dp.objective import evaluate, read_solution, to_repo_solution  # noqa: E402
from clipp.parser import parse_instance  # noqa: E402
from clipp.scoring import calculate_score  # noqa: E402
from clipp.validator import validate_solution  # noqa: E402


def check(instance_path: Path, solution_path: Path) -> bool:
    instance = parse_instance(instance_path)
    problem = problem_from_instance(instance)
    routes = read_solution(problem, solution_path)
    independent = evaluate(problem, routes)
    solution = to_repo_solution(problem, routes)
    repo_errors = validate_solution(instance, solution)
    ok = independent.valid and not repo_errors
    score = calculate_score(instance, solution).score if not repo_errors else float("nan")
    print(f"{'VALID  ' if ok else 'INVALID'} score {score:.6f}  {solution_path}")
    for error in list(repo_errors)[:5] + list(independent.errors)[:5]:
        print(f"    {error}")
    return ok


def instances(realistic: bool = False) -> list[Path]:
    data = ROOT / "data" / "input"
    if realistic:
        return sorted((data / "realistic_instances").glob("*/instance.txt"))
    return (sorted((data / "syntetic_generated").glob("instance_*.txt"))
            + sorted((data / "real_instances").glob("*/instance.txt")))


def output_name(path: Path) -> str:
    return f"{path.parent.name}_instance" if path.stem == "instance" else path.stem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("instance", nargs="?")
    parser.add_argument("solution", nargs="?")
    parser.add_argument("--algorithm", help="folder name in data/output, e.g. dp_memo")
    parser.add_argument("--realistic", action="store_true",
                        help="check data/output/realistic_instances/<algorithm> instead")
    args = parser.parse_args()
    if args.algorithm:
        output = ROOT / "data" / "output"
        folder = (output / "realistic_instances" if args.realistic else output) / args.algorithm
        results = []
        for inst in instances(args.realistic):
            sol = folder / f"{output_name(inst)}_solution.txt"
            if not sol.exists():
                print(f"MISSING {sol}")
                results.append(False)
                continue
            results.append(check(inst, sol))
        print(f"{sum(results)}/{len(results)} valid")
        return 0 if all(results) else 1
    if not (args.instance and args.solution):
        parser.error("give <instance> <solution> or --algorithm NAME")
    return 0 if check(Path(args.instance), Path(args.solution)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
