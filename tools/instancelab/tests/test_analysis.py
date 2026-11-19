from math import isclose, log1p
import unittest

from instancelab.analysis import (
    DEFAULT_PCA_FEATURES,
    AnalysisError,
    AnalysisFeature,
    FeatureTable,
    build_feature_table,
    preprocess_for_pca,
)
from instancelab.clipp import parse_instance
from instancelab.features import FEATURE_NAMES

from tests.test_clipp_reader import REPOSITORY_LAYOUT


class AnalysisTests(unittest.TestCase):
    def test_builds_feature_table_from_instances(self):
        first = parse_instance(REPOSITORY_LAYOUT, source="first.txt")
        second = parse_instance(REPOSITORY_LAYOUT, source="second.txt")

        table = build_feature_table((first, second))

        self.assertEqual(table.sources, ("first.txt", "second.txt"))
        self.assertEqual(table.feature_names, FEATURE_NAMES)
        self.assertEqual(len(table.values), 2)
        self.assertEqual(table.column("num_streets"), (3.0, 3.0))
        self.assertEqual(table.as_rows()[0]["source"], "first.txt")

    def test_log_transforms_and_standardizes_selected_features(self):
        table = FeatureTable(
            sources=("small", "medium", "large"),
            feature_names=("size", "fraction"),
            values=((9.0, 0.2), (99.0, 0.5), (999.0, 0.8)),
        )
        selected = (
            AnalysisFeature("size", "log1p", "test scale feature"),
            AnalysisFeature("fraction", "identity", "test ratio feature"),
        )

        prepared = preprocess_for_pca(table, selected)

        self.assertEqual(
            prepared.transformed_values,
            (
                (log1p(9.0), 0.2),
                (log1p(99.0), 0.5),
                (log1p(999.0), 0.8),
            ),
        )
        for column in range(2):
            values = [row[column] for row in prepared.standardized_values]
            self.assertTrue(isclose(sum(values) / len(values), 0.0, abs_tol=1e-12))
            variance = sum(value**2 for value in values) / len(values)
            self.assertTrue(isclose(variance, 1.0, abs_tol=1e-12))

    def test_rejects_constant_selected_column(self):
        table = FeatureTable(
            sources=("a", "b", "c"),
            feature_names=("constant",),
            values=((1.0,), (1.0,), (1.0,)),
        )

        with self.assertRaisesRegex(AnalysisError, "zero variance"):
            preprocess_for_pca(
                table,
                (AnalysisFeature("constant", "identity", "test"),),
            )

    def test_default_selection_is_unique_and_uses_catalog_features(self):
        names = tuple(feature.name for feature in DEFAULT_PCA_FEATURES)

        self.assertEqual(len(names), 9)
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(set(names).issubset(FEATURE_NAMES))


if __name__ == "__main__":
    unittest.main()
