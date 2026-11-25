from math import isclose
import unittest

from instancelab.analysis import AnalysisError, AnalysisFeature, FeatureTable
from instancelab.diagnostics import build_validation_report


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.table = FeatureTable(
            sources=("a", "b", "c", "d", "e", "f"),
            feature_names=("scale", "duplicate_scale", "shape"),
            values=(
                (1.0, 2.0, 0.1),
                (2.0, 4.0, 0.8),
                (3.0, 6.0, 0.3),
                (4.0, 8.0, 0.9),
                (5.0, 10.0, 0.2),
                (12.0, 24.0, 0.6),
            ),
        )
        self.features = (
            AnalysisFeature("scale", "identity", "test"),
            AnalysisFeature("duplicate_scale", "identity", "test"),
            AnalysisFeature("shape", "identity", "test"),
        )

    def test_reports_redundancy_extremeness_and_stability(self):
        report = build_validation_report(self.table, self.features)

        self.assertEqual(report.feature_names, tuple(f.name for f in self.features))
        self.assertEqual(len(report.correlation_matrix), 3)
        self.assertTrue(
            any(
                {pair.left, pair.right} == {"scale", "duplicate_scale"}
                and isclose(pair.correlation, 1.0, abs_tol=1e-12)
                for pair in report.high_correlations
            )
        )
        self.assertEqual(report.extremeness[0].source, "f")
        self.assertEqual(len(report.stability_folds), len(self.table.values))
        self.assertGreaterEqual(report.minimum_subspace_similarity, 0.0)
        self.assertLessEqual(report.mean_subspace_similarity, 1.0)
        low, high = report.variance_retained_range
        self.assertGreater(low, 0.0)
        self.assertLessEqual(high, 1.0 + 1e-12)

    def test_rejects_too_few_rows(self):
        short = FeatureTable(
            sources=self.table.sources[:3],
            feature_names=self.table.feature_names,
            values=self.table.values[:3],
        )

        with self.assertRaisesRegex(AnalysisError, "At least four"):
            build_validation_report(short, self.features)

    def test_rejects_invalid_correlation_threshold(self):
        with self.assertRaisesRegex(AnalysisError, "threshold"):
            build_validation_report(
                self.table,
                self.features,
                correlation_threshold=1.1,
            )

    def test_rejects_single_feature_diagnostics(self):
        with self.assertRaisesRegex(AnalysisError, "At least two features"):
            build_validation_report(self.table, self.features[:1])


if __name__ == "__main__":
    unittest.main()
