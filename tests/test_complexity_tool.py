"""Tests for the CLIPP Performance Analyzer (tools/complexity)."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from tools.complexity import fit
from tools.complexity.algorithms import load
from tools.complexity.dashboard import render
from tools.complexity.instances import discover, select
from tools.complexity.report import write_all
from tools.complexity.runner import Runner, dependency_files, estimate, plan

SIZES = [50, 100, 200, 400, 800, 1600]


class FitTest(unittest.TestCase):
    def test_growth_classes(self):
        cases = {
            "O(1)": lambda n: 5.0,
            "O(n)": lambda n: 3 * n,
            "O(n log n)": lambda n: n * math.log2(n),
            "O(n^2)": lambda n: 0.5 * n * n,
        }
        for expected, f in cases.items():
            with self.subTest(expected=expected):
                result = fit.growth(SIZES, [f(n) for n in SIZES])
                self.assertEqual(result.model, expected)

    def test_noise_does_not_inflate_the_class(self):
        noisy = [n * (1.08 if i % 2 else 0.93) for i, n in enumerate(SIZES)]
        self.assertEqual(fit.growth(SIZES, noisy).model, "O(n)")

    def test_too_few_points(self):
        result = fit.growth([10, 20], [1.0, 2.0])
        self.assertIsNone(result.model)
        self.assertEqual(result.reason, "too few points")


class DiscoveryTest(unittest.TestCase):
    def test_reads_main_algorithms(self):
        import main

        found = load()
        for name in main.ALGORITHMS:
            self.assertIn(name, found)
            self.assertEqual(found[name].source, "main.py")

    def test_instances(self):
        available = discover()
        names = {i.name for i in available}
        self.assertTrue({"instance_A", "instance_E"} <= names)
        small = select(available, max_streets=100)
        self.assertTrue(all(i.streets <= 100 for i in small))
        self.assertEqual([i.name for i in select(available, ["instance_b"])], ["instance_B"])
        with self.assertRaises(ValueError):
            select(available, ["no-such-instance"])

    def test_dependency_files_follow_imports(self):
        files = {p.name for p in dependency_files("clipp.recursive")}
        self.assertTrue({"recursive.py", "search.py", "graph.py", "parser.py"} <= files)


class DashboardTest(unittest.TestCase):
    def test_page_contains_styles_scripts_and_data(self):
        page = render({"marker": "data-is-here"})
        self.assertIn("<style>", page)
        self.assertIn("--accent", page)            # from style.css
        self.assertIn("function fmtTime", page)    # from ui/js/core/format.js
        self.assertIn("data-is-here", page)
        self.assertNotIn("<!-- STYLES", page)
        self.assertNotIn("<!-- SCRIPTS", page)

    def test_every_script_is_included(self):
        from tools.complexity.dashboard import SCRIPTS, UI

        on_disk = {p.relative_to(UI / "js").as_posix() for p in (UI / "js").rglob("*.js")}
        self.assertEqual(on_disk, set(SCRIPTS), "list new ui/js files in dashboard.SCRIPTS")

    def test_data_cannot_close_the_script_tag(self):
        page = render({"x": "</script><script>alert(1)</script>"})
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("\\u003c/script\\u003e", page)


class EndToEndTest(unittest.TestCase):
    def test_measure_and_report(self):
        algorithms = {"greedy": load()["greedy"]}
        instances = select(discover(), ["instance_A", "instance_B", "instance_C"])
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            events = []
            jobs = plan(algorithms, instances, ("time", "memory", "profile", "fmemory"), folder=out).jobs
            self.assertEqual(len(jobs), 12)
            records = Runner(repeat=1, timeout=120, folder=out, on_event=events.append).run(jobs)
            self.assertEqual({r["status"] for r in records}, {"ok"})
            self.assertEqual(events[-1]["type"], "finished")
            # unchanged code: everything is reused
            self.assertEqual(len(plan(algorithms, instances, ("time",), folder=out).jobs), 0)
            # the Run panel's estimate: known jobs are timed, unseen ones extrapolated
            again = plan(algorithms, instances, ("time",), fresh=True, folder=out).jobs
            guess = estimate(again, timeout=120, folder=out)
            self.assertEqual(guess["unknown"], 0)
            self.assertGreater(guess["seconds"], 0)
            bigger = select(discover(), ["instance_D"])
            unseen = plan(algorithms, bigger, ("time",), folder=out).jobs
            self.assertEqual(estimate(unseen, timeout=120, folder=out)["unknown"], 0)
            self.assertEqual(estimate(unseen, timeout=120, folder=Path(folder) / "empty")["unknown"], 1)

            data = write_all(algorithms, out)
            for name in ("results.json", "report.md", "runs.csv", "functions.csv", "dashboard.html"):
                self.assertTrue((out / name).exists(), name)
            greedy = data["algorithms"][0]
            self.assertEqual(len(greedy["runs"]), 3)
            self.assertIsNotNone(greedy["time"]["all"]["fit"]["model"])
            keys = {f["key"] for f in data["functions"]["greedy"]}
            self.assertIn("clipp/graph.py:shortest_path", keys)
            self.assertEqual(json.loads((out / "results.json").read_text())["schema"], data["schema"])


class ReviewRegressionTest(unittest.TestCase):
    def test_changed_input_is_measured_again(self):
        from dataclasses import replace

        from tools.complexity.runner import _append

        algorithms = {"greedy": load()["greedy"]}
        source = select(discover(), ["instance_A"])[0]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            copy = out / "instance.txt"
            copy.write_bytes((Path(__file__).resolve().parents[1] / source.path).read_bytes())
            instance = replace(source, path=str(copy))
            job = plan(algorithms, [instance], ("time",), folder=out).jobs[0]
            _append({"schema": 2, "algorithm": "greedy", "instance": instance.to_dict(),
                     "mode": "time", "fingerprint": job.fingerprint,
                     "input_hash": job.input_hash, "status": "ok"}, out)
            self.assertEqual(len(plan(algorithms, [instance], ("time",), folder=out).jobs), 0)
            copy.write_text(copy.read_text() + "\n")
            self.assertEqual(len(plan(algorithms, [instance], ("time",), folder=out).jobs), 1)

    def test_only_one_run_starts_at_a_time(self):
        import threading
        import time
        from unittest import mock

        from tools.complexity.runner import Plan
        from tools.complexity.server import State

        state = State(Path(tempfile.mkdtemp()))
        slow_plan = lambda request: (time.sleep(0.2), (Plan(), []))[1]
        results = []
        with mock.patch.object(state, "_plan", side_effect=slow_plan), \
                mock.patch.object(state, "_work"):
            threads = [threading.Thread(target=lambda: results.append(state.start({})))
                       for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(sorted("error" in r for r in results), [False, True])

    def test_refused_run_releases_the_claim(self):
        from tools.complexity.server import State

        state = State(Path(tempfile.mkdtemp()))
        self.assertIn("error", state.start({"algorithms": ["no-such-algorithm"]}))
        self.assertFalse(state.running)

    def test_old_profile_is_marked_outdated(self):
        from tools.complexity.analysis import build
        from tools.complexity.instances import content_hash
        from tools.complexity.runner import fingerprint

        algorithms = {"greedy": load()["greedy"]}
        instance = select(discover(), ["instance_A"])[0]
        current = fingerprint(algorithms["greedy"].function.__module__)
        base = {"schema": 2, "algorithm": "greedy", "instance": instance.to_dict(),
                "input_hash": content_hash(instance.path), "status": "ok"}
        records = [{**base, "mode": "profile", "fingerprint": "old-code", "profiled_seconds": 1.0,
                    "functions": {"clipp/graph.py:shortest_path": {
                        "calls": 1, "primitive_calls": 1, "own_seconds": 0.1, "cum_seconds": 0.2}}},
                   {**base, "mode": "time", "fingerprint": current, "seconds": 0.1, "runs": [0.1]}]
        greedy = build(records, algorithms)["algorithms"][0]
        self.assertTrue(greedy["stale"])
        self.assertEqual(greedy["stale_modes"], ["profile"])
        # same code but a changed instance file is outdated too
        records[0]["fingerprint"], records[0]["input_hash"] = current, "other-input"
        self.assertEqual(build(records, algorithms)["algorithms"][0]["stale_modes"], ["profile"])

    def test_open_with_relative_out_folder(self):
        import os
        from unittest import mock

        from tools.complexity.__main__ import main

        here = os.getcwd()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch("webbrowser.open") as browser:
            try:
                os.chdir(folder)
                self.assertEqual(main(["report", "--out", "demo-results", "--open"]), 0)
            finally:
                os.chdir(here)
            url = browser.call_args.args[0]
            self.assertTrue(url.startswith("file://") and url.endswith("demo-results/dashboard.html"))

    def test_fingerprint_covers_how_results_are_measured(self):
        from tools.complexity.runner import measurement_files

        names = {p.relative_to(Path(__file__).resolve().parents[1]).as_posix()
                 for p in measurement_files()}
        self.assertTrue({"tools/complexity/worker.py", "clipp/validator.py",
                         "clipp/scoring.py", "clipp/parser.py"} <= names)
        self.assertNotIn("main.py", names)  # one algorithm's change must not invalidate others
        # every algorithm's fingerprint includes them
        files = set(dependency_files("clipp.recursive")) | set(measurement_files())
        self.assertTrue(set(measurement_files()) <= files)

    def test_worker_change_invalidates_the_cache(self):
        from unittest import mock

        from tools.complexity import runner

        before = runner.fingerprint("clipp.recursive")
        worker = Path(runner.__file__).with_name("worker.py").resolve()
        original = Path.read_bytes
        patched = lambda self: original(self) + (b"# changed" if self.resolve() == worker else b"")
        with mock.patch.object(Path, "read_bytes", patched):
            self.assertNotEqual(runner.fingerprint("clipp.recursive"), before)

    def test_profile_modes_validate_the_solution(self):
        from tools.complexity import worker

        path = Path(__file__).resolve().parents[1] / select(discover(), ["instance_A"])[0].path
        for measure in (worker.measure_profile, worker.measure_function_memory):
            with self.subTest(measure=measure.__name__):
                self.assertEqual(measure(lambda instance: None, path)["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
