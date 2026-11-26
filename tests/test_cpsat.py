"""Tests for the cold/warm wrapper around the competition CP-SAT model (clipp/milp/cpsat.py)."""

from pathlib import Path
import tempfile
import unittest

try:
    from clipp.milp import cpsat
    from clipp_cpsat.parser import parse_instance as parse_competition
    HAS_ORTOOLS = True
except ImportError:  # ortools not installed
    HAS_ORTOOLS = False

from clipp.milp.seed import read_solution, solution_file_name
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.solver import solve as greedy_solve
from clipp.validator import validate_solution

ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
