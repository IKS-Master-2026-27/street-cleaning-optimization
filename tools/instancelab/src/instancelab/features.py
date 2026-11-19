"""Deterministic, scalable characteristics for validated CLIPP instances."""

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from .model import Instance
from .routing import depot_distances
from .validation import VEHICLE_CAPACITIES, validate_instance


class FeatureExtractionError(ValueError):
    """Raised when characteristics are requested for an invalid instance."""


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """Human-readable metadata for one reproducible instance characteristic."""

    name: str
    group: str
    description: str
    formula: str


FEATURE_DEFINITIONS = (
    FeatureDefinition("num_junctions", "size", "Number of graph junctions.", "N"),
    FeatureDefinition("num_streets", "size", "Number of street records.", "M"),
    FeatureDefinition("num_vehicles", "fleet", "Number of available vehicles.", "C"),
    FeatureDefinition("time_limit", "budget", "Route time limit from the instance header.", "T"),
    FeatureDefinition("alpha", "budget", "Objective trade-off parameter from the instance header.", "alpha"),
    FeatureDefinition(
        "street_to_junction_ratio",
        "graph",
        "Street records per junction; a sparse-graph complexity measure.",
        "M / N",
    ),
    FeatureDefinition(
        "directed_arc_to_junction_ratio",
        "graph",
        "Traversable directed arcs per junction; two-way streets contribute two arcs.",
        "(one_way + 2 * two_way) / N",
    ),
    FeatureDefinition(
        "out_degree_cv",
        "graph",
        "Relative variation of directed out-degree across all junctions.",
        "population_std(out_degree) / mean(out_degree)",
    ),
    FeatureDefinition(
        "connector_street_fraction",
        "service",
        "Fraction of all street records that are connector streets.",
        "count(category=C) / M",
    ),
    FeatureDefinition(
        "mandatory_service_fraction",
        "service",
        "Fraction of serviceable streets that are mandatory.",
        "count(category=M) / count(category in {M, O})",
    ),
    FeatureDefinition(
        "mandatory_length_fraction",
        "service",
        "Fraction of serviceable street length that is mandatory.",
        "sum(length for M) / sum(length for M or O)",
    ),
    FeatureDefinition(
        "bidirectional_street_fraction",
        "graph",
        "Fraction of street records traversable in both directions.",
        "count(direction=2) / M",
    ),
    FeatureDefinition(
        "mean_travel_time",
        "graph",
        "Mean travel time over all street records.",
        "mean(travel_time)",
    ),
    FeatureDefinition(
        "travel_time_cv",
        "graph",
        "Scale-independent variation in street travel times.",
        "population_std(travel_time) / mean(travel_time)",
    ),
    FeatureDefinition(
        "mean_service_length",
        "service",
        "Mean length of mandatory and optional service streets.",
        "mean(length for category in {M, O})",
    ),
    FeatureDefinition(
        "service_length_cv",
        "service",
        "Scale-independent variation in service-street lengths.",
        "population_std(service_length) / mean(service_length)",
    ),
    FeatureDefinition(
        "mean_service_requirement",
        "service",
        "Mean cleaning capability required by service streets.",
        "mean(requirement for category in {M, O})",
    ),
    FeatureDefinition(
        "high_requirement_fraction",
        "service",
        "Fraction of service streets requiring the highest capability level (30).",
        "count(requirement=30) / count(category in {M, O})",
    ),
    FeatureDefinition(
        "mean_vehicle_capacity",
        "fleet",
        "Mean cleaning capability of the fleet (S=10, M=20, L=30).",
        "mean(vehicle_capacity)",
    ),
    FeatureDefinition(
        "large_vehicle_fraction",
        "fleet",
        "Fraction of fleet vehicles with the highest capability level.",
        "count(vehicle_type=L) / C",
    ),
    FeatureDefinition(
        "mandatory_length_per_vehicle",
        "fleet",
        "Mandatory service length allocated per vehicle before routing effects.",
        "sum(length for category=M) / C",
    ),
    FeatureDefinition(
        "mean_mandatory_fleet_coverage",
        "fleet",
        "Mean fraction of vehicles capable of serving each mandatory street.",
        "mean(count(capacity >= requirement) / C for mandatory streets)",
    ),
    FeatureDefinition(
        "mandatory_time_pressure",
        "time",
        "Pure mandatory traversal time relative to the total fleet time budget.",
        "sum(travel_time for category=M) / (C * T)",
    ),
    FeatureDefinition(
        "service_time_pressure",
        "time",
        "Pure traversal time of all serviceable streets relative to the fleet budget.",
        "sum(travel_time for category in {M, O}) / (C * T)",
    ),
    FeatureDefinition(
        "mean_mandatory_round_trip_ratio",
        "time",
        "Mean fastest depot-street-depot time of mandatory streets, relative to T.",
        "mean(round_trip(s) / T for category=M)",
    ),
    FeatureDefinition(
        "max_mandatory_round_trip_ratio",
        "time",
        "Tightest single mandatory street: its fastest depot round trip relative to T.",
        "max(round_trip(s) / T for category=M)",
    ),
)

FEATURE_NAMES = tuple(definition.name for definition in FEATURE_DEFINITIONS)


