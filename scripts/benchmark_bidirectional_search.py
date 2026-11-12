"""Benchmark Bidirectional Search (clipp/bidirectional_search.py).

Every run is a separate process (clean peak-memory reading, hard timeout).
Results go to data/output/bidirectional_search/:

    benchmark.csv         BDS-Bounded on all 15 instances, BDS-Exact attempts
    parameter_study.csv   one-factor-at-a-time BDS-Bounded study on A-E
    baselines.csv         the six executable existing algorithms (score only,
                          their own output files are NOT touched)
    runs.jsonl            raw JSON report of every run

    exact_scaling.csv     BDS-Exact on generated instances of growing size
                          (instances in exact_scaling/instances/)

    python scripts/benchmark_bidirectional_search.py --groups main exact study baselines
    python scripts/benchmark_bidirectional_search.py --groups scaling --workers 4
    python scripts/benchmark_bidirectional_search.py --groups main --only instance_A Presheva
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output" / "bidirectional_search"
SYNTHETIC = [ROOT / f"data/input/syntetic_generated/instance_{x}.txt" for x in "ABCDE"]
CITIES = [ROOT / f"data/input/real_instances/{c}/instance.txt" for c in (
    "Presheva", "Ulqini", "Prishtina", "Shkupi", "Tirana", "Ljubljana", "Vienna",
    "New-York", "Johannesburg", "Sydney")]
BASELINES = {
    "greedy": ("clipp.solver", "solve"),
    "recursive": ("clipp.recursive", "solve"),
    "recursive-enum": ("clipp.recursive_enum", "solve"),
    "preprocessing": ("clipp.preprocessing_solver", "solve"),
    "dp-simple": ("clipp.dp.simple", "solve"),
    "greedy-lookahead": ("clipp.greedy_lookahead", "solve"),
}
STUDY = {  # parameter -> values (defaults: see BoundedParams)
    "width": [8, 32, 128],
    "candidates": [4, 8, 16],
    "bucket-fraction": [0.005, 0.02, 0.08],
    "overlap": [0.0, 0.5, 1.0, 2.0],
    "diversity": ["quota", "none"],
    "meeting": ["partitioned", "free"],
    "rank": ["nearest", "density"],
    "mandatory-weight": [4.0, 64.0],
}


def name_of(path: Path) -> str:
    return path.stem if path.stem != "instance" else path.parent.name


def run(cmd: list[str], timeout: float) -> dict:
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "message": f"killed after {timeout:.0f}s (process limit)",
                "runtime_s": time.perf_counter() - started}
    lines = [l for l in proc.stdout.splitlines() if l.startswith("{")]
    if not lines:
        return {"status": "ERROR", "message": (proc.stderr or proc.stdout)[-400:],
                "runtime_s": time.perf_counter() - started}
    return json.loads(lines[-1])


def bds_job(path: Path, mode: str, extra: list[str], limit: float, label: str, write=True):
    cmd = [sys.executable, "-B", "-m", "clipp.bidirectional_search", str(path), "--mode", mode,
           "--json", "--time-limit", str(limit), *extra]
    if not write:
        cmd.append("--no-write")
    report = run(cmd, limit * 1.5 + 120)
    report.setdefault("instance", name_of(path))
    report["config"] = label
    report["instance"] = name_of(path)
    return report


def baseline_job(path: Path, algorithm: str, limit: float) -> dict:
    module, function = BASELINES[algorithm]
    code = (
        "import json,time,sys\n"
        "from clipp.parser import parse_instance\n"
        "from clipp.scoring import calculate_score\n"
        "from clipp.validator import validate_solution\n"
        "from clipp.bidirectional_search import memory_mb\n"
        f"from {module} import {function} as solve\n"
        f"i=parse_instance(r'{path}')\n"
        "t=time.perf_counter()\n"
        "try:\n"
        "    s=solve(i); rt=time.perf_counter()-t; e=validate_solution(i,s)\n"
        "    sc=None if e else calculate_score(i,s).score\n"
        "    st='VALID' if not e else 'INVALID'\n"
        "except Exception as x:\n"
        "    rt=time.perf_counter()-t; sc=None; st='FAILED: '+type(x).__name__\n"
        "print(json.dumps(dict(status=st,score=sc,runtime_s=rt,peak_memory_mb=memory_mb()[0])))\n")
    report = run([sys.executable, "-B", "-c", code], limit)
    report.update(instance=name_of(path), config=algorithm)
    return report


FIELDS = ["group", "instance", "config", "mode", "class_reduction", "report_status", "status", "valid",
          "optimal_proven", "score_certificate", "score", "coverage", "efficiency",
          "runtime_s", "peak_memory_mb", "generated", "expanded", "stored", "join_checks",
          "compatible_meetings", "dominated", "bound_pruned", "pruned", "params", "message"]


def row(group: str, r: dict) -> dict:
    stats = r.get("stats") or {}
    out = {k: r.get(k) for k in FIELDS}
    out["group"] = group
    for k in ("generated", "expanded", "stored", "join_checks", "compatible_meetings",
              "dominated", "bound_pruned", "pruned"):
        out[k] = stats.get(k)
    p = r.get("params") or {}
    out["params"] = ";".join(f"{k}={v}" for k, v in p.items()
                             if k in ("width", "candidates", "bucket_fraction", "overlap",
                                      "diversity", "meeting", "rank", "mandatory_weight",
                                      "time_limit", "memory_limit_mb", "halfway", "seed"))
    return out


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def scaling_instances(sizes=(4, 6, 8, 10, 12, 14, 16, 20), seeds=(0, 1)) -> list[Path]:
    """Random strongly connected instances with n tasks for the exact-mode limits.

    A two-way connector ring keeps every junction reachable; n eligible streets
    (half mandatory) are added at random; 2 vehicles; T = half of the service
    time plus one ring tour, so routes must be chosen with care.
    """
    import random
    folder = OUT / "exact_scaling" / "instances"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in sizes:
        for seed in seeds:
            rng = random.Random(1000 * n + seed)
            nodes = max(4, n // 2 + 2)
            lines = [(i, (i + 1) % nodes, 2, rng.randint(1, 5), 100, "C", 10) for i in range(nodes)]
            for j in range(n):
                a, b = rng.sample(range(nodes), 2)
                lines.append((a, b, rng.choice((1, 2)), rng.randint(2, 9), rng.randint(1, 9) * 100,
                              "M" if j % 2 == 0 else "O", rng.choice((10, 20, 30))))
            ring = sum(x[3] for x in lines[:nodes])
            T = ring + sum(x[3] for x in lines[nodes:]) // 2
            types = ["L", rng.choice("SML")]
            text = [f"{nodes} {len(lines)} {T} 2 0 1.0"] + [" ".join(map(str, x)) for x in lines]
            text.append(" ".join(types))
            p = folder / f"scale_n{n:02d}_s{seed}.txt"
            p.write_text("\n".join(text) + "\n", encoding="utf-8")
            paths.append(p)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--groups", nargs="+", default=["main", "exact", "study", "baselines"])
    ap.add_argument("--only", nargs="*", help="instance names")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--synthetic-limit", type=float, default=120.0)
    ap.add_argument("--city-limit", type=float, default=600.0)
    ap.add_argument("--exact-limit", type=float, default=300.0)
    ap.add_argument("--baseline-limit", type=float, default=300.0)
    ap.add_argument("--scaling-limit", type=float, default=60.0)
    args = ap.parse_args()
    keep = (lambda p: True) if not args.only else (lambda p: name_of(p) in args.only)
    jobs = []
    if "main" in args.groups:
        for p in filter(keep, SYNTHETIC):
            jobs.append(("main", bds_job, (p, "bounded", [], args.synthetic_limit, "bounded")))
        for p in filter(keep, CITIES):
            jobs.append(("main", bds_job, (p, "bounded", ["--class-reduction"], args.city_limit,
                                           "bounded+class-reduction")))
        for p in filter(keep, CITIES[:1]):  # unrestricted on the smallest city
            jobs.append(("main", bds_job, (p, "bounded", [], args.synthetic_limit, "bounded")))
    if "exact" in args.groups:
        for p in filter(keep, SYNTHETIC[:1]):
            jobs.append(("exact", bds_job, (p, "exact", ["--memory-limit-mb", "4000"],
                                            args.exact_limit, "exact")))
    if "scaling" in args.groups:
        for p in scaling_instances():
            jobs.append(("scaling", bds_job, (p, "exact", ["--memory-limit-mb", "3000"],
                                              args.scaling_limit, "exact", False)))
    if "study" in args.groups:
        for p in filter(keep, SYNTHETIC):
            for param, values in STUDY.items():
                for v in values:
                    jobs.append(("study", bds_job, (p, "bounded", [f"--{param}", str(v)],
                                                    args.synthetic_limit, f"{param}={v}", False)))
    if "baselines" in args.groups:
        for p in filter(keep, SYNTHETIC + CITIES[:1]):
            for alg in BASELINES:
                jobs.append(("baselines", baseline_job, (p, alg, args.baseline_limit)))

    results: dict[str, list[dict]] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool, open(OUT / "runs.jsonl", "a",
                                                        encoding="utf-8") as raw:
        futures = [(g, pool.submit(fn, *a)) for g, fn, a in jobs]
        for g, fut in futures:
            r = fut.result()
            r["group"] = g
            raw.write(json.dumps(r, default=str) + "\n")
            raw.flush()
            results.setdefault(g, []).append(row(g, r))
            print(g, r.get("instance"), r.get("config"), r.get("status"), r.get("score"),
                  round(r.get("runtime_s") or 0, 1), flush=True)
    files = {"main": "benchmark.csv", "exact": "benchmark_exact.csv",
             "scaling": "exact_scaling.csv",
             "study": "parameter_study.csv", "baselines": "baselines.csv"}
    for g, rows in results.items():
        write(OUT / files[g], rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
