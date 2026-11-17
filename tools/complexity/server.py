"""Local dashboard server: python -m tools.complexity serve

Serves the dashboard in live mode and a small JSON API on 127.0.0.1 only.
Measurements run in a background thread, one subprocess at a time; the page
polls /api/status and reloads /api/results when new measurements arrive.

    GET  /                 dashboard (live)
    GET  /api/results      the data model (same as results.json)
    GET  /api/options      algorithms, instances and defaults for the run form
    GET  /api/status?since=N   progress and log lines after index N
    POST /api/run          {"algorithms": [...], "instances": [paths], "modes": [...],
                            "repeat": 3, "timeout": 300, "fresh": false}
    POST /api/plan         same body as /api/run: measurements needed and an estimated duration
    POST /api/cancel       stop the current run
"""

import json
import os
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import OUTPUT, ROOT
from .algorithms import load
from .analysis import build
from .dashboard import render
from .instances import DEFAULT_MAX_STREETS, INPUT, discover, size_sets
from .report import write_all
from .runner import MODES, Runner, estimate, load_records, plan


_SKIP_DIRS = {"__pycache__", "node_modules", "venv", "tests", "scripts", "visualization", "data"}


def source_signature() -> tuple:
    """(path, mtime, size) of the project's Python files and instance files."""
    entries = []
    for top, suffix in ((ROOT, ".py"), (INPUT, ".txt")):
        for folder, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if name.endswith(suffix):
                    path = os.path.join(folder, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    entries.append((path, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


class State:
    def __init__(self, folder: Path):
        self.folder = folder
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.running = False
        self.runner: Runner | None = None
        self.progress = {"done": 0, "total": 0, "current": None, "cached": 0}
        self.version = 0
        self._data = None
        self._sources = None

    def log(self, event: dict) -> None:
        with self.lock:
            event = {**event, "at": time.strftime("%H:%M:%S")}
            self.events.append(event)
            kind = event["type"]
            if kind == "start":
                self.progress["current"] = event["label"]
            elif kind in ("done", "skip"):
                self.progress["done"] = event["index"]
                self.progress["current"] = None
            elif kind == "plan":
                self.progress["total"] = event["total"]

    def _check_sources(self) -> None:
        """Rebuild the data when code or instances changed, so "outdated" shows
        without a new run. Uses modification times only: cheap enough per poll."""
        signature = source_signature()
        with self.lock:
            if signature != self._sources:
                if self._sources is not None:
                    self._data = None
                    self.version += 1  # the page reloads /api/results
                self._sources = signature

    def data(self) -> dict:
        self._check_sources()
        with self.lock:
            if self._data is None:
                self._data = build(load_records(self.folder), load())
            return self._data

    def refresh(self) -> None:
        data = write_all(load(), self.folder)
        with self.lock:
            self._data = data
            self.version += 1

    def _plan(self, request: dict):
        """(plan, chosen instances) for a Run request, or {"error": ...}."""
        algorithms = load(reload=True)
        wanted = request.get("algorithms") or list(algorithms)
        unknown = [a for a in wanted if a not in algorithms]
        if unknown:
            return {"error": f"unknown algorithm(s): {', '.join(unknown)}"}
        by_path = {i.path: i for i in discover()}
        paths = request.get("instances") or [i.path for i in by_path.values()
                                             if i.streets <= DEFAULT_MAX_STREETS]
        missing = [p for p in paths if p not in by_path]
        if missing:
            return {"error": f"unknown instance(s): {', '.join(missing)}"}
        modes = [m for m in (request.get("modes") or MODES) if m in MODES]
        chosen = [by_path[p] for p in paths]
        job_plan = plan({a: algorithms[a] for a in wanted}, chosen, modes,
                        fresh=bool(request.get("fresh")), folder=self.folder)
        return job_plan, chosen

    def preview(self, request: dict) -> dict:
        """How many measurements a request needs and roughly how long they take."""
        planned = self._plan(request)
        if isinstance(planned, dict):
            return planned
        job_plan, chosen = planned
        guess = estimate(job_plan.jobs, float(request.get("timeout") or 300), self.folder)
        big = sorted({j.instance.name for j in job_plan.jobs
                      if j.instance.streets > DEFAULT_MAX_STREETS})
        return {"jobs": len(job_plan.jobs), "cached": job_plan.cached, **guess,
                "big_instances": big}

    def start(self, request: dict) -> dict:
        # check and claim in one step, so two concurrent requests cannot both start
        with self.lock:
            if self.running:
                return {"error": "a run is already in progress"}
            self.running = True
        runner = None
        try:
            planned = self._plan(request)
            if isinstance(planned, dict):
                return planned
            job_plan, _ = planned
            runner = Runner(repeat=int(request.get("repeat") or 3),
                            timeout=float(request.get("timeout") or 300), folder=self.folder,
                            on_event=self._on_event)
        finally:
            if runner is None:  # refused or failed: release the claim
                with self.lock:
                    self.running = False
        with self.lock:
            self.runner = runner
            self.events.append({"type": "info", "at": time.strftime("%H:%M:%S"),
                                "message": f"{len(job_plan.jobs)} measurements to run, "
                                           f"{job_plan.cached} reused from earlier runs"})
            self.progress = {"done": 0, "total": len(job_plan.jobs), "current": None,
                             "cached": job_plan.cached}
        threading.Thread(target=self._work, args=(runner, job_plan.jobs), daemon=True).start()
        return {"ok": True, "jobs": len(job_plan.jobs), "cached": job_plan.cached}

    def _on_event(self, event: dict) -> None:
        self.log(event)
        if event["type"] == "done":
            try:
                self.refresh()
            except Exception as exc:  # never kill the run because of the report
                self.log({"type": "info", "message": f"report failed: {exc}"})

    def _work(self, runner: Runner, jobs) -> None:
        try:
            runner.run(jobs)
            self.refresh()
        except Exception as exc:
            self.log({"type": "info", "message": f"run failed: {type(exc).__name__}: {exc}"})
        finally:
            with self.lock:
                self.running = False
                self.runner = None
                self.progress["current"] = None

    def cancel(self) -> dict:
        with self.lock:
            runner = self.runner
        if runner:
            runner.cancel()
            return {"ok": True}
        return {"error": "nothing is running"}

    def status(self, since: int) -> dict:
        self._check_sources()
        with self.lock:
            return {"running": self.running, "progress": dict(self.progress),
                    "version": self.version, "next": len(self.events),
                    "events": self.events[since:]}


def options() -> dict:
    algorithms = load(reload=True)
    data_names = {}
    for name, algorithm in algorithms.items():
        data_names[name] = {"name": name, "source": algorithm.source,
                            "location": algorithm.location}
    return {
        "algorithms": list(data_names.values()),
        "instances": [{**i.to_dict(), "sets": size_sets(i.streets)} for i in discover()],
        "modes": list(MODES),
        "defaults": {"repeat": 3, "timeout": 300},
    }


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CLIPPPerformanceAnalyzer/1"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, status, body: bytes, kind: str):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status=HTTPStatus.OK):
            self._send(status, json.dumps(payload).encode(), "application/json")

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, render(None, live=True).encode(), "text/html; charset=utf-8")
            elif url.path == "/api/results":
                self._json(state.data())
            elif url.path == "/api/options":
                self._json(options())
            elif url.path == "/api/status":
                since = int(parse_qs(url.query).get("since", ["0"])[0] or 0)
                self._json(state.status(since))
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            # the page is served from this origin; refuse cross-site form posts
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                self._json({"error": "cross-origin request refused"}, HTTPStatus.FORBIDDEN)
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return
            path = urlparse(self.path).path
            if path == "/api/run":
                result = state.start(body)
            elif path == "/api/plan":
                result = state.preview(body)
            elif path == "/api/cancel":
                result = state.cancel()
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json(result, HTTPStatus.BAD_REQUEST if "error" in result else HTTPStatus.OK)

    return Handler


def serve(port: int = 8765, open_browser: bool = True, folder: Path = OUTPUT) -> None:
    state = State(folder)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"CLIPP Performance Analyzer running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
        if state.runner:
            state.runner.cancel()
    finally:
        server.server_close()
