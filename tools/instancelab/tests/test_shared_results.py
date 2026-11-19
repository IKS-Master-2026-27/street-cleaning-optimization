from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from instancelab.adapters.shared_repository import InstanceSource
from instancelab.adapters.shared_results import (
    SolutionResultError,
    scan_shared_algorithm_results,
    score_solution_file,
)
from instancelab.clipp import parse_instance

from tests.test_clipp_reader import REPOSITORY_LAYOUT


VALID_SOLUTION = """2
2
0 1 0
0
0
0

"""


class SharedResultAdapterTests(unittest.TestCase):
    def test_scores_valid_solution(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="instance_A.txt")
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "solution.txt"
            path.write_text(VALID_SOLUTION, encoding="utf-8")
            result = score_solution_file(
                instance,
                path,
                instance_name="instance_A",
                algorithm="test",
            )

        self.assertAlmostEqual(result.coverage, 1 / 3)
        self.assertAlmostEqual(result.efficiency, 1.0)
        self.assertAlmostEqual(result.score, 2 / 3)

    def test_rejects_solution_missing_mandatory_work(self):
        instance = parse_instance(REPOSITORY_LAYOUT)
        invalid = VALID_SOLUTION.replace("0\n0\n0\n\n", "\n0\n0\n\n", 1)
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "solution.txt"
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(SolutionResultError, "mandatory"):
                score_solution_file(
                    instance,
                    path,
                    instance_name="instance_A",
                    algorithm="test",
                )

    def test_scans_algorithm_directories_without_writing(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="instance_A.txt")
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            source = InstanceSource(
                "instance_A",
                "synthetic",
                root / "data/input/syntetic_generated/instance_A.txt",
            )
            for algorithm in ("greedy", "dp_simple"):
                directory = root / "data/output" / algorithm
                directory.mkdir(parents=True)
                (directory / "instance_A_solution.txt").write_text(
                    VALID_SOLUTION,
                    encoding="utf-8",
                )

            scan = scan_shared_algorithm_results(root, ((source, instance),))

        self.assertEqual(len(scan.results), 2)
        self.assertEqual(scan.failures, ())
        self.assertEqual(scan.discovered_algorithms, ("dp_simple", "greedy"))
        self.assertEqual(scan.complete_algorithms, ("dp_simple", "greedy"))

    def test_excludes_incomplete_discovered_algorithm(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="instance_A.txt")
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            sources = tuple(
                (
                    InstanceSource(
                        name,
                        "synthetic",
                        root / f"data/input/syntetic_generated/{name}.txt",
                    ),
                    instance,
                )
                for name in ("instance_A", "instance_B")
            )
            complete = root / "data" / "output" / "complete"
            partial = root / "data" / "output" / "partial"
            complete.mkdir(parents=True)
            partial.mkdir(parents=True)
            for name in ("instance_A", "instance_B"):
                (complete / f"{name}_solution.txt").write_text(
                    VALID_SOLUTION,
                    encoding="utf-8",
                )
            (partial / "instance_A_solution.txt").write_text(
                VALID_SOLUTION,
                encoding="utf-8",
            )

            scan = scan_shared_algorithm_results(root, sources)

        self.assertEqual(scan.discovered_algorithms, ("complete", "partial"))
        self.assertEqual(scan.complete_algorithms, ("complete",))
        self.assertEqual(len(scan.results), 2)
        self.assertEqual(
            [(failure.algorithm, failure.instance_name) for failure in scan.failures],
            [("partial", "instance_B")],
        )


class NewInstanceFlowTests(unittest.TestCase):
    def test_new_instance_without_results_does_not_block_comparison(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="instance_A.txt")
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            sources = tuple(
                InstanceSource(name, "synthetic", root / f"{name}.txt")
                for name in ("instance_A", "instance_B")
            )
            for algorithm in ("greedy", "dp_simple"):
                directory = root / "data/output" / algorithm
                directory.mkdir(parents=True)
                (directory / "instance_A_solution.txt").write_text(
                    VALID_SOLUTION, encoding="utf-8"
                )
            scan = scan_shared_algorithm_results(
                root, tuple((source, instance) for source in sources)
            )

        self.assertEqual(scan.complete_algorithms, ("dp_simple", "greedy"))
        self.assertEqual(scan.benchmarked_instances, ("instance_A",))
        self.assertEqual(scan.unbenchmarked_instances, ("instance_B",))
        self.assertEqual(scan.failures, ())

    def test_algorithm_missing_a_benchmarked_instance_stays_excluded(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="instance_A.txt")
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            sources = tuple(
                InstanceSource(name, "synthetic", root / f"{name}.txt")
                for name in ("instance_A", "instance_B")
            )
            for algorithm, names in (
                ("greedy", ("instance_A", "instance_B")),
                ("recursive", ("instance_A",)),
            ):
                directory = root / "data/output" / algorithm
                directory.mkdir(parents=True)
                for name in names:
                    (directory / f"{name}_solution.txt").write_text(
                        VALID_SOLUTION, encoding="utf-8"
                    )
            scan = scan_shared_algorithm_results(
                root, tuple((source, instance) for source in sources)
            )

        self.assertEqual(scan.complete_algorithms, ("greedy",))
        self.assertEqual(scan.unbenchmarked_instances, ())
        self.assertEqual(
            [(f.instance_name, f.algorithm) for f in scan.failures],
            [("instance_B", "recursive")],
        )


if __name__ == "__main__":
    unittest.main()
