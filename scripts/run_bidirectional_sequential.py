"""Run the long Bidirectional Search experiments strictly one at a time.

* exactly one search process at a time;
* before each start, wait until the previous process has exited and enough
  physical memory is free (``--min-free-mb``); while waiting, a line is logged
  every few minutes and nothing is launched;
* each result is appended to data/output/bidirectional_search/sequential_runs.jsonl
  as soon as the process exits (resumable: jobs with a stored result are skipped);
* a hard process timeout of time limit + 30 min protects against hangs.

    python scripts/run_bidirectional_sequential.py --plan all
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output" / "bidirectional_search"
LOG = OUT / "sequential_runs.jsonl"
SYN = {x: ROOT / f"data/input/syntetic_generated/instance_{x}.txt" for x in "ABCDE"}
CITY = lambda c: ROOT / f"data/input/real_instances/{c}/instance.txt"  # noqa: E731
LARGE = ["Ljubljana", "Vienna", "New-York", "Johannesburg", "Sydney"]
OTHER = ["Presheva", "Ulqini", "Prishtina", "Shkupi", "Tirana"]
FOUR_HOURS = 14400


def free_mb() -> float | None:
    if os.name == "nt":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        s = Status()
        s.dwLength = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return s.ullAvailPhys / 2**20
        return None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def jobs(plan: str):
    """(key, instance path, mode, extra args, time limit).

    Only configurations that were never run. Class-reduction runs exist for
    all ten cities (benchmark.csv, large_cities_1500s.jsonl) and are not
    repeated, whatever their outcome (a TIMEOUT is a completed experiment).
    """
    out = []
    if plan in ("all", "exact"):
        for x in "BCDE":  # BDS-Exact on the remaining synthetic instances
            out.append((f"instance_{x}|exact|4h", SYN[x], "exact", ["--memory-limit-mb", "3500"],
                        FOUR_HOURS))
        out.append(("Presheva|exact|4h", CITY("Presheva"), "exact",
                    ["--memory-limit-mb", "3500"], FOUR_HOURS))
        for c in OTHER[1:] + LARGE:  # > 1500 junctions: exact mode is not applicable
            out.append((f"{c}|exact|na", CITY(c), "exact", [], 60))
    if plan in ("all", "unrestricted"):
        for c in OTHER[1:] + LARGE:  # BDS-Bounded without class reduction
            out.append((f"{c}|bounded|4h", CITY(c), "bounded", [], FOUR_HOURS))
    return out


def _config(instance: str, mode: str, class_reduction) -> tuple[str, str, bool]:
    name = instance.replace("_instance", "")
    return name, mode, str(class_reduction).lower() in ("true", "1")


def completed() -> set[tuple[str, str, bool]]:
    """(instance, mode, class_reduction) of every recorded run, any outcome.

    Reads benchmark.csv, benchmark_exact.csv, large_cities_1500s.jsonl and
    sequential_runs.jsonl. Only a record the runner itself marked KILLED (its
    process was terminated from outside) does not count.
    """
    import csv
    done = set()
    for name in ("benchmark.csv", "benchmark_exact.csv"):
        path = OUT / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("status") and r.get("mode"):
                        done.add(_config(r["instance"], r["mode"], r["class_reduction"]))
    for name in ("large_cities_1500s.jsonl", LOG.name):
        path = OUT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") in (None, "KILLED") or not r.get("instance"):
                continue
            done.add(_config(r["instance"], r.get("mode", ""), r.get("class_reduction")))
    return done


def job_config(path: Path, mode: str, extra: list[str]) -> tuple[str, str, bool]:
    name = path.parent.name if path.stem == "instance" else path.stem
    return name, mode, "--class-reduction" in extra


TIMEOUT_CITIES = ["Vienna", "New-York", "Johannesburg", "Sydney"]
NO_MEETING = ["C", "E"]
ALTERNATIVES = {   # controlled alternative BDS-Bounded configurations for NO_MEETING
    "alt1-W512-K16": ["--width", "512", "--candidates", "16"],
    "alt2-W2048-K16": ["--width", "2048", "--candidates", "16"],
    "alt3-W512-K16-ov3-b0.005": ["--width", "512", "--candidates", "16", "--overlap", "3.0",
                                 "--bucket-fraction", "0.005"],
}


def score_jobs():
    """Plan 'scores': attempts that can still produce a numerical score.

    (key, path, mode, extra, limit, rule). Rules: 'once' = run unless this
    attempt key is already recorded; 'if_no_score' = run only while the
    instance has no validator-passing score in any results file; 'config' = the
    old rule (skip if this mode/configuration was ever recorded).
    """
    out = []
    for x in NO_MEETING:       # NO_MEETING: controlled alternative configurations (short)
        for name, extra in ALTERNATIVES.items():
            out.append((f"instance_{x}|bounded|{name}", SYN[x], "bounded", extra, 3600, "once"))
    for c in TIMEOUT_CITIES:   # TIMEOUT without a score: retry with 4 h (new attempt)
        out.append((f"{c}|bounded+classred|attempt2-4h", CITY(c), "bounded",
                    ["--class-reduction"], FOUR_HOURS, "once"))
    for c in TIMEOUT_CITIES:   # still no score: unrestricted BDS-Bounded (no class reduction)
        out.append((f"{c}|bounded|unrestricted-4h", CITY(c), "bounded", [], FOUR_HOURS,
                    "if_no_score"))
    for x in "CDE":            # remaining pending BDS-Exact attempts (lowest priority)
        out.append((f"instance_{x}|exact|4h", SYN[x], "exact", ["--memory-limit-mb", "3500"],
                    FOUR_HOURS, "config"))
    out.append(("Presheva|exact|4h", CITY("Presheva"), "exact", ["--memory-limit-mb", "3500"],
                FOUR_HOURS, "config"))
    return out


SPLITS = {"C": ["0.475", "0.45"], "E": ["0.525", "0.55"]}


def split_jobs():
    """Plan 'split': asymmetric forward/backward share splits for C and E only.

    0.5 is the default (already recorded as NO_MEETING). The values balance the
    mandatory service time between the two sides (C 0.475, E 0.525) or move one
    step further in the same direction (C 0.45, E 0.55). All other settings are
    the defaults.
    """
    return [(f"instance_{x}|bounded|split{v}", SYN[x], "bounded", ["--share-split", v], 3600,
             "once") for x, values in SPLITS.items() for v in values]


def recorded_keys() -> set[str]:
    keys = set()
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") != "KILLED":
                keys.add(r.get("job"))
    return keys


def scored_instances() -> set[str]:
    """Instances with a validator-passing numerical score in any results file."""
    import csv
    done = set()
    for name in ("benchmark.csv", "benchmark_exact.csv"):
        path = OUT / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("valid") == "True" and r.get("score"):
                        done.add(r["instance"].replace("_instance", ""))
    for name in ("large_cities_1500s.jsonl", LOG.name):
        path = OUT / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("valid") and r.get("score") is not None:
                    done.add(str(r.get("instance", "")).replace("_instance", ""))
    return done


def should_skip(key, path, mode, extra, rule) -> str | None:
    if rule == "once" and key in recorded_keys():
        return "this attempt is already recorded"
    if rule == "if_no_score" and job_config(path, mode, extra)[0] in scored_instances():
        return "the instance already has a validator-passing score"
    if rule == "config" and job_config(path, mode, extra) in completed():
        return "a completed result is already recorded"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default="scores",
                    choices=("scores", "split", "all", "exact", "unrestricted"))
    ap.add_argument("--log", help="results file name in data/output/bidirectional_search")
    ap.add_argument("--min-free-mb", type=float, default=3000.0)
    ap.add_argument("--memory-limit-mb", type=float, default=4500.0,
                    help="per-process limit for bounded runs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.log:
        global LOG
        LOG = OUT / args.log
    plan = (score_jobs() if args.plan == "scores" else split_jobs() if args.plan == "split"
            else [(*j, "config") for j in jobs(args.plan)])
    for key, path, mode, extra, limit, rule in plan:
        reason = should_skip(key, path, mode, extra, rule)   # re-read files before every job
        if reason:
            print(f"skip {key} ({reason})", flush=True)
            continue
        if args.dry_run:
            print(f"would run {key}: {mode} {' '.join(extra)} limit={limit}s", flush=True)
            continue
        waited = 0
        while (free_mb() or 0) < args.min_free_mb:
            if waited % 300 == 0:
                print(f"waiting for memory before {key}: {free_mb():.0f} MB free "
                      f"< {args.min_free_mb:.0f} MB", flush=True)
            time.sleep(30)
            waited += 30
        cmd = [sys.executable, "-B", "-m", "clipp.bidirectional_search", str(path),
               "--mode", mode, "--json", "--time-limit", str(limit), *extra]
        if mode == "bounded":
            cmd += ["--memory-limit-mb", str(args.memory_limit_mb)]
        print(f"start {key} ({free_mb():.0f} MB free)", flush=True)
        started = time.time()
        try:
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                  timeout=limit + 1800)
            lines = [l for l in proc.stdout.splitlines() if l.startswith("{")]
            record = json.loads(lines[-1]) if lines else {
                "status": "ERROR", "message": (proc.stderr or proc.stdout)[-600:]}
        except subprocess.TimeoutExpired:
            record = {"status": "KILLED", "message": f"process exceeded {limit + 1800:.0f} s"}
        record.update(job=key, wall_s=time.time() - started,
                      free_mb_after=free_mb(), command=" ".join(cmd[1:]))
        with open(LOG, "a", encoding="utf-8") as f:   # saved before the next job starts
            f.write(json.dumps(record, default=str) + "\n")
        print(f"done {key}: {record.get('report_status', record.get('status'))} "
              f"score={record.get('score')} {record['wall_s']:.0f}s", flush=True)
    print("all jobs finished", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
