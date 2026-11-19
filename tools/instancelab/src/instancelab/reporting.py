"""Dependency-free reproducibility exports for an InstanceLab analysis."""

from collections import Counter
from collections.abc import Sequence

from .analysis import AnalysisError, FeatureTable
from .diagnostics import ValidationReport
from .pca import PCAResult
from .performance import PerformanceAnalysis


ANALYSIS_REPORT_SCHEMA_VERSION = "1.2"


def _markdown_cell(value: object) -> str:
    """Keep generated Markdown tables valid for repository-provided labels."""

    return str(value).replace("|", r"\|").replace("\n", " ")


def build_reproducibility_report(
    instance_names: Sequence[str],
    instance_groups: Sequence[str],
    table: FeatureTable,
    pca: PCAResult,
    validation: ValidationReport,
    excluded_instances: Sequence[tuple[str, str, str]] = (),
    performance: PerformanceAnalysis | None = None,
) -> dict[str, object]:
    """Build a JSON-ready report without filesystem paths or generated data."""

    row_count = len(table.values)
    if len(instance_names) != row_count or len(instance_groups) != row_count:
        raise AnalysisError(
            "Export names, groups and feature-table rows must have equal lengths"
        )
    if len(set(instance_names)) != len(instance_names):
        raise AnalysisError("Export instance names must be unique")
    if len(pca.coordinates) != row_count:
        raise AnalysisError("PCA coordinate count must match the feature table")

    source_to_name = dict(zip(table.sources, instance_names, strict=True))
    preprocessing = pca.preprocessing
    report: dict[str, object] = {
        "schema_version": ANALYSIS_REPORT_SCHEMA_VERSION,
        "scope": {
            "analysis_type": "exploratory_unsupervised_feature_space_pca",
            "full_supervised_isa": False,
            "reference_instance_count": row_count,
            "excluded_instance_count": len(excluded_instances),
            "catalog_feature_count": len(table.feature_names),
            "pca_feature_count": len(preprocessing.feature_names),
        },
        "preprocessing": [
            {
                "feature": feature,
                "transformation": transformation,
                "mean": mean,
                "scale": scale,
            }
            for feature, transformation, mean, scale in zip(
                preprocessing.feature_names,
                preprocessing.transformations,
                preprocessing.means,
                preprocessing.scales,
                strict=True,
            )
        ],
        "pca": {
            "explained_variance_ratio": {
                "pc1": pca.explained_variance_ratio[0],
                "pc2": pca.explained_variance_ratio[1],
                "total_2d": pca.total_explained_variance_ratio,
            },
            "loadings": list(pca.loading_rows()),
            "coordinates": [
                {
                    "name": name,
                    "group": group,
                    "pc1": coordinate[0],
                    "pc2": coordinate[1],
                }
                for name, group, coordinate in zip(
                    instance_names,
                    instance_groups,
                    pca.coordinates,
                    strict=True,
                )
            ],
        },
        "validation": {
            "correlation_threshold": validation.correlation_threshold,
            "maximum_absolute_correlation": (
                validation.maximum_absolute_correlation
            ),
            "high_correlations": [
                {
                    "feature_1": pair.left,
                    "feature_2": pair.right,
                    "pearson_r": pair.correlation,
                }
                for pair in validation.high_correlations
            ],
            "extremeness": [
                {
                    "name": source_to_name[row.source],
                    "rms_z_score": row.rms_z_score,
                    "max_abs_z_score": row.max_abs_z_score,
                    "dominant_feature": row.dominant_feature,
                    "dominant_z_score": row.dominant_z_score,
                }
                for row in validation.extremeness
            ],
            "leave_one_out": [
                {
                    "omitted_name": source_to_name[fold.omitted_source],
                    "subspace_similarity": fold.subspace_similarity,
                    "variance_retained": fold.variance_retained,
                }
                for fold in validation.stability_folds
            ],
            "summary": {
                "mean_subspace_similarity": (
                    validation.mean_subspace_similarity
                ),
                "minimum_subspace_similarity": (
                    validation.minimum_subspace_similarity
                ),
                "variance_retained_range": list(
                    validation.variance_retained_range
                ),
            },
        },
        "excluded_instances": [
            {"name": name, "group": group, "reason": reason}
            for name, group, reason in excluded_instances
        ],
        "limitations": [
            "The reference set is small and the projection is exploratory.",
            "PCA axes are fitted from instance characteristics only, not from algorithm performance data.",
            "Feature-score correlations may be confounded by the synthetic/real instance-group split.",
            "The report does not define algorithm footprints or predict performance.",
        ],
    }
    report["performance"] = None if performance is None else {
        "scope": "descriptive_score_analysis",
        "algorithms": list(performance.algorithms),
        "scores": list(performance.score_rows()),
        "summaries": [
            {
                "algorithm": summary.algorithm,
                "mean_score": summary.mean_score,
                "minimum_score": summary.minimum_score,
                "maximum_score": summary.maximum_score,
                "best_count": summary.best_count,
                "timed_count": summary.timed_count,
                "mean_seconds": summary.mean_seconds,
                "median_seconds": summary.median_seconds,
                "maximum_seconds": summary.maximum_seconds,
            }
            for summary in performance.summaries
        ],
        "feature_score_correlations": [
            {
                "feature": row.feature,
                "algorithm": row.algorithm,
                "pearson_r": row.pearson_r,
            }
            for row in performance.correlations
        ],
        "execution_seconds": list(performance.time_rows()),
        "feature_time_correlations": [
            {
                "feature": row.feature,
                "algorithm": row.algorithm,
                "pearson_r_log10_seconds": row.pearson_r,
                "timed_instances": row.timed_instances,
            }
            for row in performance.time_correlations
        ],
        "execution_times_available": performance.execution_times_available,
        "algorithm_footprints_inferred": False,
    }
    return report


