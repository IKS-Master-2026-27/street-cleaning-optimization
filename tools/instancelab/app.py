"""Streamlit entry point for the InstanceLab exploratory dashboard."""

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from instancelab import (
    DEFAULT_PCA_FEATURES,
    FEATURE_DEFINITIONS,
    build_academic_summary,
    build_feature_table,
    build_reproducibility_report,
    build_validation_report,
    analyze_algorithm_performance,
    fit_pca_2d,
    parse_instance,
    preprocess_for_pca,
    project_feature_table,
    validate_instance,
)
from instancelab.adapters import (
    DATASET_LABELS,
    SharedRepositoryError,
    find_shared_repository_root,
    resolve_dataset,
    scan_shared_instances,
    scan_shared_algorithm_results,
    shared_repository_fingerprint,
)
from instancelab.analysis import FeatureTable
from instancelab.timing import attach_execution_times, read_timing_csv, stale_timings


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMING_CSV = PROJECT_ROOT / "results" / "timing" / "results.csv"
DEFAULT_TIMING_CSVS = {
    "realistic": PROJECT_ROOT / "results" / "timing_realistic" / "results.csv",
    "legacy": DEFAULT_TIMING_CSV,
}


def file_fingerprint(paths) -> tuple[tuple[str, int, int], ...]:
    """Cache key for InstanceLab-owned inputs (the timing file)."""

    fingerprint = []
    for path in paths:
        if path.is_file():
            status = path.stat()
            fingerprint.append((str(path), status.st_size, status.st_mtime_ns))
    return tuple(fingerprint)


