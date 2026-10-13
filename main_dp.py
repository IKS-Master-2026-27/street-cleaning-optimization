"""Run the dynamic-programming solvers (Solution A: simple, Solution B: advanced).

Every solution is checked twice: by the repository's validator/scorer and by the
independent validator in clipp/dp/objective.py, and is compared with the
provable upper bound from clipp/dp/bounds.py.
"""

import argparse
import sys
import time
from pathlib import Path

from clipp.dp.bounds import upper_bound
from clipp.dp.distances import Oracle
from clipp.dp.io import read_problem
from clipp.dp.objective import additive_score, to_repo_solution
from clipp.output import write_solution
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.validator import validate_solution


def run(path: str, method: str, seed: int, time_limit: float, output_dir: str | None,
        quiet: bool = False) -> dict:
    say = (lambda *a: None) if quiet else print
    t0 = time.perf_counter()
    problem = read_problem(path)
    oracle = Oracle(problem)
    say(f"{problem.name}: N={problem.num_junctions} M={problem.num_streets} "
        f"C={problem.num_vehicles} T={problem.time_limit} alpha={problem.alpha}")
    if method == "simple":
        from clipp.dp.simple import solve_simple
        result = solve_simple(problem, oracle)
    else:
        from clipp.dp.advanced import solve_advanced
        result = solve_advanced(problem, oracle, seed=seed, time_limit=time_limit,
                                progress=None if quiet else say)
    for line in result.log:
        say(f"  {line}")

    ev = result.evaluation
    repo_errors = []
    repo_score = None
    try:
        instance = parse_instance(path)
        solution = to_repo_solution(problem, result.routes)
        repo_errors = validate_solution(instance, solution)
        if not repo_errors:
            repo_score = calculate_score(instance, solution).score
    except ValueError as exc:  # e.g. official layout with coordinates
        repo_errors = [f"repository parser: {exc}"]
    bound = upper_bound(problem, oracle)
    status = "VALID" if ev.valid and not repo_errors else "INVALID"
    say(f"Solution {method}: {status}")
    for error in list(ev.errors)[:10] + list(repo_errors)[:10]:
        say(f"  ! {error}")
    say(f"Score {ev.score:.10f}  (coverage {ev.coverage:.4f}, efficiency {ev.efficiency:.4f}, "
        f"waste {ev.waste:g})")
    if repo_score is not None:
        say(f"Repository scoring.py: {repo_score:.10f}   additive identity: "
            f"{additive_score(problem, result.routes):.10f}")
    gap = max(0.0, (bound - ev.score) / bound) if bound > 0 else 0.0
    say(f"Upper bound {bound:.10f}  gap {100 * gap:.2f}%   time {time.perf_counter() - t0:.1f}s")

    output = None
    if status == "VALID" and output_dir:
        output = Path(output_dir) / f"{problem.name}_solution.txt"
        write_solution(to_repo_solution(problem, result.routes), output)
        say(f"Output: {output}")
    return {
        "instance": problem.name, "method": method, "valid": status == "VALID",
        "score": ev.score, "coverage": ev.coverage, "efficiency": ev.efficiency,
        "upper_bound": bound, "gap": gap, "seconds": time.perf_counter() - t0,
        "output": str(output) if output else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance")
    parser.add_argument("--method", choices=["simple", "advanced"], default="simple")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=60.0,
                        help="search budget in seconds for the advanced method")
    parser.add_argument("--output-dir", default=None,
                        help="default: data/output/dp_<method>")
    args = parser.parse_args()
    out = args.output_dir or f"data/output/dp_{args.method}"
    try:
        result = run(args.instance, args.method, args.seed, args.time_limit, out)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