def _seconds_cell(value: float | None) -> str:
    return "–" if value is None else f"{value:.3f}"


def build_academic_summary(
    instance_names: Sequence[str],
    instance_groups: Sequence[str],
    table: FeatureTable,
    pca: PCAResult,
    validation: ValidationReport,
    excluded_instances: Sequence[tuple[str, str, str]] = (),
    performance: PerformanceAnalysis | None = None,
) -> str:
    """Build a readable, deterministic Markdown summary of the analysis."""

    # Reuse the machine-readable export's consistency checks before formatting.
    build_reproducibility_report(
        instance_names,
        instance_groups,
        table,
        pca,
        validation,
        excluded_instances,
        performance,
    )

    group_counts = Counter(instance_groups)
    group_text = ", ".join(
        f"{_markdown_cell(group)}: {count}"
        for group, count in sorted(group_counts.items())
    )
    retained_low, retained_high = validation.variance_retained_range
    lines = [
        "# InstanceLab Academic Analysis Summary",
        "",
        "## Scope",
        "",
        f"- Reference instances: **{len(instance_names)}** ({group_text}).",
        f"- Validated catalog characteristics: **{len(table.feature_names)}**.",
        f"- Selected PCA inputs: **{len(pca.preprocessing.feature_names)}**.",
        "- Analysis type: exploratory unsupervised feature-space PCA.",
        "- Full supervised Instance Space Analysis: **not claimed**.",
        "",
        "## Feature-space projection",
        "",
        f"- PC1 explained variance: **{pca.explained_variance_ratio[0]:.1%}**.",
        f"- PC2 explained variance: **{pca.explained_variance_ratio[1]:.1%}**.",
        f"- Total variance retained in 2D: **{pca.total_explained_variance_ratio:.1%}**.",
        "- PCA inputs are transformed where documented, standardized, and fitted "
        "from instance characteristics only.",
        "- Selected inputs: "
        + ", ".join(
            f"`{_markdown_cell(feature)}`"
            for feature in pca.preprocessing.feature_names
        )
        + ".",
        "",
        "## Scientific validation",
        "",
        f"- Maximum absolute selected-feature correlation: **{validation.maximum_absolute_correlation:.3f}**.",
        f"- Feature pairs above the {validation.correlation_threshold:.2f} threshold: "
        f"**{len(validation.high_correlations)}**.",
        f"- Mean leave-one-out subspace similarity: **{validation.mean_subspace_similarity:.3f}**.",
        f"- Minimum leave-one-out subspace similarity: **{validation.minimum_subspace_similarity:.3f}**.",
        f"- Leave-one-out 2D variance-retention range: **{retained_low:.1%} to {retained_high:.1%}**.",
        "",
        "## Algorithm-score analysis",
        "",
    ]

    if performance is None:
        lines.extend(
            [
                "No complete comparison matrix for at least two algorithms was available.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Stored solutions were validated and re-scored before comparison.",
                "",
                "| Algorithm | Mean score | Minimum | Maximum | Best count | Timed | Median time (s) |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        lines.extend(
            "| "
            f"{_markdown_cell(summary.algorithm)} | "
            f"{summary.mean_score:.4f} | "
            f"{summary.minimum_score:.4f} | "
            f"{summary.maximum_score:.4f} | "
            f"{summary.best_count} | "
            f"{summary.timed_count} | "
            f"{_seconds_cell(summary.median_seconds)} |"
            for summary in performance.summaries
        )
        best_summary = max(
            performance.summaries,
            key=lambda summary: summary.mean_score,
        )
        lines.extend(
            [
                "",
                f"Highest mean score: **{_markdown_cell(best_summary.algorithm)}** "
                f"({best_summary.mean_score:.4f}).",
                "",
                (
                    "Execution times were measured by re-running only published "
                    "pairs; a time is reported only where the re-run reproduced "
                    "the published score."
                    if performance.execution_times_available
                    else "Execution times were not available for the published results."
                ),
                "",
            ]
        )

    lines.extend(["## Excluded instances", ""])
    if excluded_instances:
        lines.extend(
            f"- **{_markdown_cell(name)}** ({_markdown_cell(group)}): "
            f"{_markdown_cell(reason)}"
            for name, group, reason in excluded_instances
        )
        lines.append("")
    else:
        lines.extend(["No discovered reference instance was excluded.", ""])

    lines.extend(
        [
            "## Interpretation boundaries",
            "",
            "- The current reference set is small, so conclusions are exploratory.",
            "- PCA distance represents similarity under selected instance characteristics, "
            "not algorithm performance.",
            "- Feature-score correlations are descriptive and may be confounded by the "
            "synthetic/real group split.",
            "- This analysis does not infer algorithm footprints or predict performance "
            "on unseen instances.",
            "",
        ]
    )
    return "\n".join(lines)