st.set_page_config(
    page_title="InstanceLab",
    page_icon="🧭",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
    [data-testid="stMetric"] {
        border: 1px solid #e2e8f0;
        border-radius: 0.75rem;
        padding: 0.8rem 1rem;
        background: rgba(248, 250, 252, 0.55);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def analyze_repository(
    repository_path: str,
    repository_revision: tuple[tuple[str, int, int], ...],
    timing_path: str,
    local_revision: tuple[tuple[str, int, int], ...],
    dataset: str = "auto",
):
    """Load read-only class data and return compact analysis artifacts.

    Only instances published in the shared repository are analysed, and
    scores come only from the solutions published there.
    """

    # The revision arguments are part of the cache key only. They change when
    # a recognized instance, published result or timing file changes.
    del repository_revision, local_revision
    scan = scan_shared_instances(repository_path, dataset)
    loaded = scan.loaded
    if not loaded:
        raise SharedRepositoryError(
            "No valid CLIPP instances are available for analysis"
        )
    sources = tuple(source for source, _ in loaded)
    table = build_feature_table(instance for _, instance in loaded)
    projection = fit_pca_2d(preprocess_for_pca(table))
    validation_report = build_validation_report(table)

    result_scan = scan_shared_algorithm_results(repository_path, loaded)
    timings = ()
    timing_error = None
    if timing_path and Path(timing_path).is_file():
        try:
            timings = read_timing_csv(timing_path)
        except (OSError, ValueError) as error:
            timing_error = str(error)
    results = attach_execution_times(result_scan.results, timings)
    outdated_timings = stale_timings(result_scan.results, timings)

    # Scores are compared on instances that have published results; a newly
    # added instance without any result does not hide the comparison.
    benchmarked = set(result_scan.benchmarked_instances)
    rows = [index for index, source in enumerate(sources) if source.name in benchmarked]
    benchmarked_table = FeatureTable(
        sources=tuple(table.sources[index] for index in rows),
        feature_names=table.feature_names,
        values=tuple(table.values[index] for index in rows),
    )
    performance_analysis = None
    performance_error = None
    try:
        performance_analysis = analyze_algorithm_performance(
            benchmarked_table,
            tuple(sources[index].name for index in rows),
            results,
        )
    except ValueError as error:
        performance_error = str(error)
    return (
        sources,
        table,
        projection,
        validation_report,
        scan.failures,
        performance_analysis,
        result_scan.failures,
        performance_error,
        timings,
        timing_error,
        result_scan.unbenchmarked_instances,
        outdated_timings,
    )


st.title("InstanceLab")
st.caption(
    "Validated CLIPP instance characteristics and an unsupervised PCA "
    "feature-space projection."
)

st.sidebar.header("Data source")
detected_repository = find_shared_repository_root(Path.cwd())
repository_path = st.sidebar.text_input(
    "Shared repository path",
    value=os.environ.get(
        "CLIPP_SHARED_REPO",
        str(detected_repository) if detected_repository else "",
    ),
    placeholder=r"C:\path\to\street-cleaning-optimization",
)
st.sidebar.caption("The shared repository is read only; InstanceLab writes no data there.")
dataset_choice = st.sidebar.radio(
    "Instance set",
    options=("realistic", "legacy"),
    format_func=lambda key: DATASET_LABELS[key]
    + (" - main comparison" if key == "realistic" else " - optional"),
    help="The realistic whole-city instances are the main comparison. The old "
    "synthetic + real_instances set can still be inspected.",
)
try:
    dataset = resolve_dataset(repository_path, dataset_choice) if repository_path else dataset_choice
except (OSError, ValueError):
    dataset = dataset_choice
timing_path = st.sidebar.text_input(
    "Execution-time file",
    value=str(DEFAULT_TIMING_CSVS[dataset]),
    key=f"timing_path_{dataset}",
    help="Written by `python -m instancelab.timing` for published pairs only.",
)
if st.sidebar.button("Reload repository instances", width="stretch"):
    analyze_repository.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("Add one instance")
uploaded_file = st.sidebar.file_uploader(
    "CLIPP text file",
    type=("txt",),
    help="The file is validated in memory and is not written to either repository.",
)

if not repository_path:
    st.info(
        "Enter the local shared-repository path in the sidebar or set "
        "`CLIPP_SHARED_REPO` before starting Streamlit."
    )
    st.stop()

try:
    with st.spinner("Reading, validating and analysing instances…"):
        repository_revision = shared_repository_fingerprint(repository_path, dataset)
        local_revision = file_fingerprint(
            (Path(timing_path),) if timing_path else ()
        )
        (
            sources,
            feature_table,
            pca_result,
            validation_report,
            repository_failures,
            performance_analysis,
            performance_failures,
            performance_error,
            timing_records,
            timing_error,
            unbenchmarked_instances,
            outdated_timings,
        ) = analyze_repository(
            repository_path,
            repository_revision,
            timing_path,
            local_revision,
            dataset,
        )
except (OSError, ValueError) as error:
    st.error(f"Analysis stopped: {error}")
    st.stop()

if repository_failures:
    st.warning(
        f"{len(repository_failures)} discovered instance(s) failed validation and "
        "were excluded from the reference PCA."
    )
    with st.expander("Excluded repository instances"):
        for failure in repository_failures:
            st.write(f"**{failure.source.name}:** {failure.reason}")

metadata = pd.DataFrame(
    {
        "name": [source.name for source in sources],
        "group": [source.group for source in sources],
        "path": [str(source.path) for source in sources],
    }
)
features = pd.DataFrame(feature_table.values, columns=feature_table.feature_names)
coordinates = pd.DataFrame(pca_result.coordinates, columns=("pc1", "pc2"))
instance_data = pd.concat((metadata, features, coordinates), axis=1)
reproducibility_report = build_reproducibility_report(
    metadata["name"].tolist(),
    metadata["group"].tolist(),
    feature_table,
    pca_result,
    validation_report,
    tuple(
        (failure.source.name, failure.source.group, failure.reason)
        for failure in repository_failures
    ),
    performance=performance_analysis,
)
academic_summary = build_academic_summary(
    metadata["name"].tolist(),
    metadata["group"].tolist(),
    feature_table,
    pca_result,
    validation_report,
    tuple(
        (failure.source.name, failure.source.group, failure.reason)
        for failure in repository_failures
    ),
    performance=performance_analysis,
)

if uploaded_file is not None:
    try:
        uploaded_text = uploaded_file.getvalue().decode("utf-8-sig")
        uploaded_instance = parse_instance(uploaded_text, source=uploaded_file.name)
        upload_issues = validate_instance(uploaded_instance)
        if upload_issues:
            st.sidebar.error(f"Invalid instance: {len(upload_issues)} issue(s)")
            with st.sidebar.expander("Validation details"):
                for issue in upload_issues:
                    st.write(f"**{issue.code}:** {issue.message}")
        else:
            uploaded_table = build_feature_table((uploaded_instance,))
            uploaded_coordinate = project_feature_table(uploaded_table, pca_result)[0]
            display_name = Path(uploaded_file.name).stem
            if display_name in set(instance_data["name"]):
                display_name = f"{display_name} (uploaded)"
            uploaded_values = uploaded_table.as_rows()[0]
            uploaded_values.pop("source")
            uploaded_row = {
                "name": display_name,
                "group": "uploaded",
                "path": "In-memory upload",
                **uploaded_values,
                "pc1": uploaded_coordinate[0],
                "pc2": uploaded_coordinate[1],
            }
            instance_data = pd.concat(
                (instance_data, pd.DataFrame((uploaded_row,))),
                ignore_index=True,
            )
            st.sidebar.success(
                "Valid instance projected with the existing reference PCA."
            )
            st.sidebar.caption(
                f"PC1 = {uploaded_coordinate[0]:.3f}, "
                f"PC2 = {uploaded_coordinate[1]:.3f}. "
                "The PCA axes were not re-fitted."
            )
    except (UnicodeDecodeError, OSError, ValueError) as error:
        st.sidebar.error(f"Upload could not be analysed: {error}")

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
metric_1.metric("Reference set", len(sources))
metric_2.metric("Displayed points", len(instance_data))
metric_3.metric("Catalog features", len(feature_table.feature_names))
metric_4.metric(
    "2D variance retained",
    f"{pca_result.total_explained_variance_ratio:.1%}",
)

(
    space_tab,
    compare_tab,
    details_tab,
    interpretation_tab,
    validation_tab,
    performance_tab,
) = st.tabs(
    (
        "Instance space",
        "Compare instances",
        "Instance details",
        "Interpretation",
        "Scientific validation",
        "Algorithm performance",
    )
)

with space_tab:
    st.subheader("2D PCA instance space")
    st.caption(
        "Each point is one validated instance. Distance means similarity under "
        "the selected and standardized characteristics—not algorithm performance."
    )
    control_1, control_2 = st.columns((3, 1))
    with control_1:
        selected_groups = st.multiselect(
            "Visible instance types",
            options=instance_data["group"].drop_duplicates().tolist(),
            default=instance_data["group"].drop_duplicates().tolist(),
        )
    with control_2:
        show_labels = st.checkbox("Show point labels", value=False)

    plot_data = instance_data.loc[instance_data["group"].isin(selected_groups)]
    figure = px.scatter(
        plot_data,
        x="pc1",
        y="pc2",
        color="group",
        symbol="group",
        text="name" if show_labels else None,
        hover_name="name",
        hover_data={
            "group": True,
            "num_junctions": ":,.0f",
            "num_streets": ":,.0f",
            "num_vehicles": ":,.0f",
            "mandatory_service_fraction": ":.3f",
            "mandatory_time_pressure": ":.3f",
            "pc1": ":.3f",
            "pc2": ":.3f",
        },
        color_discrete_map={
            "synthetic": "#f59e0b",
            "real": "#2563eb",
            "uploaded": "#7c3aed",
        },
        symbol_map={
            "synthetic": "circle",
            "real": "diamond",
            "uploaded": "star",
        },
        labels={"group": "Instance type"},
    )
    figure.update_traces(
        marker={"size": 13, "line": {"width": 1, "color": "white"}},
        textposition="top center",
    )
    figure.update_layout(
        height=620,
        legend_title_text="Instance type",
        xaxis_title=(
            f"PC1 ({pca_result.explained_variance_ratio[0]:.1%} variance)"
        ),
        yaxis_title=(
            f"PC2 ({pca_result.explained_variance_ratio[1]:.1%} variance)"
        ),
    )
    figure.add_hline(y=0, line_width=1, line_dash="dot", line_color="#94a3b8")
    figure.add_vline(x=0, line_width=1, line_dash="dot", line_color="#94a3b8")
    st.plotly_chart(figure, width="stretch")

with compare_tab:
    st.subheader("Instance comparison")
    default_names = instance_data["name"].head(5).tolist()
    selected_names = st.multiselect(
        "Instances",
        options=instance_data["name"].tolist(),
        default=default_names,
    )
    display_columns = [
        "name",
        "group",
        "num_junctions",
        "num_streets",
        "num_vehicles",
        "mandatory_service_fraction",
        "bidirectional_street_fraction",
        "mandatory_length_per_vehicle",
        "mean_mandatory_fleet_coverage",
        "mandatory_time_pressure",
        "max_mandatory_round_trip_ratio",
        "pc1",
        "pc2",
    ]
    comparison = instance_data.loc[
        instance_data["name"].isin(selected_names), display_columns
    ]
    st.dataframe(comparison, hide_index=True, width="stretch")
    st.download_button(
        "Download full feature table (CSV)",
        data=instance_data.drop(columns=["path"]).to_csv(index=False),
        file_name="instancelab_features.csv",
        mime="text/csv",
    )

with details_tab:
    st.subheader("Inspect one instance")
    selected_instance = st.selectbox("Instance", instance_data["name"].tolist())
    selected_row = instance_data.loc[
        instance_data["name"] == selected_instance
    ].iloc[0]
    detail_1, detail_2, detail_3, detail_4 = st.columns(4)
    detail_1.metric("Junctions", f"{selected_row['num_junctions']:,.0f}")
    detail_2.metric("Streets", f"{selected_row['num_streets']:,.0f}")
    detail_3.metric("Vehicles", f"{selected_row['num_vehicles']:,.0f}")
    detail_4.metric(
        "Mandatory service",
        f"{selected_row['mandatory_service_fraction']:.1%}",
    )
    st.caption(
        f"PCA position: PC1 = {selected_row['pc1']:.3f}, "
        f"PC2 = {selected_row['pc2']:.3f}"
    )
    feature_details = pd.DataFrame(
        {
            "group": [definition.group for definition in FEATURE_DEFINITIONS],
            "feature": [definition.name for definition in FEATURE_DEFINITIONS],
            "value": [selected_row[definition.name] for definition in FEATURE_DEFINITIONS],
            "meaning": [definition.description for definition in FEATURE_DEFINITIONS],
        }
    )
    st.dataframe(feature_details, hide_index=True, width="stretch")

with interpretation_tab:
    st.subheader("What shapes PC1 and PC2?")
    st.caption(
        "Loadings show contribution and direction. Positive does not mean good, "
        "and negative does not mean bad."
    )
    loading_table = pd.DataFrame(pca_result.loading_rows())
    long_loadings = loading_table.melt(
        id_vars="feature",
        value_vars=("pc1_loading", "pc2_loading"),
        var_name="component",
        value_name="loading",
    )
    loading_figure = px.bar(
        long_loadings,
        x="loading",
        y="feature",
        color="component",
        barmode="group",
        orientation="h",
        color_discrete_map={
            "pc1_loading": "#2563eb",
            "pc2_loading": "#f59e0b",
        },
    )
    loading_figure.update_layout(height=560, yaxis_title=None, legend_title_text="Axis")
    st.plotly_chart(loading_figure, width="stretch")

    st.subheader("Selected PCA inputs")
    st.dataframe(
        pd.DataFrame(
            {
                "feature": [feature.name for feature in DEFAULT_PCA_FEATURES],
                "transformation": [
                    feature.transformation for feature in DEFAULT_PCA_FEATURES
                ],
                "reason": [feature.rationale for feature in DEFAULT_PCA_FEATURES],
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.warning(
        f"This is exploratory unsupervised PCA on a small {len(sources)}-instance "
        "reference set. It is not an algorithm footprint or performance predictor."
    )
    with st.expander("Research basis and current scope"):
        st.markdown(
            """
            Full Instance Space Analysis relates measurable instance features to
            algorithm performance and can construct regions of good performance
            called *algorithm footprints*. InstanceLab implements validated
            characteristics, comparison, an unsupervised 2D PCA projection,
            sensitivity diagnostics and a separate descriptive overlay of the
            currently committed algorithm scores.

            This deliberate boundary follows the professor's references:
            [Gurobi stress-testing webinar](https://www.gurobi.com/resources/webinar-events/stress-testing-algorithms-kate-smith-miles-replay/),
            [InstanceSpace toolkit](https://github.com/andremun/InstanceSpace),
            [MATILDA](https://matilda.unimelb.edu.au/) and
            [OPTIMA](https://optima.org.au/instance/).
            Algorithm footprints and performance prediction remain deferred until
            published results cover more diverse instances and more algorithms.
            """
        )

with validation_tab:
    st.subheader("Scientific validation diagnostics")
    st.caption(
        "These checks measure redundancy, instance extremeness and sensitivity "
        "of the exploratory 2D PCA. They are evidence for interpretation, not a "
        "claim that a small reference set is conclusive."
    )

    validation_1, validation_2, validation_3, validation_4 = st.columns(4)
    validation_1.metric(
        "Maximum |correlation|",
        f"{validation_report.maximum_absolute_correlation:.3f}",
    )
    validation_2.metric(
        f"Pairs above {validation_report.correlation_threshold:.2f}",
        len(validation_report.high_correlations),
    )
    validation_3.metric(
        "Mean LOO similarity",
        f"{validation_report.mean_subspace_similarity:.3f}",
    )
    validation_4.metric(
        "Minimum LOO similarity",
        f"{validation_report.minimum_subspace_similarity:.3f}",
    )

    st.subheader("Selected-feature correlation")
    st.caption(
        "Pearson correlation is computed after the documented transformations. "
        "Large absolute values identify possible double-weighting, not causation."
    )
    correlation_frame = pd.DataFrame(
        validation_report.correlation_matrix,
        index=validation_report.feature_names,
        columns=validation_report.feature_names,
    )
    correlation_figure = px.imshow(
        correlation_frame,
        zmin=-1,
        zmax=1,
        color_continuous_scale="RdBu_r",
        text_auto=".2f",
        aspect="auto",
        labels={"color": "Pearson r"},
    )
    correlation_figure.update_layout(height=650)
    st.plotly_chart(correlation_figure, width="stretch")

    correlation_pairs_frame = pd.DataFrame(
        {
            "feature_1": [
                pair.left for pair in validation_report.high_correlations
            ],
            "feature_2": [
                pair.right for pair in validation_report.high_correlations
            ],
            "pearson_r": [
                pair.correlation for pair in validation_report.high_correlations
            ],
        }
    )
    if validation_report.high_correlations:
        st.dataframe(
            correlation_pairs_frame,
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(
            "No selected PCA feature pair reaches the configured absolute "
            f"correlation threshold of {validation_report.correlation_threshold:.2f}."
        )

    source_names = {
        source_value: source.name
        for source_value, source in zip(feature_table.sources, sources, strict=True)
    }
    extremeness_frame = pd.DataFrame(
        {
            "instance": [
                source_names[row.source] for row in validation_report.extremeness
            ],
            "rms_z_score": [
                row.rms_z_score for row in validation_report.extremeness
            ],
            "largest_abs_z": [
                row.max_abs_z_score for row in validation_report.extremeness
            ],
            "driving_feature": [
                row.dominant_feature for row in validation_report.extremeness
            ],
            "signed_z": [
                row.dominant_z_score for row in validation_report.extremeness
            ],
        }
    )
    stability_frame = pd.DataFrame(
        {
            "omitted_instance": [
                source_names[fold.omitted_source]
                for fold in validation_report.stability_folds
            ],
            "subspace_similarity": [
                fold.subspace_similarity
                for fold in validation_report.stability_folds
            ],
            "variance_retained": [
                fold.variance_retained for fold in validation_report.stability_folds
            ],
        }
    ).sort_values("subspace_similarity")
    left_column, right_column = st.columns(2)
    with left_column:
        st.subheader("Most extreme reference rows")
        st.caption(
            f"RMS z-score summarizes distance across the {len(DEFAULT_PCA_FEATURES)} standardized inputs. "
            "A high value is a review signal, not proof of an invalid outlier."
        )
        st.dataframe(
            extremeness_frame.round(4),
            hide_index=True,
            width="stretch",
        )

    with right_column:
        st.subheader("Leave-one-out PCA sensitivity")
        st.caption(
            "Each row re-fits PCA after omitting that instance. Subspace similarity "
            "is sign- and rotation-invariant; 1.0 means unchanged 2D axes."
        )
        st.dataframe(
            stability_frame.round(4),
            hide_index=True,
            width="stretch",
        )

    retained_low, retained_high = validation_report.variance_retained_range
    st.info(
        "Across leave-one-out fits, the 2D explained variance ranges from "
        f"{retained_low:.1%} to {retained_high:.1%}. Interpret all diagnostics "
        "together with the small reference-set limitation."
    )

    st.subheader("Reproducible exports")
    st.caption(
        "Exports contain reference-instance names and scientific results, but no "
        "local filesystem paths. Uploaded points are intentionally excluded from "
        "the fitted reference report."
    )
    export_1, export_2, export_3, export_4, export_5 = st.columns(5)
    with export_1:
        st.download_button(
            "Full report (JSON)",
            data=json.dumps(
                reproducibility_report,
                indent=2,
                sort_keys=True,
            ),
            file_name="instancelab_analysis_report.json",
            mime="application/json",
            width="stretch",
        )
    with export_2:
        st.download_button(
            "PCA coordinates (CSV)",
            data=instance_data.iloc[: len(sources)][
                ["name", "group", "pc1", "pc2"]
            ].to_csv(index=False),
            file_name="instancelab_pca_coordinates.csv",
            mime="text/csv",
            width="stretch",
        )
    with export_3:
        st.download_button(
            "Extremeness (CSV)",
            data=extremeness_frame.to_csv(index=False),
            file_name="instancelab_extremeness.csv",
            mime="text/csv",
            width="stretch",
        )
    with export_4:
        st.download_button(
            "LOO stability (CSV)",
            data=stability_frame.to_csv(index=False),
            file_name="instancelab_loo_stability.csv",
            mime="text/csv",
            width="stretch",
        )
    with export_5:
        st.download_button(
            "Academic summary (MD)",
            data=academic_summary,
            file_name="instancelab_academic_summary.md",
            mime="text/markdown",
            width="stretch",
        )

with performance_tab:
    st.subheader("Algorithm score analysis")
    st.caption(
        "Stored solutions are parsed, validated and re-scored in memory. This "
        "section describes score relationships; it does not infer algorithm "
        "footprints or predict future performance."
    )

    if unbenchmarked_instances:
        st.info(
            f"{len(unbenchmarked_instances)} instance(s) have no published algorithm "
            "results yet and are shown in the instance space only: "
            + ", ".join(unbenchmarked_instances)
        )

    if performance_failures:
        incomplete_algorithms = sorted(
            {failure.algorithm for failure in performance_failures}
        )
        st.warning(
            f"{len(incomplete_algorithms)} discovered algorithm result set(s) "
            "were excluded because they are incomplete or invalid."
        )
        with st.expander("Unavailable algorithm results"):
            for failure in performance_failures:
                st.write(
                    f"**{failure.instance_name} / {failure.algorithm}:** "
                    f"{failure.reason}"
                )

    if performance_analysis is None:
        st.info(
            "A complete result matrix for at least two algorithms is required. "
            f"Current status: {performance_error or 'no comparable results found'}."
        )
    else:
        score_frame = pd.DataFrame(performance_analysis.score_rows())
        algorithms = list(performance_analysis.algorithms)
        score_values = score_frame[algorithms]
        score_frame["winner"] = score_values.apply(
            lambda row: ", ".join(
                algorithm
                for algorithm in algorithms
                if abs(row[algorithm] - row.max()) <= 1e-12
            ),
            axis=1,
        )

        summary_frame = pd.DataFrame(
            {
                "algorithm": [
                    summary.algorithm for summary in performance_analysis.summaries
                ],
                "mean_score": [
                    summary.mean_score for summary in performance_analysis.summaries
                ],
                "minimum_score": [
                    summary.minimum_score
                    for summary in performance_analysis.summaries
                ],
                "maximum_score": [
                    summary.maximum_score
                    for summary in performance_analysis.summaries
                ],
                "best_count": [
                    summary.best_count for summary in performance_analysis.summaries
                ],
            }
        )
        best_summary = max(
            performance_analysis.summaries,
            key=lambda summary: summary.mean_score,
        )
        performance_1, performance_2, performance_3, performance_4 = st.columns(4)
        performance_1.metric("Algorithms", len(algorithms))
        performance_2.metric("Complete instances", len(score_frame))
        performance_3.metric("Highest mean score", best_summary.algorithm)
        timed_pairs = sum(summary.timed_count for summary in performance_analysis.summaries)
        performance_4.metric(
            "Timed published pairs",
            f"{timed_pairs}/{len(algorithms) * len(score_frame)}",
        )
        st.dataframe(summary_frame.round(4), hide_index=True, width="stretch")

        if best_summary.best_count == len(score_frame):
            st.warning(
                f"{best_summary.algorithm} has the best stored score on all "
                f"{len(score_frame)} reference instances. This supports descriptive "
                "comparison, but there is no contrasting winner region from which "
                "to infer algorithm footprints."
            )

        st.subheader("Performance over the PCA feature space")
        selected_algorithm = st.selectbox(
            "Score shown by colour",
            algorithms,
            key="performance_algorithm",
        )
        performance_plot = (
            instance_data.iloc[: len(sources)][["name", "group", "pc1", "pc2"]]
            .merge(score_frame, left_on="name", right_on="instance", how="inner")
        )
        score_figure = px.scatter(
            performance_plot,
            x="pc1",
            y="pc2",
            color=selected_algorithm,
            symbol="group",
            hover_name="name",
            hover_data={
                "group": True,
                selected_algorithm: ":.4f",
                "pc1": ":.3f",
                "pc2": ":.3f",
            },
            color_continuous_scale="Viridis",
            labels={selected_algorithm: "Official score"},
        )
        score_figure.update_traces(
            marker={"size": 14, "line": {"width": 1, "color": "white"}}
        )
        score_figure.update_layout(
            height=600,
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "left",
                "x": 0.0,
                "title_text": "Instance group",
            },
            coloraxis_colorbar={
                "title": "Official score",
                "x": 1.02,
                "len": 0.75,
            },
            margin={"r": 120},
        )
        score_figure.add_hline(
            y=0,
            line_width=1,
            line_dash="dot",
            line_color="#94a3b8",
        )
        score_figure.add_vline(
            x=0,
            line_width=1,
            line_dash="dot",
            line_color="#94a3b8",
        )
        st.plotly_chart(score_figure, width="stretch")

        if len(algorithms) == 2:
            gap_name = f"{algorithms[0]}_minus_{algorithms[1]}"
            score_frame[gap_name] = (
                score_frame[algorithms[0]] - score_frame[algorithms[1]]
            )
        st.subheader("Scores by instance")
        st.dataframe(score_frame.round(4), hide_index=True, width="stretch")

        correlation_frame = pd.DataFrame(
            {
                "feature": [
                    row.feature for row in performance_analysis.correlations
                    if row.pearson_r is not None
                ],
                "algorithm": [
                    row.algorithm for row in performance_analysis.correlations
                    if row.pearson_r is not None
                ],
                "pearson_r": [
                    row.pearson_r for row in performance_analysis.correlations
                    if row.pearson_r is not None
                ],
            }
        )
        if not correlation_frame.empty:
            correlation_frame["absolute_r"] = correlation_frame["pearson_r"].abs()
            correlation_frame = correlation_frame.sort_values(
                "absolute_r",
                ascending=False,
            )
            st.subheader("Feature-score relationships")
            st.caption(
                "Pearson correlations are descriptive associations over only "
                f"{len(score_frame)} instances. The synthetic/real group split may drive part of an "
                "association; these values do not establish causation or predictive "
                "accuracy."
            )
            correlation_figure = px.bar(
                correlation_frame,
                x="pearson_r",
                y="feature",
                color="algorithm",
                barmode="group",
                orientation="h",
            )
            correlation_figure.update_layout(height=620, yaxis_title=None)
            st.plotly_chart(correlation_figure, width="stretch")
            st.dataframe(
                correlation_frame.drop(columns="absolute_r").round(4),
                hide_index=True,
                width="stretch",
            )

        st.download_button(
            "Download algorithm scores (CSV)",
            data=score_frame.to_csv(index=False),
            file_name="instancelab_algorithm_scores.csv",
            mime="text/csv",
        )

        st.subheader("Execution time")
        st.caption(
            "Published solutions carry no timings. `python -m instancelab.timing` "
            "re-runs only the published (instance, algorithm) pairs and times the "
            "algorithm call. A time is shown only when the re-run reproduced the "
            "published score, so each time belongs to the scored solution. "
            "Algorithms without published results are never executed."
        )
        if timing_error:
            st.error(f"Execution-time file could not be read: {timing_error}")
        if not performance_analysis.execution_times_available:
            st.info(
                "No execution times are available yet. Run "
                "`python -m instancelab.timing --shared-repo <path>` to measure "
                "the published pairs."
            )
        else:
            time_frame = pd.DataFrame(performance_analysis.time_rows())
            time_summary = pd.DataFrame(
                {
                    "algorithm": [s.algorithm for s in performance_analysis.summaries],
                    "timed_instances": [
                        s.timed_count for s in performance_analysis.summaries
                    ],
                    "median_seconds": [
                        s.median_seconds for s in performance_analysis.summaries
                    ],
                    "mean_seconds": [
                        s.mean_seconds for s in performance_analysis.summaries
                    ],
                    "maximum_seconds": [
                        s.maximum_seconds for s in performance_analysis.summaries
                    ],
                }
            )
            st.dataframe(time_summary.round(4), hide_index=True, width="stretch")
            long_times = time_frame.melt(
                id_vars="instance",
                var_name="algorithm",
                value_name="seconds",
            ).dropna()
            long_times = long_times.merge(
                instance_data[["name", "group", "num_streets"]],
                left_on="instance",
                right_on="name",
                how="left",
            )
            time_figure = px.scatter(
                long_times,
                x="num_streets",
                y="seconds",
                color="algorithm",
                symbol="group",
                hover_name="instance",
                log_x=True,
                log_y=True,
                labels={"num_streets": "Streets (M)", "seconds": "Seconds"},
            )
            time_figure.update_traces(marker={"size": 12})
            time_figure.update_layout(height=520)
            st.plotly_chart(time_figure, width="stretch")
            st.dataframe(time_frame.round(4), hide_index=True, width="stretch")

            time_correlations = pd.DataFrame(
                {
                    "feature": [r.feature for r in performance_analysis.time_correlations],
                    "algorithm": [
                        r.algorithm for r in performance_analysis.time_correlations
                    ],
                    "pearson_r_log10_seconds": [
                        r.pearson_r for r in performance_analysis.time_correlations
                    ],
                    "timed_instances": [
                        r.timed_instances for r in performance_analysis.time_correlations
                    ],
                }
            ).dropna(subset=["pearson_r_log10_seconds"])
            if not time_correlations.empty:
                st.subheader("Feature-time relationships")
                st.caption(
                    "Pearson r between each standardized PCA input and log10(seconds). "
                    "Descriptive only; one run per pair on one machine."
                )
                st.dataframe(
                    time_correlations.sort_values(
                        "pearson_r_log10_seconds", key=abs, ascending=False
                    ).round(4),
                    hide_index=True,
                    width="stretch",
                )
            st.download_button(
                "Download execution times (CSV)",
                data=time_frame.to_csv(index=False),
                file_name="instancelab_execution_times.csv",
                mime="text/csv",
            )

        outdated_keys = {(r.instance, r.algorithm) for r in outdated_timings}
        unreproduced = [
            record for record in timing_records
            if record.status != "ok" or not record.score_matches
            or (record.instance, record.algorithm) in outdated_keys
        ]
        if unreproduced:
            with st.expander(
                f"{len(unreproduced)} timed pair(s) without a reportable time"
            ):
                st.caption(
                    "A differing re-run score means the published solution was "
                    "produced by an earlier version of the algorithm code. A pair "
                    "whose published solution changed after timing is listed until "
                    "`python -m instancelab.timing --resume` measures it again."
                )
                st.dataframe(
                    pd.DataFrame(
                        {
                            "instance": [r.instance for r in unreproduced],
                            "algorithm": [r.algorithm for r in unreproduced],
                            "status": [r.status for r in unreproduced],
                            "published_score": [r.published_score for r in unreproduced],
                            "re_run_score": [r.run_score for r in unreproduced],
                            "re_run_seconds": [r.seconds for r in unreproduced],
                            "reason": [
                                "published solution changed after timing"
                                if (r.instance, r.algorithm) in outdated_keys
                                else r.reason
                                for r in unreproduced
                            ],
                        }
                    ).round(4),
                    hide_index=True,
                    width="stretch",
                )
