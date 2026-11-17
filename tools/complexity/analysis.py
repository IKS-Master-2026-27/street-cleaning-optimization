"""Turn stored measurements into the data model the dashboard and report use."""

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT, SCHEMA
from .fit import growth
from .instances import content_hash
from .runner import fingerprint, latest

ALL = "all"


def _outdated(record: dict, current_print: str | None, current_inputs: dict) -> bool:
    """Measured with other code, or on an instance file that has changed since."""
    if current_print and record.get("fingerprint") != current_print:
        return True
    current_input = current_inputs.get(record["instance"]["path"])
    measured_input = record.get("input_hash")
    return bool(current_input and measured_input and measured_input != current_input)


def function_key(function) -> str:
    try:
        file = Path(function.__code__.co_filename).resolve().relative_to(ROOT).as_posix()
    except (AttributeError, ValueError):
        file = function.__module__.replace(".", "/") + ".py"
    return f"{file}:{function.__qualname__}"


def _families(instances: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for instance in instances:
        groups.setdefault(instance["family"], []).append(instance)
    groups[ALL] = list(instances)
    return groups


def _growth_block(instances, values_by_path):
    """Measured growth of one quantity, per instance family and overall."""
    out = {}
    for family, members in _families(instances).items():
        members = [m for m in members if values_by_path.get(m["path"]) is not None]
        xs = [m["streets"] for m in members]
        ys = [values_by_path[m["path"]] for m in members]
        out[family] = {"fit": growth(xs, ys).to_dict()}
    return out


def build(records: list[dict], algorithms: dict) -> dict:
    newest = latest(records)
    current_prints = {}
    for name, algorithm in algorithms.items():
        try:
            current_prints[name] = fingerprint(algorithm.function.__module__)
        except OSError:
            current_prints[name] = None

    instances_by_path = {}
    for record in newest.values():
        instances_by_path[record["instance"]["path"]] = record["instance"]
    instances = sorted(instances_by_path.values(), key=lambda i: (i["streets"], i["name"]))
    current_inputs = {}
    for path in instances_by_path:
        try:
            current_inputs[path] = content_hash(path)
        except OSError:  # instance file removed: nothing to compare against
            current_inputs[path] = None

    names = list(algorithms) + sorted({r["algorithm"] for r in newest.values()} - set(algorithms))
    result_algorithms = []
    result_functions = {}
    profiled = {}
    for name in names:
        mine = {(path, mode): r for (alg, path, mode), r in newest.items() if alg == name}
        algorithm = algorithms.get(name)
        key = function_key(algorithm.function) if algorithm else None

        # every mode counts: re-measuring only time must not hide an old profile
        stale_modes = sorted({mode for (path, mode), r in mine.items()
                              if _outdated(r, current_prints.get(name), current_inputs)})

        runs = []
        seconds, peaks = {}, {}
        for instance in instances:
            path = instance["path"]
            t, m = mine.get((path, "time")), mine.get((path, "memory"))
            if not t and not m:
                continue
            status = (t or m)["status"]
            run = {"instance": instance["name"], "path": path, "family": instance["family"],
                   "streets": instance["streets"], "junctions": instance["junctions"],
                   "status": status,
                   "seconds": t.get("seconds") if t and t["status"] == "ok" else None,
                   "runs": t.get("runs") if t else None,
                   "peak_bytes": m.get("peak_bytes") if m and m["status"] == "ok" else None,
                   "max_rss_bytes": m.get("max_rss_bytes") if m else None,
                   "score": (t or m).get("score"),
                   "error": (t or m).get("error") or "; ".join((t or m).get("errors") or [])}
            if t and m and t["status"] != m["status"]:
                run["status"] = t["status"] if t["status"] != "ok" else m["status"]
            runs.append(run)
            if run["seconds"] is not None:
                seconds[path] = run["seconds"]
            if run["peak_bytes"] is not None:
                peaks[path] = run["peak_bytes"]

        result_algorithms.append({
            "name": name,
            "source": algorithm.source if algorithm else "removed",
            "location": key,
            "stale": bool(stale_modes),
            "stale_modes": stale_modes,
            "runs": runs,
            "time": _growth_block(instances, seconds),
            "memory": _growth_block(instances, peaks),
        })
        result_functions[name] = _functions(mine, instances)
        profiled[name] = {r["instance"]["name"]: r.get("profiled_seconds")
                          for (path, mode), r in mine.items()
                          if mode == "profile" and r.get("status") == "ok"}

    return {
        "schema": SCHEMA,
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "revision": next((r.get("revision") for r in reversed(records)), None),
            "python": sys.version.split()[0],
            "platform": platform.platform(terse=True),
            "measurements": len(newest),
            "size_variable": "n = number of streets (M)",
        },
        "instances": instances,
        "algorithms": result_algorithms,
        "functions": result_functions,
        "profiled": profiled,  # algorithm -> instance -> total profiled seconds
    }


def _functions(mine: dict, instances: list[dict]) -> list[dict]:
    per_function: dict[str, dict] = {}
    profiled_total = {}
    for instance in instances:
        path = instance["path"]
        profile = mine.get((path, "profile"))
        memory = mine.get((path, "fmemory"))
        if profile and profile.get("status") == "ok":
            profiled_total[path] = profile.get("profiled_seconds")
            for key, stats in profile.get("functions", {}).items():
                entry = per_function.setdefault(key, {})
                entry.setdefault(path, {}).update({
                    "calls": stats["calls"], "own": stats["own_seconds"],
                    "cum": stats["cum_seconds"], "line": stats.get("line")})
        if memory and memory.get("status") == "ok":
            for key, peak in memory.get("function_peak_bytes", {}).items():
                per_function.setdefault(key, {}).setdefault(path, {})["peak"] = peak

    largest = next((i["path"] for i in reversed(instances) if i["path"] in profiled_total), None)
    out = []
    for key, by_path in per_function.items():
        file, _, qualname = key.partition(":")
        members = [i for i in instances if i["path"] in by_path]
        calls = {p: v.get("calls") for p, v in by_path.items()}
        cum = {p: v.get("cum") for p, v in by_path.items()}
        per_call = {p: (v["cum"] / v["calls"]) if v.get("calls") and v.get("cum") is not None
                    else None for p, v in by_path.items()}
        peak = {p: v.get("peak") for p, v in by_path.items()}
        line = next((v.get("line") for v in by_path.values() if v.get("line")), None)
        share = None
        if largest and largest in by_path and profiled_total.get(largest):
            share = (by_path[largest].get("cum") or 0) / profiled_total[largest]
        out.append({
            "key": key, "file": file, "qualname": qualname, "line": line,
            "helper": "<" in qualname,
            "share": share,
            "per_instance": {i["name"]: by_path[i["path"]] for i in members},
            "calls": _growth_block(members, calls),
            "per_call": _growth_block(members, per_call),
            "total": _growth_block(members, cum),
            "memory": _growth_block(members, peak),
        })
    out.sort(key=lambda f: (-(f["share"] or 0), f["key"]))
    return out
