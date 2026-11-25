from dataclasses import replace
import unittest

from instancelab.analysis import AnalysisError, AnalysisFeature, FeatureTable
from instancelab.performance import AlgorithmResult, analyze_algorithm_performance


class PerformanceAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.table = FeatureTable(
            sources=("a", "b", "c", "d"),
            feature_names=("size", "demand"),
            values=((1.0, 0.1), (2.0, 0.4), (4.0, 0.2), (8.0, 0.9)),
        )
        self.features = (
            AnalysisFeature("size", "log1p", "test"),
            AnalysisFeature("demand", "identity", "test"),
        )
        self.results = tuple(
            AlgorithmResult(name, algorithm, score, score, 1.0)
            for name, left, right in (
                ("A", 0.2, 0.7),
                ("B", 0.4, 0.6),
                ("C", 0.5, 0.8),
                ("D", 0.9, 0.3),
            )
            for algorithm, score in (("greedy", left), ("dp", right))
        )

    def test_builds_complete_score_matrix_and_correlations(self):
        analysis = analyze_algorithm_performance(
            self.table,
            ("A", "B", "C", "D"),
            self.results,
            self.features,
        )

        self.assertEqual(analysis.algorithms, ("dp", "greedy"))
        self.assertEqual(len(analysis.score_rows()), 4)
        self.assertEqual(len(analysis.summaries), 2)
        self.assertEqual(len(analysis.correlations), 4)
        self.assertEqual(sum(summary.best_count for summary in analysis.summaries), 4)

    def test_summarizes_optional_execution_times(self):
        timed = tuple(
            replace(result, execution_time_seconds=seconds)
            for result, seconds in zip(
                self.results,
                (1.0, 10.0, 2.0, 20.0, 4.0, 40.0, None, 80.0),
                strict=True,
            )
        )

        analysis = analyze_algorithm_performance(
            self.table, ("A", "B", "C", "D"), timed, self.features
        )
        summaries = {summary.algorithm: summary for summary in analysis.summaries}

        self.assertTrue(analysis.execution_times_available)
        self.assertEqual(summaries["dp"].timed_count, 4)
        self.assertAlmostEqual(summaries["dp"].median_seconds, 30.0)
        self.assertEqual(summaries["greedy"].timed_count, 3)
        self.assertAlmostEqual(summaries["greedy"].maximum_seconds, 4.0)
        self.assertEqual(analysis.time_rows()[3]["greedy"], None)
        size_time = {
            row.algorithm: row
            for row in analysis.time_correlations
            if row.feature == "size"
        }
        # dp time grows tenfold per doubling of size: strong positive association.
        self.assertGreater(size_time["dp"].pearson_r, 0.95)
        self.assertEqual(size_time["greedy"].timed_instances, 3)

    def test_reports_no_times_when_none_are_attached(self):
        analysis = analyze_algorithm_performance(
            self.table, ("A", "B", "C", "D"), self.results, self.features
        )

        self.assertFalse(analysis.execution_times_available)
        self.assertTrue(all(row.pearson_r is None for row in analysis.time_correlations))

    def test_rejects_incomplete_score_matrix(self):
        with self.assertRaisesRegex(AnalysisError, "complete score matrix"):
            analyze_algorithm_performance(
                self.table,
                ("A", "B", "C", "D"),
                self.results[:-1],
                self.features,
            )

    def test_rejects_duplicate_result_rows(self):
        with self.assertRaisesRegex(AnalysisError, "duplicate"):
            analyze_algorithm_performance(
                self.table,
                ("A", "B", "C", "D"),
                (*self.results, self.results[0]),
                self.features,
            )


if __name__ == "__main__":
    unittest.main()
