from math import isclose
import unittest

from instancelab.analysis import (
    AnalysisError,
    AnalysisFeature,
    FeatureTable,
    preprocess_for_pca,
)
from instancelab.pca import fit_pca_2d, project_feature_table


class PCATests(unittest.TestCase):
    def setUp(self):
        self.table = FeatureTable(
            sources=("a", "b", "c", "d"),
            feature_names=("size", "demand", "flexibility"),
            values=(
                (10.0, 0.1, 0.8),
                (20.0, 0.4, 0.6),
                (40.0, 0.3, 0.2),
                (80.0, 0.9, 0.5),
            ),
        )
        selected = (
            AnalysisFeature("size", "log1p", "test"),
            AnalysisFeature("demand", "identity", "test"),
            AnalysisFeature("flexibility", "identity", "test"),
        )
        self.prepared = preprocess_for_pca(self.table, selected)

    def test_fits_two_dimensional_projection(self):
        result = fit_pca_2d(self.prepared)

        self.assertEqual(len(result.coordinates), 4)
        self.assertTrue(all(len(row) == 2 for row in result.coordinates))
        self.assertEqual(len(result.loading_rows()), 3)
        self.assertGreater(result.explained_variance_ratio[0], 0.0)
        self.assertGreater(result.explained_variance_ratio[1], 0.0)
        self.assertLessEqual(result.total_explained_variance_ratio, 1.0 + 1e-12)

        for component in result.components:
            norm = sum(value**2 for value in component)
            self.assertTrue(isclose(norm, 1.0, abs_tol=1e-12))
        dot = sum(
            left * right
            for left, right in zip(result.components[0], result.components[1])
        )
        self.assertTrue(isclose(dot, 0.0, abs_tol=1e-12))

    def test_projects_reference_rows_reproducibly(self):
        result = fit_pca_2d(self.prepared)

        projected = project_feature_table(self.table, result)

        for expected, actual in zip(result.coordinates, projected, strict=True):
            self.assertTrue(isclose(expected[0], actual[0], abs_tol=1e-12))
            self.assertTrue(isclose(expected[1], actual[1], abs_tol=1e-12))

    def test_projects_new_row_without_refitting(self):
        result = fit_pca_2d(self.prepared)
        new_table = FeatureTable(
            sources=("new",),
            feature_names=self.table.feature_names,
            values=((30.0, 0.6, 0.4),),
        )

        projected = project_feature_table(new_table, result)

        self.assertEqual(len(projected), 1)
        self.assertTrue(all(abs(value) < float("inf") for value in projected[0]))

    def test_rejects_rank_one_input(self):
        table = FeatureTable(
            sources=("a", "b", "c"),
            feature_names=("x", "y"),
            values=((1.0, 2.0), (2.0, 4.0), (3.0, 6.0)),
        )
        selected = (
            AnalysisFeature("x", "identity", "test"),
            AnalysisFeature("y", "identity", "test"),
        )

        with self.assertRaisesRegex(AnalysisError, "rank"):
            fit_pca_2d(preprocess_for_pca(table, selected))


if __name__ == "__main__":
    unittest.main()
