"""Read-only adapter for the shared class repository layout."""

from dataclasses import dataclass
from pathlib import Path

from ..clipp import read_instance
from ..model import Instance
from ..validation import validate_instance


class SharedRepositoryError(ValueError):
    """Raised when a shared-repository instance collection cannot be found."""


# Instance sets of the shared repository. ``realistic`` (whole cities with a
# workload-scaled fleet and time limit, data/input/realistic_instances) is the
# main comparison; ``legacy`` (5 synthetic + 10 data/input/real_instances) is
# kept as an optional view. ``auto`` picks ``realistic`` when it exists.
DATASETS = ("auto", "realistic", "legacy")
DATASET_LABELS = {
    "realistic": "Realistic instances (data/input/realistic_instances)",
    "legacy": "Old instances (synthetic + data/input/real_instances)",
}


def resolve_dataset(root: str | Path, dataset: str = "auto") -> str:
    """Return ``realistic`` or ``legacy`` for a requested instance set."""

    if dataset not in DATASETS:
        raise SharedRepositoryError(f"Unknown instance set {dataset!r}; use one of {DATASETS}")
    if dataset != "auto":
        return dataset
    realistic = Path(root) / "data" / "input" / "realistic_instances"
    return "realistic" if any(realistic.glob("*/instance.txt")) else "legacy"


def results_root(root: str | Path, dataset: str) -> Path:
    """Folder that holds one sub-folder of solutions per algorithm.

    Realistic solutions live in ``data/output/realistic_instances/<algorithm>/``
    because their file names equal those of ``data/input/real_instances``.
    """

    output = Path(root) / "data" / "output"
    return output / "realistic_instances" if dataset == "realistic" else output


def source_dataset(source: "InstanceSource") -> str:
    return "realistic" if source.group == "realistic" else "legacy"


def solution_file_name(source: "InstanceSource") -> str:
    if source.group in {"real", "realistic"}:
        return f"{source.path.parent.name}_instance_solution.txt"
    return f"{source.name}_solution.txt"


def solution_path(root: str | Path, algorithm: str, source: "InstanceSource") -> Path:
    """Published solution file of one algorithm for one instance."""

    return results_root(root, source_dataset(source)) / algorithm / solution_file_name(source)


@dataclass(frozen=True, slots=True)
class InstanceSource:
    """Display metadata for one discovered CLIPP file."""

    name: str
    group: str
    path: Path


@dataclass(frozen=True, slots=True)
class InstanceLoadFailure:
    """One discovered file that could not enter the validated reference set."""

    source: InstanceSource
    reason: str


@dataclass(frozen=True, slots=True)
class SharedRepositoryScan:
    """Validated instances and explicit failures from one read-only scan."""

    loaded: tuple[tuple[InstanceSource, Instance], ...]
    failures: tuple[InstanceLoadFailure, ...]


def find_shared_repository_root(start: str | Path) -> Path | None:
    """Find the nearest parent containing the shared ``data/input`` layout."""

    candidate = Path(start).resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / "data" / "input").is_dir():
            return directory
    return None


def discover_shared_instances(
    root: str | Path, dataset: str = "auto"
) -> tuple[InstanceSource, ...]:
    """Discover every current and future instance of one instance set."""

    repository = Path(root)
    input_root = repository / "data" / "input"
    if not input_root.is_dir():
        raise SharedRepositoryError(
            f"Shared instance directory not found: {input_root}"
        )

    if resolve_dataset(repository, dataset) == "realistic":
        discovered = tuple(
            InstanceSource(path.parent.name, "realistic", path)
            for path in sorted(
                (input_root / "realistic_instances").glob("*/instance.txt")
            )
        )
        if not discovered:
            raise SharedRepositoryError(
                f"No realistic CLIPP instances discovered under {input_root}"
            )
        return discovered

    synthetic = tuple(
        InstanceSource(path.stem, "synthetic", path)
        for path in sorted(
            (input_root / "syntetic_generated").glob("instance_*.txt")
        )
    )
    real = tuple(
        InstanceSource(path.parent.name, "real", path)
        for path in sorted(
            (input_root / "real_instances").glob("*/instance.txt")
        )
    )
    discovered = (*synthetic, *real)
    if not discovered:
        raise SharedRepositoryError(f"No CLIPP instances discovered under {input_root}")

    names = [source.name for source in discovered]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SharedRepositoryError(f"Duplicate instance display names: {duplicates}")
    return discovered


def scan_instance_sources(
    sources: tuple[InstanceSource, ...],
) -> SharedRepositoryScan:
    """Load and validate explicit sources, reporting failures per file."""

    loaded: list[tuple[InstanceSource, Instance]] = []
    failures: list[InstanceLoadFailure] = []
    for source in sources:
        try:
            instance = read_instance(source.path)
            issues = validate_instance(instance)
            if issues:
                reason = "; ".join(
                    f"{issue.code}: {issue.message}" for issue in issues
                )
                failures.append(InstanceLoadFailure(source, reason))
            else:
                loaded.append((source, instance))
        except (OSError, ValueError) as error:
            reason = str(error)
            source_prefix = f"{source.path}:"
            if reason.startswith(source_prefix):
                reason = reason[len(source_prefix):].lstrip()
            failures.append(InstanceLoadFailure(source, reason))
    return SharedRepositoryScan(tuple(loaded), tuple(failures))


def load_shared_instances(
    root: str | Path,
    dataset: str = "auto",
) -> tuple[tuple[InstanceSource, Instance], ...]:
    """Load discovered files without writing to the shared repository."""

    return tuple(
        (source, read_instance(source.path))
        for source in discover_shared_instances(root, dataset)
    )


def shared_repository_fingerprint(
    root: str | Path,
    dataset: str = "auto",
) -> tuple[tuple[str, int, int], ...]:
    """Return a cache key that changes with recognized inputs or results."""

    repository = Path(root)
    resolved = resolve_dataset(repository, dataset)
    input_paths = [
        source.path for source in discover_shared_instances(repository, resolved)
    ]
    result_paths = sorted(
        results_root(repository, resolved).glob("*/*_solution.txt")
    )
    fingerprint = []
    for path in (*input_paths, *result_paths):
        status = path.stat()
        fingerprint.append(
            (
                path.relative_to(repository).as_posix(),
                status.st_size,
                status.st_mtime_ns,
            )
        )
    return tuple(fingerprint)


def scan_shared_instances(root: str | Path, dataset: str = "auto") -> SharedRepositoryScan:
    """Load and validate each discovered file without changing the repository."""

    return scan_instance_sources(discover_shared_instances(root, dataset))
