"""Measure execution time only for algorithms with published results.

Scores always come from the solution files published in the shared
repository (``data/output/<algorithm>/``) and are computed by InstanceLab
without running any algorithm. The published files carry no timings, so this
module re-runs exactly the published (instance, algorithm) pairs to measure
time. Algorithms without published results are never executed.

A published folder is runnable when its name equals a key of the shared
``main.py`` ``ALGORITHMS`` table with ``-`` replaced by ``_`` (the naming rule
``main.py`` itself uses when writing results). Other folders, such as variants
produced on modified instances, are reported as not timeable.

Each run is an isolated Python subprocess with a timeout. Only the algorithm
call is timed. The re-run solution is written to an InstanceLab-owned
directory, re-scored independently and compared with the published score, so a
timing row is also a reproducibility check. Nothing is written to the shared
repository; bytecode caching is disabled for workers.

Usage::

    python -m instancelab.timing --shared-repo C:\\path\\to\\street-cleaning-optimization
        [--output results/timing] [--timeout 1800] [--workers 1] [--only Presheva]
"""

import argparse
import csv
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from math import isclose
from pathlib import Path

from .adapters.shared_repository import InstanceSource, scan_shared_instances
from .adapters.shared_results import (
    SolutionResultError,
    _solution_name,
    score_solution_file,
)
from .model import Instance
from .performance import AlgorithmResult

TIMING_FIELDS = (
    "instance",
    "group",
    "algorithm",
    "status",
    "seconds",
    "published_score",
    "run_score",
    "score_matches",
    "reason",
)
STATUSES = ("ok", "failed", "invalid", "timeout", "crashed")
SCORE_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class TimingRecord:
    """One timed re-run of a published (instance, algorithm) pair."""

    instance: str
    group: str
    algorithm: str
    status: str
    seconds: float | None = None
    published_score: float | None = None
    run_score: float | None = None
    score_matches: bool | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TimingPlan:
    """Which published pairs will be timed and which folders cannot be."""

    jobs: tuple[tuple[InstanceSource, Instance, str, str], ...]
    not_timeable: tuple[tuple[str, str], ...]


def load_shared_algorithm_table(shared_repo: str | Path) -> dict:
    """Import ``ALGORITHMS`` from the shared ``main.py`` without running it."""

    root = Path(shared_repo).resolve()
    main_path = root / "main.py"
    if not main_path.is_file():
        raise FileNotFoundError(f"Shared main.py not found: {main_path}")
    sys.dont_write_bytecode = True
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("clipp_shared_main", main_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.ALGORITHMS)


def published_algorithm_folders(shared_repo: str | Path) -> tuple[str, ...]:
    output_root = Path(shared_repo) / "data" / "output"
    if not output_root.is_dir():
        return ()
    return tuple(
        sorted(
            directory.name
            for directory in output_root.iterdir()
            if directory.is_dir() and any(directory.glob("*_solution.txt"))
        )
    )


def plan_timing(
    shared_repo: str | Path,
    algorithm_keys: tuple[str, ...],
    only: tuple[str, ...] = (),
) -> TimingPlan:
    """List published pairs whose folder maps to a runnable algorithm."""

    repository = Path(shared_repo).resolve()
    by_folder = {key.replace("-", "_"): key for key in algorithm_keys}
    loaded = scan_shared_instances(repository).loaded
    if only:
        loaded = tuple(pair for pair in loaded if pair[0].name in set(only))
    jobs = []
    not_timeable = []
    for folder in published_algorithm_folders(repository):
        key = by_folder.get(folder)
        if key is None:
            not_timeable.append(
                (folder, "no algorithm with this name is registered in main.py")
            )
            continue
        for source, instance in loaded:
            published = repository / "data" / "output" / folder / _solution_name(source)
            if published.is_file():
                jobs.append((source, instance, folder, key))
    return TimingPlan(tuple(jobs), tuple(not_timeable))


