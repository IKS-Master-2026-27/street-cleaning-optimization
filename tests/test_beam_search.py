"""Tests for the beam-search solver (clipp/beam_search.py)."""

from pathlib import Path
import tempfile
import unittest

from clipp import beam_search
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.solver import solve as greedy_solve
from clipp.validator import validate_solution

ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "data/input/syntetic_generated"


def _instance(text: str):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "instance.txt"
        path.write_text(text, encoding="utf-8")
        return parse_instance(path)


# depot 0; mandatory 0-1 (R10), optional 1-2 (R20), one-way connector 2->0
TINY = """3 3 {T} 2 0 1.0
0 1 2 10 100 M 10
1 2 2 10 100 O 20
2 0 1 10 0 C 0
S M
"""


class BeamSearchTests(unittest.TestCase):
    def test_valid_and_complete_on_synthetic_instances(self):
        for name in ("A", "B", "C", "D"):
            instance = parse_instance(INSTANCES / f"instance_{name}.txt")
            solution = beam_search.solve(instance)
            self.assertEqual(validate_solution(instance, solution), [], name)

    def test_beats_plain_greedy(self):
        instance = parse_instance(INSTANCES / "instance_B.txt")
        plain = calculate_score(instance, greedy_solve(instance)).score
        beam = calculate_score(instance, beam_search.solve(instance)).score
        self.assertGreater(beam, plain)

    def test_deterministic(self):
        instance = parse_instance(INSTANCES / "instance_B.txt")
        first = beam_search.solve(instance, width=16, candidates=3)
        second = beam_search.solve(instance, width=16, candidates=3)
        self.assertEqual([r.junctions for r in first.routes],
                         [r.junctions for r in second.routes])
        self.assertEqual([r.cleaned_street_ids for r in first.routes],
                         [r.cleaned_street_ids for r in second.routes])

    def test_explicit_parameters(self):
        instance = parse_instance(INSTANCES / "instance_C.txt")
        for width, candidates in ((1, 1), (8, 2), (32, 4)):
            solution = beam_search.solve(instance, width=width,
                                         candidates=candidates, rho_scale=0.5)
            self.assertEqual(validate_solution(instance, solution), [],
                             (width, candidates))

    def test_tiny_instance_cleans_everything(self):
        instance = _instance(TINY.format(T=100))
        solution = beam_search.solve(instance)
        self.assertEqual(validate_solution(instance, solution), [])
        cleaned = {s for r in solution.routes for s in r.cleaned_street_ids}
        self.assertEqual(cleaned, {0, 1})
        # The optional R20 street can only be cleaned by the M vehicle.
        medium_route = next(r for r in solution.routes if r.vehicle_type == "M")
        self.assertIn(1, medium_route.cleaned_street_ids)
        self.assertAlmostEqual(calculate_score(instance, solution).score, 1.0)

    def test_time_limit_too_short_raises(self):
        instance = _instance(TINY.format(T=15))
        with self.assertRaises(beam_search.BeamSearchError):
            beam_search.solve(instance)

    def test_no_capable_vehicle_raises(self):
        instance = _instance(TINY.format(T=100).replace("M 10", "M 30", 1))
        with self.assertRaises(beam_search.BeamSearchError):
            beam_search.solve(instance)


if __name__ == "__main__":
    unittest.main()
