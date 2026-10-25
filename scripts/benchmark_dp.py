"""Benchmark: greedy vs Solution A vs upper bound on every instance.

Usage (from the repository root):
    python scripts/benchmark_dp.py [--workers 6] [--only instance_A Presheva]
                                   [--output-dir DIR]

Baselines: the greedy outputs in data/output/greedy/ (all instances) and
the feasibility witness instance.solution.txt shipped with each real city.
Solutions go to <output-dir>/dp_simple/ (default output-dir: data/output).
The solver is deterministic, so one run per instance is enough. Solution A
replaces a stored solution only if it scores higher. The result table
goes to <output-dir>/dp_benchmark.md and .csv.
"""

import argparse
import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipp.dp.bounds import upper_bound  # noqa: E402
from clipp.dp.distances import Oracle  # noqa: E402
from clipp.dp.io import instance_name, read_problem  # noqa: E402
from clipp.dp.objective import evaluate, read_solution, save_if_better  # noqa: E402


def instances() -> list[Path]:
    synthetic = sorted((ROOT / "data/input/syntetic_generated").glob("instance_*.txt"))
    real = sorted((ROOT / "data/input/real_instances").glob("*/instance.txt"),
                  key=lambda p: p.stat().st_size)
    return synthetic + real


def greedy_file(path: Path) -> Path | None:
    candidate = ROOT / "data/output/greedy" / f"{instance_name(path)}_solution.txt"
    return candidate if candidate.exists() else None


def witness_file(path: Path) -> Path | None:
    candidate = path.with_name("instance.solution.txt")
    return candidate if path.stem == "instance" and candidate.exists() else None


def score_file(problem, path: Path | None) -> float | None:
    if path is None:
        return None
    ev = evaluate(problem, read_solution(problem, path))
    return ev.score if ev.valid else None


def run_simple(args: tuple[str, str]) -> dict:
    from clipp.dp.simple import solve_simple
    path, out_dir = args
    problem = read_problem(path)
    oracle = Oracle(problem)
    result = solve_simple(problem, oracle)
    greedy = score_file(problem, greedy_file(Path(path)))
    witness = score_file(problem, witness_file(Path(path)))
    saved, _ = save_if_better(problem, result.routes,
                              Path(out_dir) / "dp_simple" / f"{problem.name}_solution.txt")
    return {"name": problem.name, "N": problem.num_junctions, "M": problem.num_streets,
            "C": problem.num_vehicles, "alpha": problem.alpha,
            "greedy": greedy, "witness": witness, "A": result.evaluation.score,
            "A_valid": result.evaluation.valid, "A_seconds": result.seconds,
            "UB": upper_bound(problem, oracle), "A_saved": saved}


def fmt(x, digits=4):
    return "–" if x is None else f"{x:.{digits}f}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--only", nargs="*", help="instance names to run")
    parser.add_argument("--output-dir", default=str(ROOT / "data/output"),
                        help="where solutions and the table go (default: data/output)")
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    paths = [p for p in instances()
             if not args.only or (p.parent.name if p.stem == "instance" else p.stem) in args.only]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        simple = list(pool.map(run_simple, [(str(p), str(out_dir)) for p in paths]))

    rows = simple
    header = ("| Instance | N | M | C | α | Greedy | Witness | A | UB | Gap A | "
              "Time A (s) |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines = [header]
    for r in rows:
        gap = (r["UB"] - r["A"]) / r["UB"] if r["UB"] > 0 else None
        lines.append(
            f"| {r['name'].removesuffix('_instance')} | {r['N']:,} | {r['M']:,} | {r['C']} | {r['alpha']} | {fmt(r['greedy'])} | "
            f"{fmt(r['witness'])} | **{fmt(r['A'])}** | "
            f"{fmt(r['UB'])} | {fmt(None if gap is None else 100 * max(0.0, gap), 2)}% | "
            f"{r['A_seconds']:.1f} |")
    table = "\n".join(lines)
    print(table)
    print(f"\nall valid: {all(r['A_valid'] for r in rows)}, "
          f"wall time {time.perf_counter() - t0:.0f}s")
    print(f"stored solutions improved: Solution A {sum(r['A_saved'] for r in rows)}")
    (out_dir / "dp_benchmark.md").write_text(table + "\n", encoding="utf-8")
    with open(out_dir / "dp_benchmark.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
