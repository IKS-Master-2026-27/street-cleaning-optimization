"""Tests for the greedy look-ahead solver (clipp/greedy_lookahead.py)."""

from pathlib import Path
import unittest

from clipp import greedy_lookahead
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.solver import solve as greedy_solve
from clipp.validator import validate_solution

ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "data/input/syntetic_generated"


class GreedyLookaheadTests(unittest.TestCase):
    def test_valid_and_complete_on_synthetic_instances(self):
        for name in ("A", "B", "C"):
            instance = parse_instance(INSTANCES / f"instance_{name}.txt")
            solution = greedy_lookahead.solve(instance)
            self.assertEqual(validate_solution(instance, solution), [], name)

    def test_beats_plain_greedy(self):
        instance = parse_instance(INSTANCES / "instance_B.txt")
        plain = calculate_score(instance, greedy_solve(instance)).score
        ahead = calculate_score(instance, greedy_lookahead.solve(instance)).score
        self.assertGreater(ahead, plain)

    def test_deterministic(self):
        instance = parse_instance(INSTANCES / "instance_A.txt")
        first = greedy_lookahead.solve(instance)
        second = greedy_lookahead.solve(instance)
        self.assertEqual([r.junctions for r in first.routes],
                         [r.junctions for r in second.routes])

    def test_explicit_width_and_depth(self):
        instance = parse_instance(INSTANCES / "instance_C.txt")
        solution = greedy_lookahead.solve(instance, width=3, depth=2)
        self.assertEqual(validate_solution(instance, solution), [])


if __name__ == "__main__":
    unittest.main()