def _worker(shared_repo: str, algorithm: str, instance_path: str, solution_path: str) -> int:
    """Subprocess entry point: solve once and print one JSON status line."""

    try:
        algorithms = load_shared_algorithm_table(shared_repo)
        from clipp.output import write_solution
        from clipp.parser import parse_instance

        instance = parse_instance(instance_path)
        start = time.perf_counter()
        solution = algorithms[algorithm](instance)
        seconds = time.perf_counter() - start
        Path(solution_path).parent.mkdir(parents=True, exist_ok=True)
        write_solution(solution, Path(solution_path))
        print(json.dumps({"status": "solved", "seconds": seconds}))
    except Exception as error:  # noqa: BLE001 - any solver failure is data
        message = f"{type(error).__name__}: {error}".replace("\n", " ")[:500]
        print(json.dumps({"status": "failed", "reason": message}))
    return 0


def time_one(
    shared_repo: Path,
    source: InstanceSource,
    instance: Instance,
    folder: str,
    key: str,
    output_dir: Path,
    timeout: float,
) -> TimingRecord:
    """Time one published pair and compare the re-run score with the published one."""

    published = score_solution_file(
        instance,
        shared_repo / "data" / "output" / folder / _solution_name(source),
        instance_name=source.name,
        algorithm=folder,
    ).score
    base = {
        "instance": source.name,
        "group": source.group,
        "algorithm": folder,
        "published_score": published,
    }
    solution_path = output_dir / "solutions" / folder / _solution_name(source)
    if solution_path.exists():
        solution_path.unlink()
    command = [
        sys.executable, "-m", "instancelab.timing", "--worker",
        str(shared_repo), key, str(source.path), str(solution_path),
    ]
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=environment,
            cwd=str(output_dir),
        )
    except subprocess.TimeoutExpired:
        return TimingRecord(**base, status="timeout", reason=f"exceeded {timeout:g} s")

    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if completed.returncode != 0 or not lines:
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-1:] or [""]
        return TimingRecord(
            **base, status="crashed",
            reason=f"exit code {completed.returncode}: {tail[0][:300]}",
        )
    outcome = json.loads(lines[-1])
    if outcome["status"] != "solved":
        return TimingRecord(**base, status="failed", reason=outcome.get("reason", ""))
    try:
        run_score = score_solution_file(
            instance, solution_path, instance_name=source.name, algorithm=folder
        ).score
    except (OSError, SolutionResultError) as error:
        return TimingRecord(
            **base, status="invalid", seconds=outcome["seconds"], reason=str(error)
        )
    matches = isclose(run_score, published, abs_tol=SCORE_TOLERANCE)
    return TimingRecord(
        **base,
        status="ok",
        seconds=outcome["seconds"],
        run_score=run_score,
        score_matches=matches,
        reason="" if matches else "re-run score differs from published score",
    )


def _format(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_timing_csv(path: str | Path, records) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda row: (row.group, row.instance, row.algorithm))
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(TIMING_FIELDS)
        for record in ordered:
            row = asdict(record)
            writer.writerow(_format(row[name]) for name in TIMING_FIELDS)