@dataclass(frozen=True, slots=True)
class InstanceFeatures:
    """One ordered feature vector plus the source that produced it."""

    source: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(FEATURE_NAMES):
            raise ValueError(
                f"Expected {len(FEATURE_NAMES)} feature values, got {len(self.values)}"
            )

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values, strict=True))

    def as_row(self) -> dict[str, str | float]:
        return {"source": self.source, **self.as_dict()}

    def __getitem__(self, name: str) -> float:
        try:
            index = FEATURE_NAMES.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc
        return self.values[index]


@dataclass(slots=True)
class _Moments:
    """Numerically stable one-pass population moments."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

    def coefficient_of_variation(self) -> float:
        if self.count == 0 or self.mean == 0.0:
            return 0.0
        return sqrt(max(self.m2 / self.count, 0.0)) / self.mean


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def extract_features(instance: Instance) -> InstanceFeatures:
    """Extract a feature vector in O((N + M) log N + C) time and O(N + M) memory.

    The logarithmic factor comes only from the two depot shortest-path searches
    used by the round-trip time features; all other features are one pass.

    Validation is deliberately required here: numerical output from an invalid
    graph could look plausible and contaminate later comparison or PCA results.
    """

    distances = None
    if instance.num_junctions > 0 and 0 <= instance.depot < instance.num_junctions:
        distances = depot_distances(instance)
    issues = validate_instance(instance, distances=distances)
    if issues:
        codes = ", ".join(issue.code for issue in issues)
        raise FeatureExtractionError(
            f"Cannot extract features from invalid instance {instance.source!r}: {codes}"
        )

    travel_time = _Moments()
    service_length = _Moments()
    service_requirement = _Moments()
    out_degree = [0] * instance.num_junctions

    connector_count = 0
    service_count = 0
    mandatory_count = 0
    mandatory_length = 0
    total_service_length = 0
    high_requirement_count = 0
    bidirectional_count = 0
    directed_arc_count = 0
    mandatory_requirement_counts = {10: 0, 20: 0, 30: 0}
    mandatory_travel_time = 0
    service_travel_time = 0
    round_trip_sum = 0.0
    round_trip_max = 0.0

    for street in instance.streets:
        travel_time.add(street.travel_time)
        out_degree[street.start] += 1
        directed_arc_count += 1
        if street.direction == 2:
            out_degree[street.end] += 1
            directed_arc_count += 1
            bidirectional_count += 1

        if street.category == "C":
            connector_count += 1
            continue

        service_count += 1
        service_travel_time += street.travel_time
        total_service_length += street.length
        service_length.add(street.length)
        service_requirement.add(street.requirement)
        if street.requirement == 30:
            high_requirement_count += 1
        if street.category == "M":
            mandatory_count += 1
            mandatory_length += street.length
            mandatory_requirement_counts[street.requirement] += 1
            mandatory_travel_time += street.travel_time
            round_trip = distances.round_trip_time(street)
            round_trip_sum += round_trip
            round_trip_max = max(round_trip_max, round_trip)

    out_degree_moments = _Moments()
    for degree in out_degree:
        out_degree_moments.add(degree)

    capacities = tuple(VEHICLE_CAPACITIES[kind] for kind in instance.vehicle_types)
    mean_vehicle_capacity = sum(capacities) / len(capacities)
    large_vehicle_fraction = _ratio(capacities.count(30), len(capacities))

    capable_fractions = {
        requirement: sum(capacity >= requirement for capacity in capacities)
        / len(capacities)
        for requirement in mandatory_requirement_counts
    }
    coverage_sum = sum(
        count * capable_fractions[requirement]
        for requirement, count in mandatory_requirement_counts.items()
    )

    fleet_budget = instance.num_vehicles * instance.time_limit
    values = (
        float(instance.num_junctions),
        float(instance.num_streets),
        float(instance.num_vehicles),
        float(instance.time_limit),
        instance.alpha,
        _ratio(instance.num_streets, instance.num_junctions),
        _ratio(directed_arc_count, instance.num_junctions),
        out_degree_moments.coefficient_of_variation(),
        _ratio(connector_count, instance.num_streets),
        _ratio(mandatory_count, service_count),
        _ratio(mandatory_length, total_service_length),
        _ratio(bidirectional_count, instance.num_streets),
        travel_time.mean,
        travel_time.coefficient_of_variation(),
        service_length.mean,
        service_length.coefficient_of_variation(),
        service_requirement.mean,
        _ratio(high_requirement_count, service_count),
        mean_vehicle_capacity,
        large_vehicle_fraction,
        _ratio(mandatory_length, instance.num_vehicles),
        _ratio(coverage_sum, mandatory_count),
        _ratio(mandatory_travel_time, fleet_budget),
        _ratio(service_travel_time, fleet_budget),
        _ratio(round_trip_sum, mandatory_count * instance.time_limit),
        _ratio(round_trip_max, instance.time_limit),
    )
    return InstanceFeatures(source=instance.source, values=values)


def compare_instances(instances: Iterable[Instance]) -> tuple[dict[str, str | float], ...]:
    """Build a dependency-free, stable feature table for multiple instances."""

    return tuple(extract_features(instance).as_row() for instance in instances)
