"""Benchmark: greedy vs Solution A vs Solution B vs upper bound on every instance.

Usage (from the repository root):
    python scripts/benchmark_dp.py [--time-limit 120] [--seeds 1 2 3] [--workers 6]

Baselines: the greedy outputs in data/output/greedy/ (all instances) and
the feasibility witness instance.solution.txt shipped with each real city.
Best solutions are written to data/output/dp_simple/ and data/output/dp_advanced/;
the result table goes to data/output/dp_benchmark.md and .csv.
"""

import argparse
import csv
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipp.dp.bounds import upper_bound  # noqa: E402
from clipp.dp.distances import Oracle  # noqa: E402
from clipp.dp.io import read_problem  # noqa: E402
from clipp.dp.objective import evaluate, read_solution, to_repo_solution  # noqa: E402
from clipp.output import write_solution  # noqa: E402


def instances() -> list[Path]:
    synthetic = sorted((ROOT / "data/input/syntetic_generated").glob("instance_*.txt"))
    real = sorted((ROOT / "data/input/real_instances").glob("*/instance.txt"),
                  key=lambda p: p.stat().st_size)
    return synthetic + real


def greedy_file(path: Path) -> Path | None:
    stem = f"{path.parent.name}_instance" if path.stem == "instance" else path.stem
    candidate = ROOT / "data/output/greedy" / f"{stem}_solution.txt"
    return candidate if candidate.exists() else None


def witness_file(path: Path) -> Path | None:
    candidate = path.with_name("instance.solution.txt")
    return candidate if path.stem == "instance" and candidate.exists() else None


def score_file(problem, path: Path | None) -> float | None:
    if path is None:
        return None
    ev = evaluate(problem, read_solution(problem, path))
    return ev.score if ev.valid else None


def run_simple(path: str) -> dict:
    from clipp.dp.simple import solve_simple
    problem = read_problem(path)
    oracle = Oracle(problem)
    result = solve_simple(problem, oracle)
    greedy = score_file(problem, greedy_file(Path(path)))
    witness = score_file(problem, witness_file(Path(path)))
    out = ROOT / "data/output/dp_simple" / f"{problem.name}_solution.txt"
    if result.evaluation.valid:
        write_solution(to_repo_solution(problem, result.routes), out)
    return {"name": problem.name, "N": problem.num_junctions, "M": problem.num_streets,
            "C": problem.num_vehicles, "alpha": problem.alpha,
            "greedy": greedy, "witness": witness, "A": result.evaluation.score,
            "A_valid": result.evaluation.valid, "A_seconds": result.seconds,
            "UB": upper_bound(problem, oracle)}


def run_advanced(args: tuple[str, int, float]) -> dict:
    from clipp.dp.advanced import solve_advanced
    path, seed, limit = args
    problem = read_problem(path)
    result = solve_advanced(problem, Oracle(problem), seed=seed, time_limit=limit)
    out = ROOT / "data/output/dp_advanced" / f"{problem.name}_seed{seed}_solution.txt"
    if result.evaluation.valid:
        write_solution(to_repo_solution(problem, result.routes), out)
    return {"name": problem.name, "seed": seed, "B": result.evaluation.score,
            "valid": result.evaluation.valid, "seconds": result.seconds, "file": out}


def fmt(x, digits=4):
    return "–" if x is None else f"{x:.{digits}f}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--only", nargs="*", help="instance names to run")
    args = parser.parse_args()
    paths = [p for p in instances()
             if not args.only or (p.parent.name if p.stem == "instance" else p.stem) in args.only]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        simple = list(pool.map(run_simple, map(str, paths)))
        # Where Solution A already meets the upper bound it is proven optimal and
        # Solution B would return it unchanged, so those runs are skipped.
        open_paths = [p for p, info in zip(paths, simple) if info["A"] < info["UB"] - 1e-12]
        jobs = [(str(p), s, args.time_limit) for p in open_paths for s in args.seeds]
        advanced = list(pool.map(run_advanced, jobs))

    rows = []
    for info in simple:
        runs = [r for r in advanced if r["name"] == info["name"]]
        if not runs:
            final = ROOT / "data/output/dp_advanced" / f"{info['name']}_solution.txt"
            final.parent.mkdir(parents=True, exist_ok=True)
            source = ROOT / "data/output/dp_simple" / f"{info['name']}_solution.txt"
            if source.exists():
                final.write_text(source.read_text())
            rows.append({**info, "B_mean": info["A"], "B_std": 0.0, "B_best": info["A"],
                         "B_valid": info["A_valid"], "B_seconds": 0.0})
            continue
        scores = [r["B"] for r in runs if r["valid"]]
        best = max(runs, key=lambda r: r["B"] if r["valid"] else -1)
        # keep the best seed as the advanced solution of record
        final = ROOT / "data/output/dp_advanced" / f"{info['name']}_solution.txt"
        if best["valid"]:
            final.write_text(Path(best["file"]).read_text())
        for r in runs:
            Path(r["file"]).unlink(missing_ok=True)
        rows.append({**info,
                     "B_mean": statistics.mean(scores) if scores else None,
                     "B_std": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
                     "B_best": max(scores) if scores else None,
                     "B_valid": all(r["valid"] for r in runs),
                     "B_seconds": statistics.mean(r["seconds"] for r in runs)})

    header = ("| Instance | N | M | C | α | Greedy | Witness | A | B mean ± σ | B best | UB | Gap B | "
              "Time A (s) | Time B (s) |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines = [header]
    for r in rows:
        gap = (r["UB"] - r["B_best"]) / r["UB"] if r["B_best"] is not None and r["UB"] > 0 else None
        lines.append(
            f"| {r['name']} | {r['N']:,} | {r['M']:,} | {r['C']} | {r['alpha']} | {fmt(r['greedy'])} | "
            f"{fmt(r['witness'])} | "
            f"{fmt(r['A'])} | {fmt(r['B_mean'])} ± {fmt(r['B_std'])} | **{fmt(r['B_best'])}** | "
            f"{fmt(r['UB'])} | {fmt(None if gap is None else 100 * max(0.0, gap), 2)}% | "
            f"{r['A_seconds']:.1f} | {r['B_seconds']:.1f} |")
    table = "\n".join(lines)
    print(table)
    print(f"\nseeds {args.seeds}, time limit {args.time_limit}s per run, "
          f"all valid: {all(r['A_valid'] and r['B_valid'] for r in rows)}, "
          f"wall time {time.perf_counter() - t0:.0f}s")
    out_dir = ROOT / "data/output"
    (out_dir / "dp_benchmark.md").write_text(table + "\n", encoding="utf-8")
    with open(out_dir / "dp_benchmark.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
