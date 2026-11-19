"""Read-only adapter for the shared class repository layout."""

from dataclasses import dataclass
from pathlib import Path

from ..clipp import read_instance
from ..model import Instance
from ..validation import validate_instance


class SharedRepositoryError(ValueError):
    """Raised when a shared-repository instance collection cannot be found."""


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


def discover_shared_instances(root: str | Path) -> tuple[InstanceSource, ...]:
    """Discover every current and future instance following class conventions."""

    repository = Path(root)
    input_root = repository / "data" / "input"
    if not input_root.is_dir():
        raise SharedRepositoryError(
            f"Shared instance directory not found: {input_root}"
        )

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
) -> tuple[tuple[InstanceSource, Instance], ...]:
    """Load discovered files without writing to the shared repository."""

    return tuple(
        (source, read_instance(source.path))
        for source in discover_shared_instances(root)
    )


def shared_repository_fingerprint(
    root: str | Path,
) -> tuple[tuple[str, int, int], ...]:
    """Return a cache key that changes with recognized inputs or results."""

    repository = Path(root)
    input_paths = [source.path for source in discover_shared_instances(repository)]
    result_paths = sorted(
        (repository / "data" / "output").glob("*/*_solution.txt")
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


def scan_shared_instances(root: str | Path) -> SharedRepositoryScan:
    """Load and validate each discovered file without changing the repository."""

    return scan_instance_sources(discover_shared_instances(root))
