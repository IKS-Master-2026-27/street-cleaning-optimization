from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from instancelab.performance import AlgorithmResult
from instancelab.timing import (
    TimingRecord,
    attach_execution_times,
    plan_timing,
    read_timing_csv,
    run_timing,
    stale_timings,
    write_timing_csv,
)

from tests.test_clipp_reader import REPOSITORY_LAYOUT
from tests.test_shared_results import VALID_SOLUTION


FAKE_MAIN = '''from clipp.solver import solve, broken

ALGORITHMS = {"greedy": solve, "dp-simple": solve, "recursive": broken}
'''
FAKE_SOLVER = f'''SOLUTION = {VALID_SOLUTION!r}


def solve(instance):
    return SOLUTION


def broken(instance):
    raise AssertionError("unpublished algorithms must never be executed")
'''
FAKE_PARSER = '''def parse_instance(path):
    return path
'''
FAKE_OUTPUT = '''from pathlib import Path


def write_solution(solution, path):
    Path(path).write_text(solution, encoding="utf-8")
'''


def build_fake_repository(root: Path, published: dict[str, str]) -> None:
    (root / "clipp").mkdir()
    (root / "clipp/__init__.py").write_text("", encoding="utf-8")
    (root / "clipp/solver.py").write_text(FAKE_SOLVER, encoding="utf-8")
    (root / "clipp/parser.py").write_text(FAKE_PARSER, encoding="utf-8")
    (root / "clipp/output.py").write_text(FAKE_OUTPUT, encoding="utf-8")
    (root / "main.py").write_text(FAKE_MAIN, encoding="utf-8")
    instance_dir = root / "data/input/syntetic_generated"
    instance_dir.mkdir(parents=True)
    (instance_dir / "instance_A.txt").write_text(REPOSITORY_LAYOUT, encoding="utf-8")
    for folder, text in published.items():
        directory = root / "data/output" / folder
        directory.mkdir(parents=True)
        (directory / "instance_A_solution.txt").write_text(text, encoding="utf-8")


class TimingTests(unittest.TestCase):
    def test_plans_only_published_pairs_with_registered_algorithms(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            build_fake_repository(
                root,
                {"greedy": VALID_SOLUTION, "dp_simple_8h": VALID_SOLUTION},
            )
            plan = plan_timing(root, ("greedy", "dp-simple", "recursive"))

        self.assertEqual([job[2] for job in plan.jobs], ["greedy"])
        self.assertEqual([folder for folder, _ in plan.not_timeable], ["dp_simple_8h"])

    def test_times_published_pair_and_checks_reproduced_score(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder) / "shared"
            root.mkdir()
            build_fake_repository(root, {"greedy": VALID_SOLUTION})
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            output = Path(folder) / "timing"

            records = run_timing(root, output, timeout=120, log=lambda _: None)
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            reread = read_timing_csv(output / "results.csv")

        self.assertEqual(before, after, "the shared repository must stay unchanged")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual((record.instance, record.algorithm), ("instance_A", "greedy"))
        self.assertEqual(record.status, "ok", record.reason)
        self.assertTrue(record.score_matches)
        self.assertGreaterEqual(record.seconds, 0.0)
        self.assertAlmostEqual(record.published_score, 2 / 3)
        self.assertEqual(reread, records)

    def test_attaches_time_only_when_published_score_is_reproduced(self):
        results = (
            AlgorithmResult("A", "greedy", 0.5, 0.5, 0.5),
            AlgorithmResult("B", "greedy", 0.5, 0.5, 0.5),
            AlgorithmResult("C", "greedy", 0.5, 0.5, 0.5),
        )
        timings = (
            TimingRecord("A", "real", "greedy", "ok", 1.5, 0.5, 0.5, True),
            TimingRecord("B", "real", "greedy", "ok", 2.0, 0.5, 0.7, False),
            TimingRecord("C", "real", "greedy", "timeout", reason="exceeded"),
        )

        attached = attach_execution_times(results, timings)

        self.assertEqual(
            [result.execution_time_seconds for result in attached],
            [1.5, None, None],
        )

    def test_drops_time_when_published_solution_changed_after_timing(self):
        republished = (AlgorithmResult("A", "greedy", 0.9, 0.9, 0.9),)
        timings = (TimingRecord("A", "real", "greedy", "ok", 1.5, 0.5, 0.5, True),)

        attached = attach_execution_times(republished, timings)

        self.assertIsNone(attached[0].execution_time_seconds)
        self.assertEqual(stale_timings(republished, timings), timings)

    def test_resume_retimes_only_changed_published_solutions(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder) / "shared"
            root.mkdir()
            build_fake_repository(root, {"greedy": VALID_SOLUTION})
            output = Path(folder) / "timing"
            first = run_timing(root, output, timeout=120, log=lambda _: None)
            unchanged = run_timing(root, output, timeout=120, resume=True, log=lambda _: None)
            # Republish a different (still valid) solution: score changes.
            write_timing_csv(
                output / "results.csv",
                (TimingRecord("instance_A", "synthetic", "greedy", "ok", 99.0, 0.1, 0.1, True),),
            )
            retimed = run_timing(root, output, timeout=120, resume=True, log=lambda _: None)

        self.assertEqual(unchanged, first)
        self.assertNotEqual(retimed[0].seconds, 99.0)
        self.assertAlmostEqual(retimed[0].published_score, 2 / 3)

    def test_csv_round_trip_preserves_values(self):
        records = (
            TimingRecord("A", "real", "greedy", "ok", 0.25, 0.5, 0.5, True),
            TimingRecord("B", "synthetic", "dp_simple", "failed", reason="Error: x"),
        )
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "results.csv"
            write_timing_csv(path, records)
            reread = read_timing_csv(path)

        self.assertEqual(set(reread), set(records))


if __name__ == "__main__":
    unittest.main()
