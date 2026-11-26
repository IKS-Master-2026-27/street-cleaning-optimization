import json
import os
from math import isclose
from pathlib import Path
import unittest

from instancelab.adapters import discover_shared_instances, scan_shared_instances
from instancelab.adapters import results_root, scan_shared_algorithm_results
from instancelab.analysis import (
    DEFAULT_PCA_FEATURES,
    FeatureTable,
    build_feature_table,
    preprocess_for_pca,
)
from instancelab.reporting import build_reproducibility_report
from instancelab.performance import analyze_algorithm_performance
from instancelab.clipp import read_instance
from instancelab.diagnostics import build_validation_report
from instancelab.features import FEATURE_NAMES, extract_features
from instancelab.pca import fit_pca_2d, project_feature_table
from instancelab.validation import validate_instance


class SharedRepositoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("CLIPP_SHARED_REPO")
        if not configured:
            raise unittest.SkipTest("Set CLIPP_SHARED_REPO to the read-only shared repository root")
        cls.root = Path(configured)
        if not (cls.root / "data" / "input").is_dir():
            raise unittest.SkipTest(f"Shared instance directory not found under {cls.root}")

    def test_all_committed_class_instances_parse_and_validate(self):
        sources = discover_shared_instances(self.root)
        scan = scan_shared_instances(self.root)

        self.assertEqual(scan.failures, ())
        self.assertEqual(len(scan.loaded), len(sources))

        for source in sources:
            path = source.path
            with self.subTest(instance=str(path.relative_to(self.root))):
                instance = read_instance(path)
                self.assertEqual(validate_instance(instance), ())
                features = extract_features(instance)
                self.assertEqual(tuple(features.as_dict()), FEATURE_NAMES)
                self.assertEqual(features["num_streets"], float(instance.num_streets))

    def test_known_repository_dimensions(self):
        instance_a = read_instance(
            self.root / "data/input/syntetic_generated/instance_A.txt"
        )
        presheva = read_instance(
            self.root / "data/input/real_instances/Presheva/instance.txt"
        )
        sydney = read_instance(
            self.root / "data/input/real_instances/Sydney/instance.txt"
        )

        self.assertEqual(
            (instance_a.num_junctions, instance_a.num_streets, instance_a.num_vehicles),
            (20, 45, 4),
        )
        self.assertEqual(
            (presheva.num_junctions, presheva.num_streets, presheva.num_vehicles),
            (744, 838, 6),
        )
        self.assertEqual(
            (sydney.num_junctions, sydney.num_streets, sydney.num_vehicles),
            (255428, 316886, 697),
        )

    def test_features_are_extracted_for_small_and_largest_instances(self):
        for path in (
            self.root / "data/input/syntetic_generated/instance_A.txt",
            self.root / "data/input/real_instances/Sydney/instance.txt",
        ):
            with self.subTest(instance=str(path.relative_to(self.root))):
                instance = read_instance(path)
                features = extract_features(instance)
                self.assertEqual(tuple(features.as_dict()), FEATURE_NAMES)
                self.assertEqual(features["num_streets"], float(len(instance.streets)))
                self.assertGreater(features["directed_arc_to_junction_ratio"], 0.0)

    def test_realistic_instances_are_the_default_set(self):
        sources = discover_shared_instances(self.root)
        if not (self.root / "data/input/realistic_instances").is_dir():
            self.skipTest("No realistic_instances in this checkout")
        self.assertTrue(sources)
        self.assertEqual({source.group for source in sources}, {"realistic"})

    def test_real_analysis_matrix_is_standardized(self):
        self._check_analysis("legacy")

    def test_realistic_analysis_matrix_is_standardized(self):
        if not (self.root / "data/input/realistic_instances").is_dir():
            self.skipTest("No realistic_instances in this checkout")
        self._check_analysis("realistic")

    def _check_analysis(self, dataset):
        sources = discover_shared_instances(self.root, dataset)
        paths = [source.path for source in sources]
        scan = scan_shared_instances(self.root, dataset)

        table = build_feature_table(read_instance(path) for path in paths)
        prepared = preprocess_for_pca(table)

        self.assertEqual(len(table.values), len(paths))
        self.assertEqual(len(table.feature_names), len(FEATURE_NAMES))
        self.assertEqual(len(prepared.feature_names), len(DEFAULT_PCA_FEATURES))
        for column in range(len(prepared.feature_names)):
            values = [row[column] for row in prepared.standardized_values]
            self.assertTrue(isclose(sum(values) / len(values), 0.0, abs_tol=1e-12))
            variance = sum(value**2 for value in values) / len(values)
            self.assertTrue(isclose(variance, 1.0, abs_tol=1e-12))

        projection = fit_pca_2d(prepared)
        self.assertEqual(len(projection.coordinates), len(paths))
        self.assertGreater(projection.explained_variance_ratio[0], 0.0)
        self.assertGreater(projection.explained_variance_ratio[1], 0.0)
        self.assertLessEqual(projection.total_explained_variance_ratio, 1.0 + 1e-12)

        repeated = project_feature_table(table, projection)
        for expected, actual in zip(projection.coordinates, repeated, strict=True):
            self.assertTrue(isclose(expected[0], actual[0], abs_tol=1e-12))
            self.assertTrue(isclose(expected[1], actual[1], abs_tol=1e-12))

        report = build_validation_report(table)
        self.assertEqual(len(report.extremeness), len(paths))
        self.assertEqual(len(report.stability_folds), len(paths))
        self.assertGreaterEqual(report.minimum_subspace_similarity, 0.0)
        self.assertLessEqual(report.mean_subspace_similarity, 1.0)

        result_scan = scan_shared_algorithm_results(self.root, scan.loaded)
        # Expectations are derived from the files present in this checkout, so
        # newly published result folders do not break the test.
        output_root = results_root(self.root, dataset)
        expected_discovered = tuple(sorted(
            directory.name
            for directory in output_root.iterdir()
            if directory.is_dir() and any(directory.glob("*_solution.txt"))
        )) if output_root.is_dir() else ()
        self.assertEqual(result_scan.discovered_algorithms, expected_discovered)
        failed_algorithms = {failure.algorithm for failure in result_scan.failures}
        self.assertEqual(
            set(result_scan.complete_algorithms),
            set(expected_discovered) - failed_algorithms,
        )
        self.assertEqual(
            len(result_scan.results),
            len(result_scan.complete_algorithms) * len(result_scan.benchmarked_instances),
        )
        self.assertEqual(
            len(result_scan.benchmarked_instances) + len(result_scan.unbenchmarked_instances),
            len(paths),
        )
        if len(result_scan.complete_algorithms) < 2:
            self.skipTest("Fewer than two complete published result sets")
        benchmarked_rows = [
            index for index, source in enumerate(sources)
            if source.name in set(result_scan.benchmarked_instances)
        ]
        benchmarked_table = FeatureTable(
            tuple(table.sources[i] for i in benchmarked_rows),
            table.feature_names,
            tuple(table.values[i] for i in benchmarked_rows),
        )
        performance = analyze_algorithm_performance(
            benchmarked_table,
            tuple(sources[i].name for i in benchmarked_rows),
            result_scan.results,
        )
        self.assertEqual(performance.algorithms, result_scan.complete_algorithms)
        self.assertGreaterEqual(
            sum(summary.best_count for summary in performance.summaries),
            len(benchmarked_rows),
        )
        for summary in performance.summaries:
            self.assertGreaterEqual(summary.minimum_score, 0.0)
            self.assertLessEqual(summary.maximum_score, 1.0)
            self.assertLessEqual(summary.minimum_score, summary.mean_score)
            self.assertLessEqual(summary.mean_score, summary.maximum_score)

        export = build_reproducibility_report(
            [source.name for source in sources],
            [source.group for source in sources],
            table,
            projection,
            report,
            performance=performance,
        )
        serialized = json.dumps(export)
        self.assertEqual(export["scope"]["reference_instance_count"], len(paths))
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(
            export["performance"]["algorithms"],
            list(result_scan.complete_algorithms),
        )


if __name__ == "__main__":
    unittest.main()
