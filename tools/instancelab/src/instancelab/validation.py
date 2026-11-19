"""Structural and semantic validation for canonical instances."""

from dataclasses import dataclass
from math import isfinite, isinf

from .model import Instance
from .routing import DepotDistances, depot_distances


VALID_DIRECTIONS = {1, 2}
VALID_CATEGORIES = {"M", "O", "C"}
VALID_REQUIREMENTS = {10, 20, 30}
VEHICLE_CAPACITIES = {"S": 10, "M": 20, "L": 30}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str


def _mandatory_route_issues(
    instance: Instance,
    distances: DepotDistances | None,
) -> list[ValidationIssue]:
    """Check that every mandatory street fits in one closed depot route.

    A mandatory street is feasible only when some vehicle can drive from the
    depot, traverse it and return within ``T``. This necessary condition runs
    in O((N + M) log N) time and subsumes plain depot reachability.
    """

    n = instance.num_junctions
    if n <= 0 or not 0 <= instance.depot < n:
        return []

    if distances is None:
        distances = depot_distances(instance)
    issues = []
    for street in instance.streets:
        if street.category != "M":
            continue
        if not (0 <= street.start < n and 0 <= street.end < n):
            continue
        if street.direction not in VALID_DIRECTIONS or street.travel_time <= 0:
            continue
        round_trip = distances.round_trip_time(street)
        if isinf(round_trip):
            issues.append(ValidationIssue(
                "mandatory_unreachable",
                f"Street {street.id}: mandatory street cannot be reached from and returned to depot",
            ))
        elif round_trip > instance.time_limit:
            issues.append(ValidationIssue(
                "mandatory_time_infeasible",
                f"Street {street.id}: fastest depot round trip takes {round_trip:g} "
                f"seconds, above T = {instance.time_limit}",
            ))
    return issues


def validate_instance(
    instance: Instance,
    *,
    distances: DepotDistances | None = None,
) -> tuple[ValidationIssue, ...]:
    """Return deterministic structural and semantic errors for an instance.

    The mandatory-route check uses Dijkstra from and to the depot, so it
    remains safe for the largest class instances. Callers that already computed
    ``depot_distances(instance)`` may pass it to avoid repeating the search.
    An empty tuple means the instance is valid.
    """

    issues: list[ValidationIssue] = []

    if instance.num_junctions <= 0:
        issues.append(ValidationIssue("junction_count", "N must be greater than zero"))
    if instance.num_streets < 0:
        issues.append(ValidationIssue("street_count", "M cannot be negative"))
    if instance.num_streets != len(instance.streets):
        issues.append(ValidationIssue(
            "street_count_mismatch",
            f"Header declares {instance.num_streets} streets, parsed {len(instance.streets)}",
        ))
    if instance.time_limit <= 0:
        issues.append(ValidationIssue("time_limit", "T must be greater than zero"))
    if instance.num_vehicles <= 0:
        issues.append(ValidationIssue("vehicle_count", "C must be greater than zero"))
    if instance.num_vehicles != len(instance.vehicle_types):
        issues.append(ValidationIssue(
            "vehicle_count_mismatch",
            f"Header declares {instance.num_vehicles} vehicles, parsed {len(instance.vehicle_types)}",
        ))
    if not 0 <= instance.depot < instance.num_junctions:
        issues.append(ValidationIssue(
            "depot_range",
            f"Depot {instance.depot} is outside junction range [0, {instance.num_junctions})",
        ))
    if not isfinite(instance.alpha) or not 0.0 <= instance.alpha <= 1.0:
        issues.append(ValidationIssue("alpha_range", "alpha must be finite and within [0, 1]"))

    if instance.coordinates is not None:
        if len(instance.coordinates) != instance.num_junctions:
            issues.append(ValidationIssue(
                "coordinate_count_mismatch",
                f"Expected {instance.num_junctions} coordinates, got {len(instance.coordinates)}",
            ))
        for index, coordinate in enumerate(instance.coordinates):
            if len(coordinate) != 2 or not all(isfinite(value) for value in coordinate):
                issues.append(ValidationIssue(
                    "coordinate_value",
                    f"Coordinate {index} must contain two finite values",
                ))

    fleet_capacities = []
    for index, vehicle_type in enumerate(instance.vehicle_types):
        capacity = VEHICLE_CAPACITIES.get(vehicle_type)
        if capacity is None:
            issues.append(ValidationIssue(
                "vehicle_type",
                f"Vehicle {index}: unknown type {vehicle_type!r}; expected S, M or L",
            ))
        else:
            fleet_capacities.append(capacity)
    max_capacity = max(fleet_capacities, default=0)

    for expected_id, street in enumerate(instance.streets):
        prefix = f"Street {street.id}"
        if street.id != expected_id:
            issues.append(ValidationIssue(
                "street_id_sequence",
                f"{prefix}: expected ID {expected_id}",
            ))
        if not 0 <= street.start < instance.num_junctions:
            issues.append(ValidationIssue(
                "street_start_range",
                f"{prefix}: start junction {street.start} is out of range",
            ))
        if not 0 <= street.end < instance.num_junctions:
            issues.append(ValidationIssue(
                "street_end_range",
                f"{prefix}: end junction {street.end} is out of range",
            ))
        if street.direction not in VALID_DIRECTIONS:
            issues.append(ValidationIssue(
                "street_direction",
                f"{prefix}: direction must be 1 or 2",
            ))
        if street.travel_time <= 0:
            issues.append(ValidationIssue(
                "street_time",
                f"{prefix}: travel time must be greater than zero",
            ))
        if street.length < 0:
            issues.append(ValidationIssue(
                "street_length",
                f"{prefix}: length cannot be negative",
            ))
        if street.category not in VALID_CATEGORIES:
            issues.append(ValidationIssue(
                "street_category",
                f"{prefix}: category must be M, O or C",
            ))
            continue
        if street.category == "C":
            if street.length != 0 or street.requirement != 0:
                issues.append(ValidationIssue(
                    "connector_values",
                    f"{prefix}: connector streets must have length 0 and requirement 0",
                ))
        else:
            if street.length <= 0:
                issues.append(ValidationIssue(
                    "service_length",
                    f"{prefix}: mandatory/optional street length must be greater than zero",
                ))
            if street.requirement not in VALID_REQUIREMENTS:
                issues.append(ValidationIssue(
                    "service_requirement",
                    f"{prefix}: cleaning requirement must be 10, 20 or 30",
                ))
            if street.category == "M" and street.requirement > max_capacity:
                issues.append(ValidationIssue(
                    "mandatory_capacity",
                    f"{prefix}: no vehicle can satisfy requirement {street.requirement}",
                ))

    issues.extend(_mandatory_route_issues(instance, distances))
    return tuple(issues)
