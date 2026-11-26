"""Tests for the cold/warm wrapper around the competition CP-SAT model (src/milp/cpsat.py)."""

from pathlib import Path
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1]     # tools/milp
ROOT = TOOL.parents[1]                         # repository root
for _path in (ROOT, TOOL / "src", TOOL):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from milp import cpsat
    from clipp_cpsat.parser import parse_instance as parse_competition
    HAS_ORTOOLS = True
except ImportError:  # ortools not installed
    HAS_ORTOOLS = False

from milp.seed import read_solution, solution_file_name
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.solver import solve as greedy_solve
from clipp.validator import validate_solution

INSTANCE_A = ROOT / "data/input/syntetic_generated/instance_A.txt"

# depot 0; mandatory 0-1 (R10), optional 1-2 (R20), one-way connector 2->0,
# optional 1-3 (R30) only an L vehicle may clean.
TINY = """4 4 100 2 0 0.5
0 1 2 10 100 M 10
1 2 2 10 100 O 20
2 0 1 10 0 C 0
1 3 2 10 100 O 30
S M
"""


@unittest.skipUnless(HAS_ORTOOLS, "ortools not installed")
class CpSatTests(unittest.TestCase):
    def test_variable_count_matches_built_model(self):
        instance = parse_competition(str(INSTANCE_A))
        self.assertEqual(cpsat.count_variables(instance), cpsat.build(instance).num_vars)

    def test_cold_tiny_is_optimal_and_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "instance.txt"
            path.write_text(TINY, encoding="utf-8")
            ours, theirs = parse_instance(path), parse_competition(str(path))
        built = cpsat.build(theirs)
        record = cpsat.solve(built, time_limit=30, workers=1)
        self.assertTrue(record.proven_optimal)
        solution = cpsat.to_solution(built, record.best)
        self.assertEqual(validate_solution(ours, solution), [])
        self.assertAlmostEqual(calculate_score(ours, solution).score,
                               built.to_score(record.best_objective), places=6)

    def test_dp_seed_is_a_feasible_hint_and_warm_never_worse(self):
        ours, theirs = parse_instance(INSTANCE_A), parse_competition(str(INSTANCE_A))
        seed = read_solution(ours, ROOT / "data/output/dp_simple" / solution_file_name(INSTANCE_A))
        seed_score = calculate_score(ours, seed).score
        built = cpsat.build(theirs)
        values = cpsat.seed_values(built, seed)
        feasible, _, objective = cpsat.check_hint(built, values, workers=1, time_limit=30)
        self.assertTrue(feasible)
        self.assertAlmostEqual(built.to_score(objective), seed_score, places=6)
        record = cpsat.solve(built, time_limit=5, workers=1, seed=values,
                             seed_objective=objective)
        best = record.best or values
        solution = cpsat.to_solution(built, best)
        self.assertEqual(validate_solution(ours, solution), [])
        self.assertGreaterEqual(calculate_score(ours, solution).score, seed_score - 1e-9)

    def test_disconnected_values_are_detected(self):
        ours, theirs = parse_instance(INSTANCE_A), parse_competition(str(INSTANCE_A))
        built = cpsat.build(theirs)
        greedy = cpsat.seed_values(built, greedy_solve(ours))
        self.assertTrue(cpsat.routes_connected(built, greedy.f))
        far = next(a for a, (u, v, _) in enumerate(built.arcs)
                   if theirs["S"] not in (u, v))
        reverse = next((a for a, (u, v, _) in enumerate(built.arcs)
                        if (u, v) == built.arcs[far][1::-1]), None)
        if reverse is None:
            self.skipTest("no two-way street away from the depot")
        only_cycle = {(far, 0): 1, (reverse, 0): 1}
        self.assertFalse(cpsat.routes_connected(built, only_cycle))


    def test_warm_result_is_never_below_the_seed(self):
        seed, found = cpsat.Values({(0, 0): 1}, {}), cpsat.Values({(1, 0): 1}, {})
        worse = cpsat.SolveRecord(best=found, best_objective=5.0)
        better = cpsat.SolveRecord(best=found, best_objective=20.0)
        nothing = cpsat.SolveRecord()
        self.assertEqual(cpsat.final_values(worse, seed, 10.0), (seed, 10.0, False))
        self.assertEqual(cpsat.final_values(better, seed, 10.0), (found, 20.0, True))
        self.assertEqual(cpsat.final_values(nothing, seed, 10.0), (seed, 10.0, False))
        self.assertEqual(cpsat.final_values(nothing, None, None), (None, None, False))
        self.assertEqual(cpsat.final_values(worse, None, None), (found, 5.0, True))


class RunnerTests(unittest.TestCase):
    """run.py and viewer.py (no solving)."""

    @classmethod
    def setUpClass(cls):
        import run
        import viewer
        cls.runner, cls.viewer = run, viewer

    def args(self, instances=None, cold=None):
        import argparse
        return argparse.Namespace(instances=instances, cold_instances=cold,
                                  variants=["cold", "warm"])

    def test_instance_paths_are_normalised(self):
        a = "data/input/syntetic_generated/instance_A.txt"
        runs = self.runner.planned_runs(self.args(["./" + a], ["data/../" + a]))
        self.assertEqual([v for _, v in runs], ["cold", "warm"])
        self.assertEqual(self.runner.planned_runs(self.args())[0][1], "cold")
        self.assertEqual(len(self.runner.planned_runs(self.args())), 6 + 15)

    def test_existing_results_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            args = self.args(["data/input/syntetic_generated/instance_A.txt"])
            self.assertEqual(self.runner.finished_runs(args, out), [])
            (out / "jobs/instance_A_warm").mkdir(parents=True)
            (out / "jobs/instance_A_warm/result.json").write_text("{}")
            self.assertEqual(self.runner.finished_runs(args, out), ["instance_A_warm"])

    def test_viewer_builds_from_the_committed_results(self):
        results = TOOL / "results"
        if not (results / "results.csv").exists():
            self.skipTest("no results")
        with tempfile.TemporaryDirectory() as folder:
            page = self.viewer.build(results, Path(folder) / "viewer.html")
            html = page.read_text(encoding="utf-8")
        self.assertNotIn("__DATA__", html)
        data = self.viewer.load(results)
        self.assertEqual(len(data["rows"]), len(list(csv_rows(results))))


def csv_rows(results):
    import csv
    with (results / "results.csv").open(encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


if __name__ == "__main__":
    unittest.main()
