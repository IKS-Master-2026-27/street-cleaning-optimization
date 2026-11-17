"""Plan and run measurements, one subprocess per (algorithm, instance, mode).

Results are appended to data/output/complexity/results.jsonl. A measurement is
reused while the source files of its algorithm are unchanged (a fingerprint of
the algorithm's module and everything it imports from the project) and the
instance file has the same content, so adding a new algorithm only measures
the new one.
"""

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import OUTPUT, ROOT, SCHEMA
from .instances import InstanceInfo, content_hash
from .worker import RESULT_MARK

MODES = ("time", "memory", "profile", "fmemory")
RESULTS = "results.jsonl"


# --------------------------------------------------------------- fingerprints
def _module_file(name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if not spec or not spec.origin or not spec.origin.endswith(".py"):
        return None
    path = Path(spec.origin).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    return path


def _imports(path: Path, package: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            names.add(prefix)
            names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return names


def dependency_files(module: str) -> list[Path]:
    """The module's file and every project file it imports, transitively."""
    seen: dict[str, Path] = {}
    stack = [module]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        path = _module_file(name)
        if path is None:
            continue
        seen[name] = path
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        stack.extend(_imports(path, package))
    return sorted(set(seen.values()))


# What every measurement also depends on besides the algorithm: how the worker
# measures, and the parser, validator and scoring it checks solutions with.
# Listed explicitly: following the worker's own imports would pull in main.py and
# so every algorithm, and one algorithm's change would invalidate all of them.
CHECK_MODULES = ("clipp.parser", "clipp.validator", "clipp.scoring")


def measurement_files() -> list[Path]:
    files = {Path(__file__).with_name("worker.py").resolve()}
    for name in CHECK_MODULES:
        files.update(dependency_files(name))
    return sorted(files)


def fingerprint(module: str) -> str:
    digest = hashlib.sha1(f"schema{SCHEMA}".encode())
    for path in sorted(set(dependency_files(module)) | set(measurement_files())):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def revision() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "clipp", "main.py"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5).stdout
        return f"{head}-dirty" if dirty.strip() else head
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ------------------------------------------------------------------- storage
def load_records(folder: Path = OUTPUT) -> list[dict]:
    path = folder / RESULTS
    records = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as source:
        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("schema") == SCHEMA:
                records.append(record)
    return records


def latest(records: list[dict]) -> dict[tuple, dict]:
    """Newest record per (algorithm, instance path, mode)."""
    found = {}
    for record in records:
        found[(record["algorithm"], record["instance"]["path"], record["mode"])] = record
    return found


def _append(record: dict, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / RESULTS, "a", encoding="utf-8") as target:
        target.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------- jobs
@dataclass
class Job:
    algorithm: str
    instance: InstanceInfo
    mode: str
    fingerprint: str
    input_hash: str = ""

    @property
    def label(self) -> str:
        return f"{self.algorithm} · {self.instance.name} · {self.mode}"


@dataclass
class Plan:
    jobs: list[Job] = field(default_factory=list)
    cached: int = 0


def plan(algorithms: dict, instances: list[InstanceInfo], modes=MODES,
         fresh: bool = False, folder: Path = OUTPUT) -> Plan:
    known = latest(load_records(folder))
    result = Plan()
    prints = {name: fingerprint(a.function.__module__) for name, a in algorithms.items()}
    for instance in sorted(instances, key=lambda i: (i.streets, i.name)):
        data = content_hash(instance.path)
        for name in algorithms:
            for mode in modes:
                previous = known.get((name, instance.path, mode))
                if (not fresh and previous and previous.get("fingerprint") == prints[name]
                        and previous.get("input_hash") == data
                        and previous.get("status") in ("ok", "invalid", "error", "timeout")):
                    result.cached += 1
                    continue
                result.jobs.append(Job(name, instance, mode, prints[name], data))
    return result


def estimate(jobs: list[Job], timeout: float, folder: Path = OUTPUT) -> dict:
    """Rough duration of a plan, from earlier measurements' wall time.

    A job measured before (same algorithm, instance, mode) takes what it took.
    Otherwise the closest instance measured for that algorithm and mode is
    scaled by (streets ratio)^1.5, and failing that the median of other
    algorithms on that instance. Every job is capped at its time limit.
    """
    records = [r for r in latest(load_records(folder)).values() if r.get("wall_seconds")]
    by_alg_mode: dict[tuple, list[dict]] = {}
    by_inst_mode: dict[tuple, list[float]] = {}
    for r in records:
        by_alg_mode.setdefault((r["algorithm"], r["mode"]), []).append(r)
        by_inst_mode.setdefault((r["instance"]["path"], r["mode"]), []).append(r["wall_seconds"])
    total, unknown, timeouts = 0.0, 0, 0
    for job in jobs:
        limit = _timeout_for(job.mode, timeout)
        known = by_alg_mode.get((job.algorithm, job.mode), [])
        same = next((r for r in known if r["instance"]["path"] == job.instance.path), None)
        guess = None
        if same:
            guess = same["wall_seconds"]
            if same["status"] == "timeout":
                timeouts += 1
                guess = limit
        elif known:
            near = min(known, key=lambda r: abs(r["instance"]["streets"] - job.instance.streets))
            if near["status"] == "timeout" and near["instance"]["streets"] <= job.instance.streets:
                timeouts += 1
                guess = limit
            else:
                ratio = max(job.instance.streets, 1) / max(near["instance"]["streets"], 1)
                guess = near["wall_seconds"] * (ratio ** 1.5 if ratio > 1 else ratio)
        elif by_inst_mode.get((job.instance.path, job.mode)):
            others = sorted(by_inst_mode[(job.instance.path, job.mode)])
            guess = others[len(others) // 2]
        if guess is None:
            unknown += 1
            continue
        total += min(guess, limit)
    return {"seconds": round(total, 1), "unknown": unknown, "likely_timeouts": timeouts}


def _timeout_for(mode: str, base: float) -> float:
    return base * (3 if mode in ("profile", "fmemory") else 1)


class Runner:
    """Runs jobs one after another (parallel runs would distort the timings)."""

    def __init__(self, repeat: int = 3, timeout: float = 300.0, folder: Path = OUTPUT,
                 on_event: Callable[[dict], None] | None = None):
        self.repeat = repeat
        self.timeout = timeout
        self.folder = folder
        self.on_event = on_event or (lambda event: None)
        self.cancelled = threading.Event()
        self._process: subprocess.Popen | None = None
        self._revision = revision()

    def cancel(self) -> None:
        self.cancelled.set()
        process = self._process
        if process and process.poll() is None:
            process.kill()

    def run_job(self, job: Job) -> dict:
        command = [sys.executable, "-m", "tools.complexity.worker", job.algorithm,
                   job.instance.path, job.mode, "--repeat", str(self.repeat)]
        env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        started = time.perf_counter()
        status_override = None
        try:
            self._process = subprocess.Popen(command, cwd=ROOT, env=env, text=True,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = self._process.communicate(timeout=_timeout_for(job.mode, self.timeout))
        except subprocess.TimeoutExpired:
            self._process.kill()
            stdout, stderr = self._process.communicate()
            status_override = "timeout"
        finally:
            returncode = self._process.returncode if self._process else None
            self._process = None
        result = None
        for line in (stdout or "").splitlines():
            if line.startswith(RESULT_MARK):
                result = json.loads(line[len(RESULT_MARK):])
        if status_override:
            result = {"status": "timeout",
                      "error": f"stopped after {_timeout_for(job.mode, self.timeout):.0f} s"}
        elif self.cancelled.is_set() and result is None:
            result = {"status": "cancelled"}
        elif result is None:
            tail = (stderr or "").strip().splitlines()[-3:]
            result = {"status": "error",
                      "error": f"worker exited with {returncode}: {' | '.join(tail)}"}
        return {
            "schema": SCHEMA,
            "algorithm": job.algorithm,
            "instance": job.instance.to_dict(),
            "mode": job.mode,
            "fingerprint": job.fingerprint,
            "input_hash": job.input_hash,
            "revision": self._revision,
            "python": sys.version.split()[0],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "wall_seconds": round(time.perf_counter() - started, 4),
            **result,
        }

    def run(self, jobs: list[Job]) -> list[dict]:
        records = []
        stopped: set[tuple[str, str]] = set()  # (algorithm, mode) that timed out
        total = len(jobs)
        self.on_event({"type": "plan", "total": total})
        for index, job in enumerate(jobs, 1):
            if self.cancelled.is_set():
                self.on_event({"type": "cancelled", "done": index - 1, "total": total})
                break
            if (job.algorithm, job.mode) in stopped:
                self.on_event({"type": "skip", "index": index, "total": total,
                               "label": job.label, "reason": "timed out on a smaller instance"})
                continue
            self.on_event({"type": "start", "index": index, "total": total, "label": job.label})
            record = self.run_job(job)
            if record["status"] == "cancelled":
                self.on_event({"type": "cancelled", "done": index - 1, "total": total})
                break
            _append(record, self.folder)
            records.append(record)
            if record["status"] == "timeout":
                stopped.add((job.algorithm, job.mode))
            self.on_event({"type": "done", "index": index, "total": total, "label": job.label,
                           "status": record["status"], "wall_seconds": record["wall_seconds"]})
        else:
            self.on_event({"type": "finished", "total": total})
        return records
