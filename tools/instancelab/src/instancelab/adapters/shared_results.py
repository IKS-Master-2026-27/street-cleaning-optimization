"""Read-only scoring adapter for shared-repository solution files."""

from dataclasses import dataclass
from pathlib import Path

from ..model import Instance
from ..performance import AlgorithmResult
from ..validation import VEHICLE_CAPACITIES
from .shared_repository import (
    InstanceSource,
    results_root,
    solution_file_name,
    source_dataset,
)


class SolutionResultError(ValueError):
    """Raised when a stored solution cannot be validated and scored."""


@dataclass(frozen=True, slots=True)
class AlgorithmResultFailure:
    instance_name: str
    algorithm: str
    reason: str


@dataclass(frozen=True, slots=True)
class SharedResultScan:
    results: tuple[AlgorithmResult, ...]
    failures: tuple[AlgorithmResultFailure, ...]
    discovered_algorithms: tuple[str, ...]
    complete_algorithms: tuple[str, ...]
    benchmarked_instances: tuple[str, ...] = ()
    unbenchmarked_instances: tuple[str, ...] = ()


def _solution_name(source: InstanceSource) -> str:
    return solution_file_name(source)


def score_solution_file(
    instance: Instance,
    path: str | Path,
    *,
    instance_name: str,
    algorithm: str,
) -> AlgorithmResult:
    """Validate and score one stored solution without importing shared code."""

    solution_path = Path(path)
    try:
        lines = solution_path.read_text(encoding="utf-8").split("\n")
    except OSError as error:
        raise SolutionResultError(f"cannot read solution: {error}") from error

    try:
        route_count = int(lines[0])
    except (IndexError, ValueError) as error:
        raise SolutionResultError("solution must start with an integer route count") from error
    if route_count != instance.num_vehicles:
        raise SolutionResultError(
            f"expected {instance.num_vehicles} routes, got {route_count}"
        )

    streets = {street.id: street for street in instance.streets}
    edge: dict[tuple[int, int], int] = {}
    for street in instance.streets:
        edge[(street.start, street.end)] = street.id
        if street.direction == 2:
            edge[(street.end, street.start)] = street.id

    cleaned: set[int] = set()
    waste = 0.0
    row = 1
    for vehicle_index in range(route_count):
        if row + 2 >= len(lines):
            raise SolutionResultError(f"route {vehicle_index}: incomplete record")
        try:
            declared_steps = int(lines[row])
            nodes = [int(value) for value in lines[row + 1].split()]
            cleaned_ids = [int(value) for value in lines[row + 2].split()]
        except ValueError as error:
            raise SolutionResultError(
                f"route {vehicle_index}: expected integer fields"
            ) from error
        row += 3

        if len(nodes) != declared_steps + 1:
            raise SolutionResultError(
                f"route {vehicle_index}: expected {declared_steps + 1} nodes, "
                f"got {len(nodes)}"
            )
        if not nodes or nodes[0] != instance.depot or nodes[-1] != instance.depot:
            raise SolutionResultError(
                f"route {vehicle_index}: must start and end at depot"
            )

        traversed = []
        for start, end in zip(nodes, nodes[1:]):
            street_id = edge.get((start, end))
            if street_id is None:
                raise SolutionResultError(
                    f"route {vehicle_index}: illegal move {start}->{end}"
                )
            traversed.append(street_id)
        route_time = sum(streets[street_id].travel_time for street_id in traversed)
        if route_time > instance.time_limit:
            raise SolutionResultError(
                f"route {vehicle_index}: time {route_time} exceeds {instance.time_limit}"
            )

        traversed_set = set(traversed)
        capacity = VEHICLE_CAPACITIES[instance.vehicle_types[vehicle_index]]
        for street_id in cleaned_ids:
            street = streets.get(street_id)
            if street is None:
                raise SolutionResultError(
                    f"route {vehicle_index}: unknown cleaned street {street_id}"
                )
            if street_id not in traversed_set:
                raise SolutionResultError(
                    f"route {vehicle_index}: cleaned untraversed street {street_id}"
                )
            if street.category == "C":
                raise SolutionResultError(
                    f"route {vehicle_index}: connector street {street_id} cannot be cleaned"
                )
            if capacity < street.requirement:
                raise SolutionResultError(
                    f"route {vehicle_index}: insufficient capacity for street {street_id}"
                )
            cleaned.add(street_id)
            waste += (capacity - street.requirement) * street.length / 1000

    unexpected = [line for line in lines[row:] if line.strip()]
    if unexpected:
        raise SolutionResultError("unexpected content after the final route")

    missing = [
        street.id
        for street in instance.streets
        if street.category == "M" and street.id not in cleaned
    ]
    if missing:
        raise SolutionResultError(
            f"{len(missing)} mandatory streets are not cleaned"
        )

    eligible = [street for street in instance.streets if street.category in {"M", "O"}]
    cleaned_length = sum(streets[street_id].length for street_id in cleaned)
    maximum_length = sum(street.length for street in eligible)
    maximum_waste = sum(
        (30 - street.requirement) * street.length / 1000 for street in eligible
    )
    coverage = cleaned_length / maximum_length if maximum_length else 0.0
    efficiency = 1.0 - waste / maximum_waste if maximum_waste else 1.0
    score = instance.alpha * coverage + (1.0 - instance.alpha) * efficiency
    return AlgorithmResult(
        instance_name=instance_name,
        algorithm=algorithm,
        score=score,
        coverage=coverage,
        efficiency=efficiency,
    )


