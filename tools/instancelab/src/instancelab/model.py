"""Canonical, repository-independent representation of a CLIPP instance."""

from dataclasses import dataclass


Coordinate = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Street:
    """One street record exactly as described by the CLIPP input format."""

    id: int
    start: int
    end: int
    direction: int
    travel_time: int
    length: int
    category: str
    requirement: int


@dataclass(frozen=True, slots=True)
class Instance:
    """Canonical instance used by validation and future feature extraction.

    Primitive values are intentionally retained instead of importing models from
    the shared repository. Semantic validation is a separate, explicit step.
    """

    num_junctions: int
    num_streets: int
    time_limit: int
    num_vehicles: int
    depot: int
    alpha: float
    streets: tuple[Street, ...]
    vehicle_types: tuple[str, ...]
    coordinates: tuple[Coordinate, ...] | None = None
    source: str = "<memory>"
