"""Standalone reader for repository and official CLIPP text layouts."""

from pathlib import Path

from .model import Instance, Street


class InstanceParseError(ValueError):
    """Raised when an input cannot be structurally parsed as a CLIPP instance."""


def _parse_int(value: str, *, line: int, field: str, source: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise InstanceParseError(
            f"{source}:{line}: {field} must be an integer, got {value!r}"
        ) from exc


def _parse_float(value: str, *, line: int, field: str, source: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise InstanceParseError(
            f"{source}:{line}: {field} must be numeric, got {value!r}"
        ) from exc


def parse_instance(text: str, *, source: str = "<memory>") -> Instance:
    """Parse CLIPP text without depending on the shared repository.

    Supported layouts are the repository layout and the official layout, which
    inserts ``N`` coordinate rows between the header and street records.
    Structural problems raise :class:`InstanceParseError`; domain rules are
    checked separately by :func:`instancelab.validation.validate_instance`.
    """

    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise InstanceParseError(f"{source}: empty instance")

    header = lines[0].split()
    if len(header) != 6:
        raise InstanceParseError(
            f"{source}:1: expected header 'N M T C S alpha', got {len(header)} fields"
        )

    n = _parse_int(header[0], line=1, field="N", source=source)
    m = _parse_int(header[1], line=1, field="M", source=source)
    time_limit = _parse_int(header[2], line=1, field="T", source=source)
    vehicles = _parse_int(header[3], line=1, field="C", source=source)
    depot = _parse_int(header[4], line=1, field="S", source=source)
    alpha = _parse_float(header[5], line=1, field="alpha", source=source)
    if n < 0 or m < 0 or vehicles < 0:
        raise InstanceParseError(f"{source}:1: N, M and C cannot be negative")

    row = 1
    coordinates: tuple[tuple[float, float], ...] | None = None
    if row < len(lines) and len(lines[row].split()) == 2:
        parsed_coordinates: list[tuple[float, float]] = []
        for offset in range(n):
            line_number = row + offset + 1
            if row + offset >= len(lines):
                raise InstanceParseError(
                    f"{source}:{line_number}: expected coordinate {offset + 1}/{n}"
                )
            fields = lines[row + offset].split()
            if len(fields) != 2:
                raise InstanceParseError(
                    f"{source}:{line_number}: expected two coordinate values"
                )
            parsed_coordinates.append((
                _parse_float(fields[0], line=line_number, field="coordinate x", source=source),
                _parse_float(fields[1], line=line_number, field="coordinate y", source=source),
            ))
        coordinates = tuple(parsed_coordinates)
        row += n

    streets: list[Street] = []
    for street_id in range(m):
        line_number = row + 1
        if row >= len(lines):
            raise InstanceParseError(
                f"{source}:{line_number}: expected street {street_id + 1}/{m}"
            )
        fields = lines[row].split()
        if len(fields) != 7:
            raise InstanceParseError(
                f"{source}:{line_number}: expected 7 street fields, got {len(fields)}"
            )
        streets.append(Street(
            id=street_id,
            start=_parse_int(fields[0], line=line_number, field="street start", source=source),
            end=_parse_int(fields[1], line=line_number, field="street end", source=source),
            direction=_parse_int(fields[2], line=line_number, field="direction", source=source),
            travel_time=_parse_int(fields[3], line=line_number, field="travel time", source=source),
            length=_parse_int(fields[4], line=line_number, field="length", source=source),
            category=fields[5],
            requirement=_parse_int(fields[6], line=line_number, field="requirement", source=source),
        ))
        row += 1

    line_number = row + 1
    if row >= len(lines):
        raise InstanceParseError(
            f"{source}:{line_number}: expected final line with {vehicles} vehicle types"
        )
    vehicle_types = tuple(lines[row].split())
    if len(vehicle_types) != vehicles:
        raise InstanceParseError(
            f"{source}:{line_number}: expected {vehicles} vehicle types, "
            f"got {len(vehicle_types)}"
        )
    row += 1

    unexpected = next((index for index in range(row, len(lines)) if lines[index].strip()), None)
    if unexpected is not None:
        raise InstanceParseError(
            f"{source}:{unexpected + 1}: unexpected content after vehicle types"
        )

    return Instance(
        num_junctions=n,
        num_streets=m,
        time_limit=time_limit,
        num_vehicles=vehicles,
        depot=depot,
        alpha=alpha,
        streets=tuple(streets),
        vehicle_types=vehicle_types,
        coordinates=coordinates,
        source=source,
    )


def read_instance(path: str | Path) -> Instance:
    """Read a UTF-8 CLIPP instance from disk."""

    instance_path = Path(path)
    try:
        text = instance_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstanceParseError(f"{instance_path}: cannot read instance: {exc}") from exc
    return parse_instance(text, source=str(instance_path))
