"""Transparent two-dimensional PCA for preprocessed instance features."""

from dataclasses import dataclass
from math import isfinite

import numpy as np

from .analysis import (
    AnalysisError,
    FeatureTable,
    PreprocessedData,
    apply_fitted_preprocessing,
)


@dataclass(frozen=True, slots=True)
class PCAResult:
    """Fitted 2D projection plus the parameters needed for interpretation."""

    preprocessing: PreprocessedData
    coordinates: tuple[tuple[float, float], ...]
    components: tuple[tuple[float, ...], tuple[float, ...]]
    explained_variance: tuple[float, float]
    explained_variance_ratio: tuple[float, float]

    @property
    def total_explained_variance_ratio(self) -> float:
        return sum(self.explained_variance_ratio)

    def coordinate_rows(self) -> tuple[dict[str, str | float], ...]:
        return tuple(
            {"source": source, "pc1": coordinate[0], "pc2": coordinate[1]}
            for source, coordinate in zip(
                self.preprocessing.sources, self.coordinates, strict=True
            )
        )

    def loading_rows(self) -> tuple[dict[str, str | float], ...]:
        return tuple(
            {
                "feature": feature,
                "pc1_loading": self.components[0][index],
                "pc2_loading": self.components[1][index],
            }
            for index, feature in enumerate(self.preprocessing.feature_names)
        )


def _orient_components(
    components: np.ndarray,
    coordinates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Resolve arbitrary SVD signs for reproducible plots and tests."""

    for index in range(components.shape[0]):
        dominant = int(np.argmax(np.abs(components[index])))
        if components[index, dominant] < 0.0:
            components[index] *= -1.0
            coordinates[:, index] *= -1.0
    return components, coordinates


def fit_pca_2d(preprocessed: PreprocessedData) -> PCAResult:
    """Fit a deterministic 2D PCA using singular value decomposition."""

    matrix = np.asarray(preprocessed.standardized_values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 3:
        raise AnalysisError("At least three preprocessed rows are required for 2D PCA")
    if matrix.shape[1] < 2:
        raise AnalysisError("At least two selected features are required for 2D PCA")
    if not np.isfinite(matrix).all():
        raise AnalysisError("PCA input contains a non-finite value")

    _, singular_values, right_vectors = np.linalg.svd(matrix, full_matrices=False)
    tolerance = np.finfo(float).eps * max(matrix.shape) * singular_values[0]
    if np.count_nonzero(singular_values > tolerance) < 2:
        raise AnalysisError("PCA input must have numerical rank of at least two")

    all_explained_variance = singular_values**2 / (matrix.shape[0] - 1)
    total_variance = float(all_explained_variance.sum())
    if total_variance <= 0.0 or not isfinite(total_variance):
        raise AnalysisError("PCA input has no finite variance")

    components = right_vectors[:2].copy()
    coordinates = matrix @ components.T
    components, coordinates = _orient_components(components, coordinates)

    explained_variance = all_explained_variance[:2]
    explained_ratio = explained_variance / total_variance
    return PCAResult(
        preprocessing=preprocessed,
        coordinates=tuple(
            (float(row[0]), float(row[1])) for row in coordinates
        ),
        components=(
            tuple(float(value) for value in components[0]),
            tuple(float(value) for value in components[1]),
        ),
        explained_variance=(
            float(explained_variance[0]),
            float(explained_variance[1]),
        ),
        explained_variance_ratio=(
            float(explained_ratio[0]),
            float(explained_ratio[1]),
        ),
    )


def project_feature_table(
    table: FeatureTable,
    fitted: PCAResult,
) -> tuple[tuple[float, float], ...]:
    """Project new instances with the fitted preprocessing and PCA axes."""

    standardized = np.asarray(
        apply_fitted_preprocessing(table, fitted.preprocessing),
        dtype=float,
    )
    components = np.asarray(fitted.components, dtype=float)
    coordinates = standardized @ components.T
    return tuple((float(row[0]), float(row[1])) for row in coordinates)
