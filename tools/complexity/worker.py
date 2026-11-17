"""Measure one algorithm on one instance. Runs in its own process.

    python -m tools.complexity.worker <algorithm> <instance> <mode> [--repeat R]

Modes (kept separate because instrumentation distorts time):
    time     wall-clock time of solve(), no instrumentation; median of R runs
    memory   peak memory allocated by Python while solving (tracemalloc)
    profile  calls, own time and cumulative time of every project function (cProfile)
    fmemory  peak extra memory of one call, per project function (tracemalloc)

The result is printed as one JSON line prefixed with RESULT_MARK, so anything
the solver prints itself does not get in the way.
"""

import argparse
import cProfile
import gc
import json
import pstats
import statistics
import sys
import time
import tracemalloc
import traceback
import types
from pathlib import Path

from . import ROOT

RESULT_MARK = "@@COMPLEXITY_RESULT@@ "
EXCLUDED_DIRS = ("tools", "tests", "scripts", "visualization", ".venv", "venv")


def project_file(filename: str) -> str | None:
    """Repository-relative path if the file is project code we measure."""
    try:
        relative = Path(filename).resolve().relative_to(ROOT)
    except (ValueError, OSError):
        return None
    if relative.parts and relative.parts[0] in EXCLUDED_DIRS:
        return None
    if relative.suffix != ".py":
        return None
    return relative.as_posix()


def _qualnames(modules) -> dict[tuple[str, int], str]:
    """(file, first line) -> qualified name for every function in the modules."""
    names = {}

    def walk(code: types.CodeType, file: str):
        names[(file, code.co_firstlineno)] = getattr(code, "co_qualname", code.co_name)
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                walk(const, file)

    for module in modules:
        filename = getattr(module, "__file__", None)
        file = project_file(filename) if filename else None
        if not file:
            continue
        try:
            source = Path(filename).read_text(encoding="utf-8")
            walk(compile(source, filename, "exec"), file)
        except (OSError, SyntaxError):
            continue
    return names


def _parse(path: Path):
    from clipp.parser import parse_instance

    return parse_instance(path)


def _evaluate(instance, solution) -> dict:
    from clipp.scoring import calculate_score
    from clipp.validator import validate_solution

    if solution is None:
        return {"status": "invalid", "errors": ["solver returned no solution"]}
    errors = validate_solution(instance, solution)
    if errors:
        return {"status": "invalid", "errors": errors[:5]}
    return {"status": "ok", "score": calculate_score(instance, solution).score}


def _max_rss() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss * 1024)


def measure_time(solve, path: Path, repeat: int) -> dict:
    times = []
    solution = instance = None
    for _ in range(max(1, repeat)):
        instance = _parse(path)
        gc.collect()
        start = time.perf_counter()
        solution = solve(instance)
        times.append(time.perf_counter() - start)
    result = {"seconds": statistics.median(times), "runs": times}
    result.update(_evaluate(instance, solution))
    return result


def measure_memory(solve, path: Path) -> dict:
    instance = _parse(path)
    gc.collect()
    tracemalloc.start()
    try:
        solution = solve(instance)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    result = {"peak_bytes": peak, "max_rss_bytes": _max_rss()}
    result.update(_evaluate(instance, solution))
    return result


def measure_profile(solve, path: Path) -> dict:
    instance = _parse(path)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()
    try:
        solution = solve(instance)
    finally:
        profiler.disable()
    total = time.perf_counter() - start
    names = _qualnames(list(sys.modules.values()))
    functions = {}
    for (filename, line, name), (cc, nc, tt, ct, _) in pstats.Stats(profiler).stats.items():
        file = project_file(filename)
        if not file:
            continue
        qualname = names.get((file, line), name)
        key = f"{file}:{qualname}"
        entry = functions.setdefault(key, {"calls": 0, "primitive_calls": 0,
                                           "own_seconds": 0.0, "cum_seconds": 0.0,
                                           "line": line})
        entry["calls"] += nc
        entry["primitive_calls"] += cc
        entry["own_seconds"] += tt
        entry["cum_seconds"] = max(entry["cum_seconds"], ct)
    return {"profiled_seconds": total, "functions": functions, **_evaluate(instance, solution)}


