"""Core data loading, validation and feature extraction for InstanceLab."""

from .analysis import (
    DEFAULT_PCA_FEATURES,
    PERFORMANCE_FEATURES,
    TIME_PRESSURE_FEATURES,
    AnalysisError,
    AnalysisFeature,
    FeatureTable,
    PreprocessedData,
    apply_fitted_preprocessing,
    build_feature_table,
    preprocess_for_pca,
)
from .clipp import InstanceParseError, parse_instance, read_instance
from .diagnostics import (
    DEFAULT_CORRELATION_THRESHOLD,
    CorrelationPair,
    InstanceExtremeness,
    StabilityFold,
    ValidationReport,
    build_validation_report,
)
from .features import (
    FEATURE_DEFINITIONS,
    FEATURE_NAMES,
    FeatureDefinition,
    FeatureExtractionError,
    InstanceFeatures,
    compare_instances,
    extract_features,
)
from .model import Instance, Street
from .pca import PCAResult, fit_pca_2d, project_feature_table
from .performance import (
    AlgorithmResult,
    AlgorithmSummary,
    FeatureScoreCorrelation,
    PerformanceAnalysis,
    analyze_algorithm_performance,
)
from .reporting import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    build_academic_summary,
    build_reproducibility_report,
)
from .validation import ValidationIssue, validate_instance

__all__ = [
    "DEFAULT_PCA_FEATURES",
    "PERFORMANCE_FEATURES",
    "TIME_PRESSURE_FEATURES",
    "DEFAULT_CORRELATION_THRESHOLD",
    "FEATURE_DEFINITIONS",
    "FEATURE_NAMES",
    "ANALYSIS_REPORT_SCHEMA_VERSION",
    "AnalysisError",
    "AnalysisFeature",
    "AlgorithmResult",
    "AlgorithmSummary",
    "CorrelationPair",
    "FeatureDefinition",
    "FeatureExtractionError",
    "FeatureTable",
    "FeatureScoreCorrelation",
    "Instance",
    "InstanceExtremeness",
    "InstanceFeatures",
    "InstanceParseError",
    "PreprocessedData",
    "PCAResult",
    "PerformanceAnalysis",
    "Street",
    "StabilityFold",
    "ValidationIssue",
    "ValidationReport",
    "apply_fitted_preprocessing",
    "analyze_algorithm_performance",
    "build_academic_summary",
    "build_feature_table",
    "build_reproducibility_report",
    "build_validation_report",
    "compare_instances",
    "extract_features",
    "fit_pca_2d",
    "parse_instance",
    "preprocess_for_pca",
    "project_feature_table",
    "read_instance",
    "validate_instance",
]
