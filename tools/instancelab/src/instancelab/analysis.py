"""Feature-table construction and transparent preprocessing for 2D PCA."""

from dataclasses import dataclass
from math import isfinite, log1p, sqrt
from typing import Iterable

from .features import FEATURE_NAMES, InstanceFeatures, extract_features
from .model import Instance


class AnalysisError(ValueError):
    """Raised when an analysis table cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class AnalysisFeature:
    """One selected PCA input and the reason it is retained."""

    name: str
    transformation: str
    rationale: str


# Nine complementary characteristics are retained from the full 26-feature
# catalog. Highly correlated alternatives remain available for reporting but
# are intentionally not all sent to PCA with only 15 current observations.
DEFAULT_PCA_FEATURES = (
    AnalysisFeature(
        "num_junctions",
        "log1p",
        "Network scale, retained instead of the highly correlated street count.",
    ),
    AnalysisFeature(
        "time_limit",
        "log1p",
        "Route budget configured by the problem instance.",
    ),
    AnalysisFeature(
        "out_degree_cv",
        "identity",
        "Heterogeneity of directed graph connectivity.",
    ),
    AnalysisFeature(
        "mandatory_service_fraction",
        "identity",
        "Relative amount of compulsory work by street count.",
    ),
    AnalysisFeature(
        "bidirectional_street_fraction",
        "identity",
        "Directional routing flexibility.",
    ),
    AnalysisFeature(
        "travel_time_cv",
        "identity",
        "Scale-independent travel-time heterogeneity.",
    ),
    AnalysisFeature(
        "high_requirement_fraction",
        "identity",
        "Concentration of streets requiring the highest cleaning capability.",
    ),
    AnalysisFeature(
        "mandatory_length_per_vehicle",
        "log1p",
        "Mandatory workload relative to fleet size.",
    ),
    AnalysisFeature(
        "mean_mandatory_fleet_coverage",
        "identity",
        "Average interchangeability of vehicles over mandatory work.",
    ),
)

# The time-pressure characteristics are deliberately kept out of the PCA: on
# the reference set mandatory_time_pressure correlates at r = 0.95 with
# mandatory_service_fraction and mean_mandatory_round_trip_ratio at r = 0.87
# with mean_mandatory_fleet_coverage, so adding them would double-weight
# information the map already contains. They describe something algorithms
# react to, so they are included when relating characteristics to performance.
TIME_PRESSURE_FEATURES = (
    AnalysisFeature(
        "mandatory_time_pressure",
        "identity",
        "Compulsory traversal work relative to the total fleet time budget.",
    ),
    AnalysisFeature(
        "service_time_pressure",
        "identity",
        "Traversal work of all serviceable streets relative to the fleet budget.",
    ),
    AnalysisFeature(
        "mean_mandatory_round_trip_ratio",
        "identity",
        "How far compulsory work lies from the depot relative to T.",
    ),
    AnalysisFeature(
        "max_mandatory_round_trip_ratio",
        "identity",
        "The tightest single mandatory street relative to T.",
    ),
)
PERFORMANCE_FEATURES = DEFAULT_PCA_FEATURES + TIME_PRESSURE_FEATURES


@dataclass(frozen=True, slots=True)
class FeatureTable:
    """A deterministic numerical table: rows are instances, columns are features."""

    sources: tuple[str, ...]
    feature_names: tuple[str, ...]
    values: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if len(self.sources) != len(self.values):
            raise AnalysisError("Feature-table source and row counts must match")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise AnalysisError("Feature-table column names must be unique")
        for row_index, row in enumerate(self.values):
            if len(row) != len(self.feature_names):
                raise AnalysisError(
                    f"Row {row_index} has {len(row)} values; "
                    f"expected {len(self.feature_names)}"
                )
            if not all(isfinite(value) for value in row):
                raise AnalysisError(f"Row {row_index} contains a non-finite value")

    def as_rows(self) -> tuple[dict[str, str | float], ...]:
        """Return dependency-free records suitable for a UI or CSV adapter."""

        return tuple(
            {
                "source": source,
                **dict(zip(self.feature_names, row, strict=True)),
            }
            for source, row in zip(self.sources, self.values, strict=True)
        )

    def column(self, name: str) -> tuple[float, ...]:
        """Return one named column without depending on pandas."""

        try:
            index = self.feature_names.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc
        return tuple(row[index] for row in self.values)


@dataclass(frozen=True, slots=True)
class PreprocessedData:
    """Selected, transformed and standardized data ready for PCA."""

    sources: tuple[str, ...]
    feature_names: tuple[str, ...]
    transformations: tuple[str, ...]
    transformed_values: tuple[tuple[float, ...], ...]
    standardized_values: tuple[tuple[float, ...], ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


def build_feature_table(instances: Iterable[Instance]) -> FeatureTable:
    """Extract all catalog features into one stable numerical table."""

    vectors: tuple[InstanceFeatures, ...] = tuple(
        extract_features(instance) for instance in instances
    )
    return FeatureTable(
        sources=tuple(vector.source for vector in vectors),
        feature_names=FEATURE_NAMES,
        values=tuple(vector.values for vector in vectors),
    )


def _transform(value: float, transformation: str, feature_name: str) -> float:
    if transformation == "identity":
        return value
    if transformation == "log1p":
        if value < 0.0:
            raise AnalysisError(
                f"Feature {feature_name!r} cannot use log1p with value {value}"
            )
        return log1p(value)
    raise AnalysisError(
        f"Unknown transformation {transformation!r} for feature {feature_name!r}"
    )


def preprocess_for_pca(
    table: FeatureTable,
    features: tuple[AnalysisFeature, ...] = DEFAULT_PCA_FEATURES,
) -> PreprocessedData:
    """Select, transform and z-score features with explicit fitted parameters.

    Population standard deviation (``ddof=0``) matches the conventional PCA
    preprocessing used by standard scaling implementations. Constant columns
    are rejected instead of silently producing meaningless zero-variance input.
    """

    if len(table.values) < 3:
        raise AnalysisError("At least three instances are required for 2D PCA")
    if not features:
        raise AnalysisError("At least one PCA feature must be selected")

    selected_names = tuple(feature.name for feature in features)
    if len(set(selected_names)) != len(selected_names):
        raise AnalysisError("Selected PCA feature names must be unique")

    missing = [name for name in selected_names if name not in table.feature_names]
    if missing:
        raise AnalysisError(f"Feature table is missing selected columns: {missing}")

    indices = tuple(table.feature_names.index(name) for name in selected_names)
    transformed = tuple(
        tuple(
            _transform(row[index], feature.transformation, feature.name)
            for index, feature in zip(indices, features, strict=True)
        )
        for row in table.values
    )

    means = tuple(
        sum(row[column] for row in transformed) / len(transformed)
        for column in range(len(features))
    )
    scales = tuple(
        sqrt(
            sum((row[column] - means[column]) ** 2 for row in transformed)
            / len(transformed)
        )
        for column in range(len(features))
    )

    constant = [
        name for name, scale in zip(selected_names, scales, strict=True) if scale == 0.0
    ]
    if constant:
        raise AnalysisError(f"Selected PCA columns have zero variance: {constant}")

    standardized = tuple(
        tuple(
            (value - mean) / scale
            for value, mean, scale in zip(row, means, scales, strict=True)
        )
        for row in transformed
    )
    if not all(isfinite(value) for row in standardized for value in row):
        raise AnalysisError("Preprocessing produced a non-finite value")

    return PreprocessedData(
        sources=table.sources,
        feature_names=selected_names,
        transformations=tuple(feature.transformation for feature in features),
        transformed_values=transformed,
        standardized_values=standardized,
        means=means,
        scales=scales,
    )


def apply_fitted_preprocessing(
    table: FeatureTable,
    fitted: PreprocessedData,
) -> tuple[tuple[float, ...], ...]:
    """Transform new rows with parameters fitted on the reference dataset."""

    missing = [name for name in fitted.feature_names if name not in table.feature_names]
    if missing:
        raise AnalysisError(f"Feature table is missing fitted columns: {missing}")

    indices = tuple(table.feature_names.index(name) for name in fitted.feature_names)
    standardized = tuple(
        tuple(
            (
                _transform(row[index], transformation, feature_name) - mean
            )
            / scale
            for index, feature_name, transformation, mean, scale in zip(
                indices,
                fitted.feature_names,
                fitted.transformations,
                fitted.means,
                fitted.scales,
                strict=True,
            )
        )
        for row in table.values
    )
    if not all(isfinite(value) for row in standardized for value in row):
        raise AnalysisError("Fitted preprocessing produced a non-finite value")
    return standardized
