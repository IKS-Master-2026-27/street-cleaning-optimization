"""Smoke tests for the Streamlit dashboard using streamlit.testing.AppTest."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover - dashboard dependencies are optional
    AppTest = None


APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def fixture_instance(n: int, mandatory_every: int, requirement_shift: int,
                     vehicles: str, alpha: float, chord_every: int) -> str:
    """Small valid test-only ring network; not an analysed instance."""

    requirements = (10, 20, 30)
    streets = []
    for node in range(n):
        category = "M" if node % mandatory_every == 0 else ("O" if node % 2 else "C")
        travel = 10 + (node * 7) % 13
        if category == "C":
            length, requirement = 0, 0
        else:
            length = 100 + node * 13
            requirement = requirements[(node + requirement_shift) % 3]
        streets.append(f"{node} {(node + 1) % n} 2 {travel} {length} {category} {requirement}")
    for node in range(0, n, chord_every):
        streets.append(f"{node} {(node + 2) % n} 1 {15 + node % 5} 0 C 0")
    time_limit = 40 * n
    header = f"{n} {len(streets)} {time_limit} {len(vehicles.split())} 0 {alpha}"
    return "\n".join((header, *streets, vehicles)) + "\n"


FIXTURES = (
    fixture_instance(6, 2, 0, "L S", 1.0, 2),
    fixture_instance(9, 3, 1, "L M M", 0.7, 3),
    fixture_instance(12, 5, 2, "L L S S", 0.5, 4),
    fixture_instance(15, 4, 0, "L M", 0.3, 5),
    fixture_instance(20, 6, 1, "L S S M M", 0.9, 7),
)


@unittest.skipIf(AppTest is None, "Streamlit is not installed")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.get("CLIPP_SHARED_REPO")

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("CLIPP_SHARED_REPO", None)
        else:
            os.environ["CLIPP_SHARED_REPO"] = self._previous

    def test_shows_instructions_without_repository(self):
        os.environ["CLIPP_SHARED_REPO"] = ""
        app = AppTest.from_file(APP_PATH, default_timeout=60)
        app.run()

        self.assertFalse(app.exception)
        self.assertTrue(any("CLIPP_SHARED_REPO" in info.value for info in app.info))

    def test_renders_analysis_for_repository_without_results(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            instance_dir = root / "data/input/syntetic_generated"
            instance_dir.mkdir(parents=True)
            for letter, text in zip("ABCDE", FIXTURES):
                (instance_dir / f"instance_{letter}.txt").write_text(
                    text, encoding="utf-8"
                )
            os.environ["CLIPP_SHARED_REPO"] = str(root)

            app = AppTest.from_file(APP_PATH, default_timeout=120)
            app.run()

            self.assertFalse(app.exception, app.exception)
            metrics = {metric.label: metric.value for metric in app.metric}
            self.assertEqual(metrics["Catalog features"], "26")
            self.assertEqual(metrics["Reference set"], "5")
            self.assertTrue(
                any("complete result matrix" in info.value for info in app.info)
            )

    def test_renders_scores_and_times_for_shared_repository(self):
        configured = self._previous
        if not configured or not (Path(configured) / "data/input").is_dir():
            self.skipTest("Set CLIPP_SHARED_REPO to run the dashboard on class data")
        os.environ["CLIPP_SHARED_REPO"] = configured

        app = AppTest.from_file(APP_PATH, default_timeout=900)
        app.run()

        self.assertFalse(app.exception, app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertIn("Highest mean score", metrics)
        self.assertIn("Timed published pairs", metrics)
        self.assertIn("Execution time", [header.value for header in app.subheader])


if __name__ == "__main__":
    unittest.main()