def measure_function_memory(solve, path: Path) -> dict:
    """Peak extra traced memory of one call, for every project function.

    tracemalloc's peak is reset at every project call; when a call returns,
    its peak is handed to the caller, so nested calls are accounted exactly.
    """
    instance = _parse(path)
    keys: dict[types.CodeType, str | None] = {}
    names = _qualnames(list(sys.modules.values()))
    peaks: dict[str, int] = {}
    stack: list[list] = []  # [key, base bytes, highest peak seen]
    get, reset = tracemalloc.get_traced_memory, tracemalloc.reset_peak

    def key_of(code):
        if code not in keys:
            file = project_file(code.co_filename)
            keys[code] = (f"{file}:{names.get((file, code.co_firstlineno), code.co_name)}"
                          if file else None)
        return keys[code]

    def hook(frame, event, _arg):
        if event == "call":
            key = key_of(frame.f_code)
            if key is None:
                return
            current, peak = get()
            if stack and peak > stack[-1][2]:
                stack[-1][2] = peak
            reset()
            stack.append([key, current, current])
        elif event == "return":
            if not stack or key_of(frame.f_code) is None:
                return
            key, base, highest = stack.pop()
            highest = max(highest, get()[1])
            extra = highest - base
            if extra > peaks.get(key, -1):
                peaks[key] = extra
            if stack and highest > stack[-1][2]:
                stack[-1][2] = highest
            reset()

    monitoring = getattr(sys, "monitoring", None)
    gc.collect()
    tracemalloc.start()
    if monitoring is not None:
        # Python 3.12+: events of non-project code are switched off where they
        # occur (DISABLE), so library and builtin calls cost almost nothing.
        tool, events = monitoring.PROFILER_ID, monitoring.events
        disable = monitoring.DISABLE

        class _Frame:  # the hook only reads f_code
            __slots__ = ("f_code",)

        frame = _Frame()

        def enter(code, _offset):
            if key_of(code) is None:
                return disable
            frame.f_code = code
            hook(frame, "call", None)

        def leave(code, _offset, _value):
            if key_of(code) is None:
                return disable
            frame.f_code = code
            hook(frame, "return", None)

        def unwind(code, _offset, _exc):  # cannot be disabled locally
            if key_of(code) is not None:
                frame.f_code = code
                hook(frame, "return", None)

        monitoring.use_tool_id(tool, "complexity-fmemory")
        for event, callback in ((events.PY_START, enter), (events.PY_RESUME, enter),
                                (events.PY_RETURN, leave), (events.PY_YIELD, leave),
                                (events.PY_UNWIND, unwind)):
            monitoring.register_callback(tool, event, callback)
        monitoring.set_events(tool, events.PY_START | events.PY_RESUME | events.PY_RETURN
                              | events.PY_YIELD | events.PY_UNWIND)
        try:
            solution = solve(instance)
        finally:
            monitoring.set_events(tool, 0)
            monitoring.free_tool_id(tool)
            tracemalloc.stop()
    else:
        sys.setprofile(hook)
        try:
            solution = solve(instance)
        finally:
            sys.setprofile(None)
            tracemalloc.stop()
    return {"function_peak_bytes": peaks, **_evaluate(instance, solution)}


def run(algorithm: str, instance_path: str, mode: str, repeat: int = 3) -> dict:
    from .algorithms import load

    solve = load()[algorithm].function
    path = (ROOT / instance_path) if not Path(instance_path).is_absolute() else Path(instance_path)
    if mode == "time":
        return measure_time(solve, path, repeat)
    if mode == "memory":
        return measure_memory(solve, path)
    if mode == "profile":
        return measure_profile(solve, path)
    if mode == "fmemory":
        return measure_function_memory(solve, path)
    raise ValueError(f"unknown mode {mode!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("algorithm")
    parser.add_argument("instance")
    parser.add_argument("mode", choices=["time", "memory", "profile", "fmemory"])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args(argv)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20_000))
    try:
        result = run(args.algorithm, args.instance, args.mode, args.repeat)
    except Exception as exc:  # report every solver failure as data
        result = {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc(limit=8)}
    sys.stdout.flush()
    print(RESULT_MARK + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
