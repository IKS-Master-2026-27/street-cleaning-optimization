import json
import unittest

from instancelab.analysis import AnalysisError, AnalysisFeature, FeatureTable
from instancelab.diagnostics import build_validation_report
from instancelab.pca import fit_pca_2d
from instancelab.performance import AlgorithmResult, analyze_algorithm_performance
from instancelab.analysis import preprocess_for_pca
from instancelab.reporting import (
    build_academic_summary,
    build_reproducibility_report,
)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.table = FeatureTable(
            sources=(
                r"C:\private\a.txt",
                r"C:\private\b.txt",
                r"C:\private\c.txt",
                r"C:\private\d.txt",
                r"C:\private\e.txt",
            ),
            feature_names=("size", "demand", "shape"),
            values=(
                (1.0, 0.1, 0.8),
                (2.0, 0.4, 0.6),
                (4.0, 0.3, 0.2),
                (8.0, 0.9, 0.5),
                (16.0, 0.2, 0.9),
            ),
        )
        self.features = (
            AnalysisFeature("size", "log1p", "test"),
            AnalysisFeature("demand", "identity", "test"),
            AnalysisFeature("shape", "identity", "test"),
        )
        self.pca = fit_pca_2d(preprocess_for_pca(self.table, self.features))
        self.validation = build_validation_report(self.table, self.features)
        performance_results = tuple(
            AlgorithmResult(name, algorithm, score, score, 1.0)
            for name, left, right in (
                ("A", 0.2, 0.7),
                ("B", 0.4, 0.6),
                ("C", 0.5, 0.8),
                ("D", 0.9, 0.3),
                ("E", 0.7, 0.9),
            )
            for algorithm, score in (("greedy", left), ("dp", right))
        )
        self.performance = analyze_algorithm_performance(
            self.table,
            ("A", "B", "C", "D", "E"),
            performance_results,
            self.features,
        )

    def test_builds_complete_report_without_local_paths(self):
        report = build_reproducibility_report(
            ("A", "B", "C", "D", "E"),
            ("synthetic", "synthetic", "real", "real", "real"),
            self.table,
            self.pca,
            self.validation,
            (("Rejected", "synthetic", "invalid header"),),
            performance=self.performance,
        )
        serialized = json.dumps(report)

        self.assertEqual(report["scope"]["reference_instance_count"], 5)
        self.assertFalse(report["scope"]["full_supervised_isa"])
        self.assertEqual(len(report["preprocessing"]), 3)
        self.assertEqual(len(report["pca"]["coordinates"]), 5)
        self.assertEqual(len(report["validation"]["leave_one_out"]), 5)
        self.assertEqual(report["scope"]["excluded_instance_count"], 1)
        self.assertEqual(report["excluded_instances"][0]["name"], "Rejected")
        self.assertEqual(report["performance"]["algorithms"], ["dp", "greedy"])
        self.assertFalse(report["performance"]["algorithm_footprints_inferred"])
        self.assertNotIn("C:\\private", serialized)
        self.assertNotIn("a.txt", serialized)

    def test_rejects_metadata_length_mismatch(self):
        with self.assertRaisesRegex(AnalysisError, "equal lengths"):
            build_reproducibility_report(
                ("A",),
                ("real",),
                self.table,
                self.pca,
                self.validation,
            )

    def test_builds_readable_academic_summary_without_local_paths(self):
        summary = build_academic_summary(
            ("A", "B", "C", "D", "E"),
            ("synthetic", "synthetic", "real", "real", "real"),
            self.table,
            self.pca,
            self.validation,
            (("Rejected", "synthetic", "invalid header"),),
            performance=self.performance,
        )

        self.assertIn("# InstanceLab Academic Analysis Summary", summary)
        self.assertIn("Reference instances: **5**", summary)
        self.assertIn("| dp |", summary)
        self.assertIn("Highest mean score: **dp**", summary)
        self.assertIn("Full supervised Instance Space Analysis: **not claimed**", summary)
        self.assertNotIn("C:\\private", summary)
        self.assertNotIn("a.txt", summary)

    def test_rejects_duplicate_export_names(self):
        with self.assertRaisesRegex(AnalysisError, "unique"):
            build_reproducibility_report(
                ("A", "A", "C", "D", "E"),
                ("real",) * 5,
                self.table,
                self.pca,
                self.validation,
            )


if __name__ == "__main__":
    unittest.main()
