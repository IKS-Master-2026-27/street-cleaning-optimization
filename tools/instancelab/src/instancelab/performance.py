"""Descriptive links between instance characteristics and algorithm scores."""

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Iterable

import numpy as np

from .analysis import (
    PERFORMANCE_FEATURES,
    AnalysisError,
    AnalysisFeature,
    FeatureTable,
    preprocess_for_pca,
)


@dataclass(frozen=True, slots=True)
class AlgorithmResult:
    """One validated algorithm score for one named instance."""

    instance_name: str
    algorithm: str
    score: float
    coverage: float
    efficiency: float
    execution_time_seconds: float | None = None

    def __post_init__(self) -> None:
        values = (self.score, self.coverage, self.efficiency)
        if not all(isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            raise AnalysisError("Algorithm score components must be finite in [0, 1]")
        if self.execution_time_seconds is not None and (
            not isfinite(self.execution_time_seconds)
            or self.execution_time_seconds < 0.0
        ):
            raise AnalysisError("Execution time must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class AlgorithmSummary:
    algorithm: str
    mean_score: float
    minimum_score: float
    maximum_score: float
    best_count: int
    timed_count: int = 0
    mean_seconds: float | None = None
    median_seconds: float | None = None
    maximum_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class FeatureScoreCorrelation:
    feature: str
    algorithm: str
    pearson_r: float | None


@dataclass(frozen=True, slots=True)
class FeatureTimeCorrelation:
    """Pearson r between a standardized feature and log10(seconds)."""

    feature: str
    algorithm: str
    pearson_r: float | None
    timed_instances: int


@dataclass(frozen=True, slots=True)
class PerformanceAnalysis:
    """Complete score matrix and descriptive feature-score correlations."""

    instance_names: tuple[str, ...]
    algorithms: tuple[str, ...]
    scores: tuple[tuple[float, ...], ...]
    summaries: tuple[AlgorithmSummary, ...]
    correlations: tuple[FeatureScoreCorrelation, ...]
    seconds: tuple[tuple[float | None, ...], ...] = ()
    time_correlations: tuple[FeatureTimeCorrelation, ...] = ()

    @property
    def execution_times_available(self) -> bool:
        return any(value is not None for row in self.seconds for value in row)

    def time_rows(self) -> tuple[dict[str, str | float | None], ...]:
        return tuple(
            {
                "instance": instance_name,
                **dict(zip(self.algorithms, row, strict=True)),
            }
            for instance_name, row in zip(self.instance_names, self.seconds, strict=True)
        )

    def score_rows(self) -> tuple[dict[str, str | float], ...]:
        return tuple(
            {
                "instance": instance_name,
                **dict(zip(self.algorithms, row, strict=True)),
            }
            for instance_name, row in zip(
                self.instance_names,
                self.scores,
                strict=True,
            )
        )


def analyze_algorithm_performance(
    table: FeatureTable,
    instance_names: tuple[str, ...],
    results: Iterable[AlgorithmResult],
    features: tuple[AnalysisFeature, ...] = PERFORMANCE_FEATURES,
) -> PerformanceAnalysis:
    """Relate a complete algorithm-score matrix to standardized features.

    By default the nine PCA inputs plus the four time-pressure
    characteristics are related to performance. Execution times are optional
    per result. Feature-time correlations use
    log10(seconds) over the instances that have a time for that algorithm.

    This is descriptive analysis only. It does not fit a predictor or infer an
    algorithm footprint, which would require a larger and more diverse result
    set plus an explicit good-performance definition.
    """

    if len(instance_names) != len(table.values):
        raise AnalysisError("Performance instance names must match feature rows")
    if len(set(instance_names)) != len(instance_names):
        raise AnalysisError("Performance instance names must be unique")

    result_rows = tuple(results)
    keys = [(result.instance_name, result.algorithm) for result in result_rows]
    if len(keys) != len(set(keys)):
        raise AnalysisError("Algorithm results contain duplicate instance/algorithm rows")

    algorithms = tuple(sorted({result.algorithm for result in result_rows}))
    if len(algorithms) < 2:
        raise AnalysisError("At least two algorithms are required for comparison")

    result_map = {
        (result.instance_name, result.algorithm): result
        for result in result_rows
    }
    missing = [
        (instance_name, algorithm)
        for instance_name in instance_names
        for algorithm in algorithms
        if (instance_name, algorithm) not in result_map
    ]
    if missing:
        raise AnalysisError(
            "Algorithm comparison requires a complete score matrix; "
            f"missing {len(missing)} row(s)"
        )

    scores = tuple(
        tuple(result_map[(name, algorithm)].score for algorithm in algorithms)
        for name in instance_names
    )
    seconds = tuple(
        tuple(
            result_map[(name, algorithm)].execution_time_seconds
            for algorithm in algorithms
        )
        for name in instance_names
    )
    score_matrix = np.asarray(scores, dtype=float)
    best = np.max(score_matrix, axis=1)
    summaries = []
    for index, algorithm in enumerate(algorithms):
        timed = [row[index] for row in seconds if row[index] is not None]
        summaries.append(
            AlgorithmSummary(
                algorithm=algorithm,
                mean_score=float(mean(score_matrix[:, index])),
                minimum_score=float(np.min(score_matrix[:, index])),
                maximum_score=float(np.max(score_matrix[:, index])),
                best_count=int(
                    np.count_nonzero(np.isclose(score_matrix[:, index], best, atol=1e-12))
                ),
                timed_count=len(timed),
                mean_seconds=float(mean(timed)) if timed else None,
                median_seconds=float(np.median(timed)) if timed else None,
                maximum_seconds=float(max(timed)) if timed else None,
            )
        )

    prepared = preprocess_for_pca(table, features)
    feature_matrix = np.asarray(prepared.standardized_values, dtype=float)
    correlations = []
    for feature_index, feature_name in enumerate(prepared.feature_names):
        for algorithm_index, algorithm in enumerate(algorithms):
            target = score_matrix[:, algorithm_index]
            if float(np.std(target)) == 0.0:
                coefficient = None
            else:
                coefficient = float(
                    np.corrcoef(feature_matrix[:, feature_index], target)[0, 1]
                )
            correlations.append(
                FeatureScoreCorrelation(feature_name, algorithm, coefficient)
            )

    time_correlations = []
    for algorithm_index, algorithm in enumerate(algorithms):
        rows = [
            index
            for index, row in enumerate(seconds)
            if row[algorithm_index] is not None and row[algorithm_index] > 0.0
        ]
        log_seconds = np.log10([seconds[index][algorithm_index] for index in rows])
        for feature_index, feature_name in enumerate(prepared.feature_names):
            coefficient = None
            if len(rows) >= 3:
                column = feature_matrix[rows, feature_index]
                if float(np.std(column)) > 0.0 and float(np.std(log_seconds)) > 0.0:
                    coefficient = float(np.corrcoef(column, log_seconds)[0, 1])
            time_correlations.append(
                FeatureTimeCorrelation(feature_name, algorithm, coefficient, len(rows))
            )

    return PerformanceAnalysis(
        instance_names=instance_names,
        algorithms=algorithms,
        scores=scores,
        summaries=tuple(summaries),
        correlations=tuple(correlations),
        seconds=seconds,
        time_correlations=tuple(time_correlations),
    )
