"""Run the CLIPP competition model (OR-Tools CP-SAT) cold and warm, and report.

Variants
    cold  no initial solution
    warm  the Dynamic Programming solution (data/output/dp_simple/) as a CP-SAT
          hint (AddHint); it is first checked to be feasible for the model

Default experiment (the professor's instructions):
    cold  instance_A..E and Presheva
    warm  all 15 instances
    1 h solver time per run, 4 CP-SAT workers per run, same machine for all.

Usage (repository root, tools/milp/requirements.txt installed):

    python tools/milp/run.py --background          # the whole experiment, detached
    python tools/milp/run.py --part 1 --background # or in 3 parts of <= 3 h each:
                                                      # 1 = A,B,C  2 = D,E,Presheva
                                                      # 3 = other cities (warm)
    python tools/milp/run.py data/input/syntetic_generated/instance_A.txt \
        --time-limit 60 --out ~/Desktop/cpsat_test  # quick test

How the runs are scheduled
    Instances with at most --small-vars variables: the cold and warm run of the
    same instance run side by side (2 processes x 4 workers = the 8 performance
    cores), with --memory-limit-gb each. Larger instances (warm only) run one at
    a time afterwards with --large-memory-limit-gb.
    Every run is its own process. It is stopped when it uses more memory than
    its limit, or when building the model takes longer than --build-limit. The
    report then gives the number of variables, the time and the reason.

Outputs (default tools/milp/results/):
    results.csv, results.md   one row per instance and variant
    metadata.json             machine, versions, settings
    status.txt                running jobs, memory, phase
    jobs/<instance>_<variant>/
        log.txt               console output incl. the CP-SAT log of round 1
        progress.csv          every CP-SAT solution and round: time, LB/UB
        result.json           the row of this run
        solution.txt          best valid solution (CLIPP format)

Create <out>/STOP to stop everything (running jobs are killed).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOL = Path(__file__).resolve().parent          # tools/milp
ROOT = TOOL.parents[1]                          # repository root (instance paths)
for _path in (ROOT, TOOL / "src", TOOL):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

SYNTHETIC = [f"data/input/syntetic_generated/instance_{c}.txt" for c in "ABCDE"]
REAL = [f"data/input/real_instances/{city}/instance.txt" for city in (
    "Johannesburg", "Ljubljana", "New-York", "Presheva", "Prishtina",
    "Shkupi", "Sydney", "Tirana", "Ulqini", "Vienna")]
COLD_DEFAULT = SYNTHETIC + ["data/input/real_instances/Presheva/instance.txt"]
PRESHEVA = "data/input/real_instances/Presheva/instance.txt"
# The experiment in three parts of at most ~3 h each (same settings, same --out):
PARTS = {
    1: SYNTHETIC[:3],                                  # A, B, C: cold + warm
    2: SYNTHETIC[3:] + [PRESHEVA],                     # D, E, Presheva: cold + warm
    3: [p for p in REAL if p != PRESHEVA],             # the other 9 cities: warm only
}
ORDER = SYNTHETIC + [PRESHEVA] + PARTS[3]

FIELDS = [
    "instance", "variant", "result", "reason", "num_vars", "num_constraints",
    "build_s", "hint_check_s", "solve_s", "time_limit_s", "workers",
    "first_valid_s", "best_s", "objective", "lower_bound", "upper_bound", "gap",
    "seed_algorithm", "seed_score", "hint_feasible", "improvement_vs_seed",
    "rounds", "cut_rounds", "cpsat_status", "valid", "official_score",
    "peak_rss_mb", "slept_s", "message",
]


def label(path: Path) -> str:
    return path.parent.name if path.stem == "instance" else path.stem


def absolute(path, base: Path = ROOT) -> Path:
    """One spelling per instance file (``./data/x`` and ``data/x`` are the same)."""

    path = Path(path).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def planned_runs(args) -> list[tuple[Path, str]]:
    """(instance, variant) of every run this call will do, in input order."""

    paths = [absolute(p) for p in (args.instances or SYNTHETIC + REAL)]
    cold = {absolute(p) for p in (args.cold_instances if args.cold_instances is not None
                                  else args.instances or COLD_DEFAULT)}
    return [(path, v) for path in paths for v in args.variants if v == "warm" or path in cold]


def finished_runs(args, out: Path) -> list[str]:
    """Planned runs that already have a result in ``out`` (they would be overwritten)."""

    names = [f"{label(path)}_{variant}" for path, variant in planned_runs(args)]
    return [n for n in names if (out / "jobs" / n / "result.json").exists()]


def rss_bytes(pid: int) -> int:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return int(out) * 1024 if out else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def fmt(value, digits=6):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return value


# ====================================================================== worker

def worker(args) -> int:
    """One instance x variant, in its own process; writes result.json."""

    from milp import cpsat
    from milp.seed import find_best_seed
    from clipp.output import write_solution
    from clipp.parser import parse_instance
    from clipp.scoring import calculate_score
    from clipp.validator import validate_solution
    from clipp_cpsat.parser import parse_instance as parse_competition

    job = Path(args.job_dir)
    path = Path(args.instance)
    row = {"instance": label(path), "variant": args.variant,
           "time_limit_s": args.time_limit, "workers": args.workers}

    def phase(name: str) -> None:
        (job / "phase.txt").write_text(f"{name} {time.time():.0f}\n")
        print(f"[phase] {name}", flush=True)

    def finish() -> int:
        (job / "result.json").write_text(json.dumps(row, indent=2) + "\n")
        return 0

    phase("parse")
    ours = parse_instance(path)
    instance = parse_competition(str(path))
    row["num_vars"] = cpsat.count_variables(instance)

    seed = None
    if args.variant == "warm":
        seed = find_best_seed(ours, path, args.output_root, args.seed_algorithm)
        if seed is None:
            row.update(result="skipped", reason="no valid seed solution")
            return finish()
        row["seed_algorithm"], row["seed_score"] = seed.algorithm, fmt(seed.score, 10)

    phase("build")
    started = time.perf_counter()
    built = cpsat.build(instance)
    row["build_s"] = fmt(time.perf_counter() - started, 3)
    row["num_vars"], row["num_constraints"] = built.num_vars, built.num_constraints
    if built.relaxed_mandatory:
        row["message"] = f"relaxed unreachable mandatory streets {sorted(built.relaxed_mandatory)[:10]}"
    print(f"[build] {built.num_vars} variables, {built.num_constraints} constraints, "
          f"{row['build_s']} s", flush=True)

    seed_values = None
    seed_objective = None
    if seed is not None:
        phase("hint_check")
        started = time.perf_counter()
        seed_values = cpsat.seed_values(built, seed.solution)
        feasible, status, seed_objective = cpsat.check_hint(
            built, seed_values, args.workers, args.hint_check_limit)
        row["hint_check_s"] = fmt(time.perf_counter() - started, 3)
        row["hint_feasible"] = feasible
        print(f"[hint] feasible={feasible} ({status})", flush=True)
        if not feasible:
            row.update(result="error", reason=f"seed is not feasible for the model ({status})")
            return finish()

    phase("solve")
    progress = (job / "progress.csv").open("w", encoding="utf-8")
    progress.write("seconds,round,event,objective_score,bound_score,valid\n")

    def on_progress(event, seconds, objective, bound, valid, rounds):
        cells = [f"{seconds:.3f}", str(rounds), event,
                 "" if objective is None else f"{built.to_score(objective):.10f}",
                 "" if bound is None else f"{built.to_score(bound):.10f}",
                 "" if valid is None else str(valid)]
        progress.write(",".join(cells) + "\n")
        progress.flush()

    record = cpsat.solve(built, time_limit=args.time_limit, workers=args.workers,
                         seed=seed_values, seed_objective=seed_objective,
                         random_seed=args.random_seed, progress=on_progress)
    progress.close()
    phase("report")

    row.update(solve_s=fmt(record.solve_seconds, 3), rounds=record.rounds,
               cut_rounds=record.cuts_rounds, cpsat_status=" ".join(record.statuses),
               slept_s=fmt(max(0.0, record.solve_seconds - record.awake_seconds), 1),
               first_valid_s=fmt(record.first_valid_seconds, 3),
               best_s=fmt(record.best_seconds, 3))
    if record.upper_objective is not None:
        row["upper_bound"] = fmt(built.to_score(record.upper_objective), 10)

    best, best_objective, from_solver = cpsat.final_values(record, seed_values, seed_objective)
    if best is not None:
        lower = built.to_score(best_objective)
        row["objective"] = row["lower_bound"] = fmt(lower, 10)
        if record.upper_objective is not None:
            upper = built.to_score(record.upper_objective)
            row["gap"] = fmt(max(0.0, upper - lower) / (abs(lower) or 1.0), 6)
        solution = cpsat.to_solution(built, best)
        errors = validate_solution(ours, solution)
        row["valid"] = not errors
        if errors:
            row["message"] = ("; ".join(errors[:3]) + " " + row.get("message", "")).strip()
        else:
            score = calculate_score(ours, solution).score
            row["official_score"] = fmt(score, 10)
            if seed is not None:
                row["improvement_vs_seed"] = fmt(score - seed.score, 10)
            write_solution(solution, job / "solution.txt")

    if record.seed_proven_optimal and row.get("valid"):
        row["result"] = "no improvement (seed optimal)"
        row["reason"] = "the model's upper bound equals the seed score: the seed is proven optimal"
    elif record.proven_optimal and row.get("valid"):
        row["result"], row["reason"] = "optimal", "proven optimal"
    elif from_solver and row.get("valid"):
        row["result"], row["reason"] = "feasible", f"stopped: {record.stop_reason}"
    elif seed is not None:
        row["result"] = "no improvement"
        row["reason"] = (f"solver found no valid solution better than the seed "
                         f"({record.stop_reason}); the seed is kept")
    else:
        row["result"] = "no valid solution"
        row["reason"] = f"no connected solution found ({record.stop_reason})"
    if seed is not None and row.get("improvement_vs_seed") not in (None, ""):
        if float(row["improvement_vs_seed"]) <= 1e-12 and row["result"] == "feasible":
            row["result"] = "no improvement"
    if float(row.get("slept_s") or 0) > 60:
        row["message"] = (f"WARNING: computer slept {row['slept_s']} s. "
                          + row.get("message", "")).strip()
    return finish()


# ====================================================================== parent

def plan_jobs(args) -> list[list[dict]]:
    """Batches of jobs that run together: cold+warm pairs of small instances,
    then the large instances one by one."""

    from milp import cpsat
    from clipp_cpsat.parser import parse_instance as parse_competition

    by_path: dict[Path, list[str]] = {}
    for path, variant in planned_runs(args):
        by_path.setdefault(path, []).append(variant)
    batches_small, batches_large = [], []
    for path, variants in by_path.items():
        size = cpsat.count_variables(parse_competition(str(path)))
        jobs = [{"path": path, "variant": v, "num_vars": size} for v in variants]
        if size <= args.small_vars:
            for job in jobs:
                job["memory_gb"] = args.memory_limit_gb
            batches_small.append((size, jobs))
        else:
            for job in jobs:
                job["memory_gb"] = args.large_memory_limit_gb
                batches_large.append((size, [job]))
    batches_small.sort(key=lambda item: item[0])
    batches_large.sort(key=lambda item: item[0])
    return [jobs for _, jobs in batches_small + batches_large]


def kill_row(job: dict, reason_kind: str, phase: str, seconds: float, peak: int) -> dict:
    texts = {
        "memory": f"out of memory while in phase '{phase}' (limit {job['memory_gb']:g} GB)",
        "build_limit": "model not built within the build limit",
        "timeout": f"no result within the overall limit (phase '{phase}')",
        "stopped": "stopped by user (STOP file)",
        "crashed": f"process ended without a result (phase '{phase}')",
    }
    result = "model not built" if phase in ("parse", "build") else "no result"
    return {"instance": label(job["path"]), "variant": job["variant"], "result": result,
            "reason": texts[reason_kind], "num_vars": job["num_vars"],
            "build_s": fmt(seconds, 1) if phase in ("parse", "build") else "",
            "peak_rss_mb": fmt(peak / 2**20, 1)}


def run_batch(batch: list[dict], args, out: Path) -> list[dict]:
    procs = []
    for job in batch:
        jid = f"{label(job['path'])}_{job['variant']}"
        job_dir = out / "jobs" / jid
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir.mkdir(parents=True)
        command = [sys.executable, str(Path(__file__).resolve()), "--worker",
                   str(job["path"]), "--variant", job["variant"], "--job-dir", str(job_dir),
                   "--time-limit", str(args.time_limit), "--workers", str(args.workers),
                   "--random-seed", str(args.random_seed),
                   "--seed-algorithm", args.seed_algorithm, "--output-root", args.output_root,
                   "--hint-check-limit", str(args.hint_check_limit)]
        log = (job_dir / "log.txt").open("w", encoding="utf-8")
        proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        procs.append({"job": job, "dir": job_dir, "proc": proc, "log": log,
                      "start": time.time(), "peak": 0, "row": None})
        print(f"[start] {jid} ({job['num_vars']:,} variables)", flush=True)

    overall = args.build_limit + args.hint_check_limit + args.time_limit + 900
    while any(p["row"] is None for p in procs):
        time.sleep(2)
        status = [f"updated {datetime.now().isoformat(timespec='seconds')}"]
        for p in procs:
            if p["row"] is not None:
                continue
            job, proc = p["job"], p["proc"]
            phase_text = (p["dir"] / "phase.txt").read_text().split() \
                if (p["dir"] / "phase.txt").exists() else ["start", str(p["start"])]
            phase, since = phase_text[0], float(phase_text[1])
            rss = rss_bytes(proc.pid)
            p["peak"] = max(p["peak"], rss)
            elapsed = time.time() - p["start"]
            status.append(f"{p['dir'].name} | phase {phase} {time.time() - since:.0f}s | "
                          f"{rss / 2**30:.2f} GB | elapsed {elapsed:.0f}s")
            kill = None
            if (out / "STOP").exists():
                kill = "stopped"
            elif rss > job["memory_gb"] * 2**30:
                kill = "memory"
            elif phase == "build" and time.time() - since > args.build_limit:
                kill = "build_limit"
            elif elapsed > overall:
                kill = "timeout"
            if kill:
                proc.send_signal(signal.SIGKILL)
                proc.wait()
                p["row"] = kill_row(job, kill, phase, time.time() - since, p["peak"])
            elif proc.poll() is not None:
                result_file = p["dir"] / "result.json"
                if result_file.exists():
                    p["row"] = json.loads(result_file.read_text())
                    p["row"]["peak_rss_mb"] = fmt(p["peak"] / 2**20, 1)
                else:
                    p["row"] = kill_row(job, "crashed", phase, time.time() - since, p["peak"])
            if p["row"] is not None:
                p["log"].close()
                (p["dir"] / "result.json").write_text(json.dumps(p["row"], indent=2) + "\n")
                r = p["row"]
                print(f"[done] {p['dir'].name}: {r.get('result')} - {r.get('reason')} | "
                      f"LB {r.get('lower_bound', '')} UB {r.get('upper_bound', '')} "
                      f"gap {r.get('gap', '')}", flush=True)
        (out / "status.txt").write_text("\n".join(status) + "\n")
    return [p["row"] for p in procs]


def write_markdown(rows: list[dict], path: Path, args) -> None:
    def pct(value):
        return f"{float(value) * 100:.2f}%" if value not in (None, "") else ""

    def short(value, n=8):
        return str(value)[:n] if value not in (None, "") else ""

    lines = [
        "# CLIPP competition model (OR-Tools CP-SAT): cold start vs warm start",
        "",
        f"Time limit {args.time_limit:g} s per run, {args.workers} CP-SAT workers per run, "
        f"random seed {args.random_seed}, same computer for all runs. Warm start = "
        f"`{args.seed_algorithm}` solution as hint (AddHint). Objective = official score "
        "(maximise): lower bound = best valid solution, upper bound = CP-SAT bound, "
        "gap = (UB − LB) / LB.",
        "",
        "| Instance | Variant | Result | Variables | Time (s) | 1st valid (s) | Objective (LB) "
        "| Upper bound | Gap | Seed | Δ vs seed | Reason |",
        "|" + "---|" * 12,
    ]
    for r in rows:
        lines.append(
            f"| {r.get('instance')} | {r.get('variant')} | {r.get('result')} "
            f"| {int(r['num_vars']):,} | {short(r.get('solve_s') or r.get('build_s'), 7)} "
            f"| {short(r.get('first_valid_s'), 7)} | {short(r.get('lower_bound'))} "
            f"| {short(r.get('upper_bound'))} | {pct(r.get('gap'))} "
            f"| {short(r.get('seed_score'))} | {short(r.get('improvement_vs_seed'), 9)} "
            f"| {r.get('reason', '')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parent(args) -> int:
    import ortools

    out = Path(args.out).expanduser().resolve()
    existing = finished_runs(args, out)
    if existing and not args.overwrite:
        print(f"{out} already has results for: {', '.join(existing)}.\n"
              "Nothing was run. Use another --out folder (e.g. for a demo), or add "
              "--overwrite to replace these results.", file=sys.stderr)
        return 1
    if args.background:
        out.mkdir(parents=True, exist_ok=True)
        argv = [a for a in sys.argv[1:] if a != "--background"]
        command = [sys.executable, str(Path(__file__).resolve())] + argv
        if shutil.which("caffeinate"):
            command = ["caffeinate", "-dims"] + command
        log = (out / "run.txt").open("w", encoding="utf-8")
        proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        (out / "runner.pid").write_text(str(proc.pid))
        print(f"Started in the background (pid {proc.pid}). Progress: {out / 'run.txt'}, "
              f"{out / 'status.txt'}. Stop: touch {out / 'STOP'}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "STOP").unlink(missing_ok=True)
    batches = plan_jobs(args)
    power = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout \
        if shutil.which("pmset") else ""
    name = f"metadata_part{args.part}.json" if args.part else "metadata.json"
    (out / name).write_text(json.dumps({
        "part": args.part,
        "model": "CLIPP competition MILP, OR-Tools CP-SAT (tools/milp/third_party/clipp_cpsat, commit cf6ed8a)",
        "ortools": ortools.__version__, "python": platform.python_version(),
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "time_limit_s": args.time_limit, "workers": args.workers,
        "random_seed": args.random_seed, "build_limit_s": args.build_limit,
        "hint_check_limit_s": args.hint_check_limit,
        "memory_limit_gb": args.memory_limit_gb,
        "large_memory_limit_gb": args.large_memory_limit_gb, "small_vars": args.small_vars,
        "seed_algorithm": args.seed_algorithm,
        "batches": [[f"{label(j['path'])}_{j['variant']}" for j in b] for b in batches],
        "power_at_start": power.strip().splitlines()[:1],
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2) + "\n")

    def all_rows() -> list[dict]:
        """Every finished job in --out (so the parts add up to one report)."""
        rows = [json.loads(f.read_text()) for f in sorted((out / "jobs").glob("*/result.json"))]
        rank = {label(Path(p)): i for i, p in enumerate(ORDER)}
        return sorted(rows, key=lambda r: (rank.get(r["instance"], 99), r["variant"] != "cold"))

    for batch in batches:
        if (out / "STOP").exists():
            break
        run_batch(batch, args, out)
        rows = all_rows()
        with (out / "results.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        write_markdown(rows, out / "results.md", args)
        try:
            from viewer import build as build_viewer   # tools/milp/viewer.py
            build_viewer(out)
        except Exception as error:  # the viewer must never stop the experiment
            print(f"[viewer] not updated: {error}", flush=True)
    (out / "status.txt").write_text(f"finished {datetime.now().isoformat(timespec='seconds')}\n")
    print(f"Report: {out / 'results.md'}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instances", nargs="*", help="instance files (default: all 15)")
    parser.add_argument("--variants", nargs="+", choices=["cold", "warm"],
                        default=["cold", "warm"])
    parser.add_argument("--part", type=int, choices=sorted(PARTS),
                        help="run one part of the experiment (1: A-C, 2: D, E, Presheva, "
                             "3: other cities, warm)")
    parser.add_argument("--cold-instances", nargs="*",
                        help="instances that get a cold run (default: A-E and Presheva)")
    parser.add_argument("--time-limit", type=float, default=3600.0,
                        help="CP-SAT time per run in seconds (default 3600)")
    parser.add_argument("--workers", type=int, default=4, help="CP-SAT workers (default 4)")
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--build-limit", type=float, default=3600.0,
                        help="stop a run whose model is not built after this (default 3600 s)")
    parser.add_argument("--hint-check-limit", type=float, default=600.0,
                        help="time for checking the warm-start hint (default 600 s)")
    parser.add_argument("--memory-limit-gb", type=float, default=9.0,
                        help="per run, small instances (2 run together; default 9)")
    parser.add_argument("--large-memory-limit-gb", type=float, default=19.0,
                        help="per run, large instances (one at a time; default 19)")
    parser.add_argument("--small-vars", type=int, default=200_000,
                        help="instances up to this many variables run in cold/warm pairs")
    parser.add_argument("--seed-algorithm", default="dp_simple",
                        help="folder in --output-root with the warm-start solutions")
    parser.add_argument("--output-root", default=str(ROOT / "data/output"))
    parser.add_argument("--out", default=str(TOOL / "results"))
    parser.add_argument("--overwrite", action="store_true",
                        help="replace runs that already have a result in --out")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--variant", help=argparse.SUPPRESS)
    parser.add_argument("--job-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        args.instance = args.instances[0]
        return worker(args)
    if args.part:
        if args.instances:
            parser.error("give either --part or instance files, not both")
        args.instances = PARTS[args.part]                       # relative to ROOT
        args.cold_instances = [p for p in args.instances if p in COLD_DEFAULT]
    else:                                                       # relative to the shell
        if args.instances:
            args.instances = [str(absolute(p, Path.cwd())) for p in args.instances]
        if args.cold_instances is not None:
            args.cold_instances = [str(absolute(p, Path.cwd())) for p in args.cold_instances]
    return parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