def scan_shared_algorithm_results(
    root: str | Path,
    loaded_instances: tuple[tuple[InstanceSource, Instance], ...],
    algorithms: tuple[str, ...] | None = None,
) -> SharedResultScan:
    """Discover and read complete stored result sets without writing files.

    An instance is *benchmarked* when at least one discovered algorithm has
    published a solution file for it. A newly added instance without any
    published solution is reported in ``unbenchmarked_instances`` and does not
    block the comparison of the other instances.

    A discovered algorithm enters ``results`` only when every benchmarked
    instance has one valid solution. Partial or invalid sets are reported
    through ``failures`` so they cannot silently bias a comparison.
    """

    repository = Path(root)
    realistic = any(
        source_dataset(source) == "realistic" for source, _ in loaded_instances
    )
    output_root = results_root(repository, "realistic" if realistic else "legacy")
    if algorithms is None:
        if not output_root.is_dir():
            discovered_algorithms = ()
        else:
            discovered_algorithms = tuple(
                sorted(
                    directory.name
                    for directory in output_root.iterdir()
                    if directory.is_dir()
                    and any(directory.glob("*_solution.txt"))
                )
            )
    else:
        discovered_algorithms = tuple(sorted(set(algorithms)))

    benchmarked = tuple(
        (source, instance)
        for source, instance in loaded_instances
        if any(
            (output_root / algorithm / _solution_name(source)).is_file()
            for algorithm in discovered_algorithms
        )
    )
    benchmarked_names = {source.name for source, _ in benchmarked}

    results = []
    failures = []
    complete_algorithms = []
    for algorithm in discovered_algorithms:
        algorithm_results = []
        algorithm_failures = []
        for source, instance in benchmarked:
            path = output_root / algorithm / _solution_name(source)
            if not path.is_file():
                algorithm_failures.append(
                    AlgorithmResultFailure(source.name, algorithm, "solution file missing")
                )
                continue
            try:
                algorithm_results.append(
                    score_solution_file(
                        instance,
                        path,
                        instance_name=source.name,
                        algorithm=algorithm,
                    )
                )
            except (OSError, ValueError) as error:
                algorithm_failures.append(
                    AlgorithmResultFailure(source.name, algorithm, str(error))
                )
        failures.extend(algorithm_failures)
        if (
            benchmarked
            and not algorithm_failures
            and len(algorithm_results) == len(benchmarked)
        ):
            results.extend(algorithm_results)
            complete_algorithms.append(algorithm)

    return SharedResultScan(
        tuple(results),
        tuple(failures),
        discovered_algorithms,
        tuple(complete_algorithms),
        tuple(source.name for source, _ in loaded_instances if source.name in benchmarked_names),
        tuple(source.name for source, _ in loaded_instances if source.name not in benchmarked_names),
    )
