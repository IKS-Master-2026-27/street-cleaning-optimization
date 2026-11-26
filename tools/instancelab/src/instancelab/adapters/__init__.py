"""Integration boundaries for external repositories and future data sources."""

from .shared_repository import (
    DATASET_LABELS,
    DATASETS,
    InstanceLoadFailure,
    InstanceSource,
    SharedRepositoryScan,
    SharedRepositoryError,
    discover_shared_instances,
    find_shared_repository_root,
    load_shared_instances,
    resolve_dataset,
    results_root,
    scan_instance_sources,
    scan_shared_instances,
    shared_repository_fingerprint,
    solution_path,
)
from .shared_results import (
    AlgorithmResultFailure,
    SharedResultScan,
    SolutionResultError,
    scan_shared_algorithm_results,
    score_solution_file,
)

__all__ = [
    "DATASETS",
    "DATASET_LABELS",
    "AlgorithmResultFailure",
    "InstanceLoadFailure",
    "InstanceSource",
    "SharedRepositoryScan",
    "SharedResultScan",
    "SharedRepositoryError",
    "SolutionResultError",
    "discover_shared_instances",
    "find_shared_repository_root",
    "load_shared_instances",
    "resolve_dataset",
    "results_root",
    "scan_instance_sources",
    "scan_shared_instances",
    "scan_shared_algorithm_results",
    "score_solution_file",
    "shared_repository_fingerprint",
    "solution_path",
]