def read_timing_csv(path: str | Path) -> tuple[TimingRecord, ...]:
    """Read a timing CSV written by :func:`write_timing_csv`."""

    def number(text: str) -> float | None:
        return float(text) if text.strip() else None

    def flag(text: str) -> bool | None:
        return None if not text.strip() else text.strip() == "True"

    records = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(TIMING_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Timing CSV is missing columns: {sorted(missing)}")
        for row in reader:
            if row["status"] not in STATUSES:
                raise ValueError(f"Unknown timing status {row['status']!r}")
            records.append(
                TimingRecord(
                    instance=row["instance"],
                    group=row["group"],
                    algorithm=row["algorithm"],
                    status=row["status"],
                    seconds=number(row["seconds"]),
                    published_score=number(row["published_score"]),
                    run_score=number(row["run_score"]),
                    score_matches=flag(row["score_matches"]),
                    reason=row["reason"],
                )
            )
    keys = [(record.instance, record.algorithm) for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Timing CSV contains duplicate instance/algorithm rows")
    return tuple(records)


def attach_execution_times(
    results,
    timings,
) -> tuple[AlgorithmResult, ...]:
    """Add measured seconds to published-score results.

    A time is attached only when the re-run succeeded, reproduced the
    published score, and that published score is still the current one. A
    solution republished after timing therefore loses its stale time until it
    is timed again.
    """

    timed = {
        (record.instance, record.algorithm): record
        for record in timings
        if record.status == "ok" and record.score_matches and record.seconds is not None
    }
    attached = []
    for result in results:
        record = timed.get((result.instance_name, result.algorithm))
        current = (
            record is not None
            and record.published_score is not None
            and isclose(record.published_score, result.score, abs_tol=SCORE_TOLERANCE)
        )
        attached.append(
            replace(result, execution_time_seconds=record.seconds if current else None)
        )
    return tuple(attached)


def stale_timings(results, timings) -> tuple[TimingRecord, ...]:
    """Timing rows whose published solution has changed since they were measured."""

    current = {(result.instance_name, result.algorithm): result.score for result in results}
    return tuple(
        record
        for record in timings
        if (record.instance, record.algorithm) in current
        and record.published_score is not None
        and not isclose(
            record.published_score,
            current[(record.instance, record.algorithm)],
            abs_tol=SCORE_TOLERANCE,
        )
    )


def _git_revision(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        return completed.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_timing(
    shared_repo: str | Path,
    output_dir: str | Path,
    *,
    only: tuple[str, ...] = (),
    timeout: float = 1800.0,
    workers: int = 1,
    resume: bool = False,
    log=print,
) -> tuple[TimingRecord, ...]:
    """Time every published runnable pair and write ``results.csv`` + ``metadata.json``."""

    repository = Path(shared_repo).resolve()
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    plan = plan_timing(repository, tuple(load_shared_algorithm_table(repository)), only)
    for folder, reason in plan.not_timeable:
        log(f"Not timed: {folder} ({reason})")

    csv_path = directory / "results.csv"
    records = {}
    if resume and csv_path.is_file():
        published = {
            (source.name, folder): score_solution_file(
                instance,
                repository / "data" / "output" / folder / _solution_name(source),
                instance_name=source.name,
                algorithm=folder,
            ).score
            for source, instance, folder, _ in plan.jobs
        }
        # Keep a finished row only if its published solution is unchanged.
        records = {
            (r.instance, r.algorithm): r
            for r in read_timing_csv(csv_path)
            if r.status in {"ok", "timeout"}
            and (r.instance, r.algorithm) in published
            and r.published_score is not None
            and isclose(
                r.published_score,
                published[(r.instance, r.algorithm)],
                abs_tol=SCORE_TOLERANCE,
            )
        }
    jobs = [job for job in plan.jobs if (job[0].name, job[2]) not in records]
    jobs.sort(key=lambda job: -job[0].path.stat().st_size)
    log(f"{len(jobs)} published pair(s) to time")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(time_one, repository, source, instance, folder, key, directory, timeout)
            for source, instance, folder, key in jobs
        ]
        for done, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            records[(record.instance, record.algorithm)] = record
            write_timing_csv(csv_path, records.values())
            seconds = f"{record.seconds:.2f}s" if record.seconds is not None else "-"
            log(
                f"[{done}/{len(jobs)}] {record.instance:14} {record.algorithm:12} "
                f"{record.status:8} time={seconds} match={record.score_matches} "
                f"{record.reason[:80]}"
            )

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shared_repository_revision": _git_revision(repository),
        "timed_algorithms": sorted({job[2] for job in plan.jobs}),
        "not_timeable": [{"folder": f, "reason": r} for f, r in plan.not_timeable],
        "timeout_seconds": timeout,
        "workers": workers,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "timing": "time.perf_counter around the algorithm call only; one run per pair",
    }
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return tuple(records.values())


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["--worker"]:
        return _worker(*arguments[1:5])

    parser = argparse.ArgumentParser(
        description="Time published shared-repository algorithm results."
    )
    parser.add_argument("--shared-repo", default=os.environ.get("CLIPP_SHARED_REPO"))
    parser.add_argument("--output", default="results/timing")
    parser.add_argument("--only", nargs="*", default=())
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(arguments)
    if not args.shared_repo:
        parser.error("--shared-repo or CLIPP_SHARED_REPO is required")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run_timing(
        args.shared_repo,
        args.output,
        only=tuple(args.only),
        timeout=args.timeout,
        workers=args.workers,
        resume=args.resume,
        log=lambda message: print(message, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
