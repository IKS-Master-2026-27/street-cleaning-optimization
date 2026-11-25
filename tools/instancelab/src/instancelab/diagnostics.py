"""Scientific diagnostics for the exploratory PCA instance space."""

from dataclasses import dataclass
from math import sqrt

import numpy as np

from .analysis import (
    DEFAULT_PCA_FEATURES,
    AnalysisError,
    AnalysisFeature,
    FeatureTable,
    preprocess_for_pca,
)
from .pca import fit_pca_2d


DEFAULT_CORRELATION_THRESHOLD = 0.85


@dataclass(frozen=True, slots=True)
class CorrelationPair:
    """Pearson correlation between two selected PCA inputs."""

    left: str
    right: str
    correlation: float


@dataclass(frozen=True, slots=True)
class InstanceExtremeness:
    """Transparent distance summary in the standardized input space."""

    source: str
    rms_z_score: float
    max_abs_z_score: float
    dominant_feature: str
    dominant_z_score: float


@dataclass(frozen=True, slots=True)
class StabilityFold:
    """PCA sensitivity after omitting one reference instance."""

    omitted_source: str
    subspace_similarity: float
    variance_retained: float


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Correlation, extremeness and leave-one-out PCA diagnostics."""

    feature_names: tuple[str, ...]
    correlation_matrix: tuple[tuple[float, ...], ...]
    correlation_threshold: float
    high_correlations: tuple[CorrelationPair, ...]
    extremeness: tuple[InstanceExtremeness, ...]
    stability_folds: tuple[StabilityFold, ...]

    @property
    def maximum_absolute_correlation(self) -> float:
        pairs = [
            abs(self.correlation_matrix[row][column])
            for row in range(len(self.feature_names))
            for column in range(row + 1, len(self.feature_names))
        ]
        return max(pairs, default=0.0)

    @property
    def mean_subspace_similarity(self) -> float:
        return sum(
            fold.subspace_similarity for fold in self.stability_folds
        ) / len(self.stability_folds)

    @property
    def minimum_subspace_similarity(self) -> float:
        return min(fold.subspace_similarity for fold in self.stability_folds)

    @property
    def variance_retained_range(self) -> tuple[float, float]:
        values = [fold.variance_retained for fold in self.stability_folds]
        return min(values), max(values)


def _subset_table(table: FeatureTable, omitted_index: int) -> FeatureTable:
    return FeatureTable(
        sources=tuple(
            source
            for index, source in enumerate(table.sources)
            if index != omitted_index
        ),
        feature_names=table.feature_names,
        values=tuple(
            row for index, row in enumerate(table.values) if index != omitted_index
        ),
    )


def _subspace_similarity(
    reference_components: np.ndarray,
    candidate_components: np.ndarray,
) -> float:
    """Return rotation- and sign-invariant overlap of two 2D PCA subspaces."""

    singular_values = np.linalg.svd(
        reference_components @ candidate_components.T,
        compute_uv=False,
    )
    similarity = float(np.mean(singular_values**2))
    return min(1.0, max(0.0, similarity))


def build_validation_report(
    table: FeatureTable,
    features: tuple[AnalysisFeature, ...] = DEFAULT_PCA_FEATURES,
    correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
) -> ValidationReport:
    """Measure redundancy, row extremeness and leave-one-out PCA stability.

    Extremeness is descriptive: it ranks rows by their root-mean-square
    standardized feature value and does not automatically classify a valid
    instance as an outlier. PCA stability compares two-dimensional component
    subspaces, which is invariant to arbitrary sign changes and axis rotations.
    """

    if len(table.values) < 4:
        raise AnalysisError(
            "At least four instances are required for leave-one-out validation"
        )
    if len(features) < 2:
        raise AnalysisError(
            "At least two features are required for PCA validation diagnostics"
        )
    if not 0.0 < correlation_threshold <= 1.0:
        raise AnalysisError("Correlation threshold must be in the interval (0, 1]")

    prepared = preprocess_for_pca(table, features)
    matrix = np.asarray(prepared.standardized_values, dtype=float)
    correlation = np.corrcoef(matrix, rowvar=False)
    if not np.isfinite(correlation).all():
        raise AnalysisError("Correlation diagnostics produced a non-finite value")

    pairs = tuple(
        sorted(
            (
                CorrelationPair(
                    left=prepared.feature_names[left],
                    right=prepared.feature_names[right],
                    correlation=float(correlation[left, right]),
                )
                for left in range(len(prepared.feature_names))
                for right in range(left + 1, len(prepared.feature_names))
                if abs(float(correlation[left, right])) >= correlation_threshold
            ),
            key=lambda pair: abs(pair.correlation),
            reverse=True,
        )
    )

    extremeness = []
    for source, row in zip(prepared.sources, matrix, strict=True):
        dominant_index = int(np.argmax(np.abs(row)))
        extremeness.append(
            InstanceExtremeness(
                source=source,
                rms_z_score=float(sqrt(float(np.mean(row**2)))),
                max_abs_z_score=float(abs(row[dominant_index])),
                dominant_feature=prepared.feature_names[dominant_index],
                dominant_z_score=float(row[dominant_index]),
            )
        )
    extremeness.sort(key=lambda row: row.rms_z_score, reverse=True)

    reference = fit_pca_2d(prepared)
    reference_components = np.asarray(reference.components, dtype=float)
    folds = []
    for omitted_index, source in enumerate(table.sources):
        reduced = _subset_table(table, omitted_index)
        candidate = fit_pca_2d(preprocess_for_pca(reduced, features))
        folds.append(
            StabilityFold(
                omitted_source=source,
                subspace_similarity=_subspace_similarity(
                    reference_components,
                    np.asarray(candidate.components, dtype=float),
                ),
                variance_retained=candidate.total_explained_variance_ratio,
            )
        )

    return ValidationReport(
        feature_names=prepared.feature_names,
        correlation_matrix=tuple(
            tuple(float(value) for value in row) for row in correlation
        ),
        correlation_threshold=correlation_threshold,
        high_correlations=pairs,
        extremeness=tuple(extremeness),
        stability_folds=tuple(folds),
    )
