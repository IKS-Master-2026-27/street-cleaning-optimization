"""
Solution validator for CLIPP.
"""

__all__ = ["validate_solution"]


def validate_solution(
    instance: dict,
    routes: list[list[int]],
    clean_per_vehicle: list[list[int]],
) -> tuple[bool, list[str]]:
    """
    Validate a solution against all problem rules.

    Checks performed
    ----------------
    * Routes start and end at the depot.
    * Every consecutive pair of junctions in a route corresponds to a valid arc.
    * Route time does not exceed *T*.
    * Cleaned streets were actually traversed.
    * Vehicle capacity is sufficient for each cleaned street.
    * Connectors are not cleaned.
    * All mandatory streets are cleaned.

    Parameters
    ----------
    instance : dict
        Parsed instance.
    routes : list[list[int]]
        Per-vehicle junction sequences.
    clean_per_vehicle : list[list[int]]
        Per-vehicle lists of cleaned street indices.

    Returns
    -------
    is_valid : bool
    errors : list[str]
    """
    streets  = instance["streets"]
    vehicles = instance["vehicles"]
    T = instance["T"]
    S = instance["S"]
    M = instance["M"]
    C = instance["C"]

    # Build arc lookup: (u, v) → street_id
    arc_to_street: dict[tuple[int, int], int] = {}
    for s in streets:
        arc_to_street[(s["a"], s["b"])] = s["id"]
        if s["dir"] == 2:
            arc_to_street[(s["b"], s["a"])] = s["id"]

    errors: list[str] = []
    all_cleaned: set[int] = set()

    for k in range(C):
        route   = routes[k]
        cleaned = set(clean_per_vehicle[k])

        # Depot start/end
        if route[0] != S:
            errors.append(
                f"Vehicle {k}: route starts at {route[0]}, not depot {S}"
            )
        if route[-1] != S:
            errors.append(
                f"Vehicle {k}: route ends at {route[-1]}, not depot {S}"
            )

        # Traverse route
        total_time      = 0
        traversed_set: set[int] = set()
        valid_traverse  = True

        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            sid  = arc_to_street.get((u, v))
            if sid is None:
                errors.append(
                    f"Vehicle {k}: no arc ({u} -> {v}) at step {i}"
                )
                valid_traverse = False
                break
            traversed_set.add(sid)
            total_time += streets[sid]["cost"]

        if total_time > T:
            errors.append(
                f"Vehicle {k}: route time {total_time}s exceeds limit {T}s"
            )

        # Cleaning checks
        for j in cleaned:
            if j < 0 or j >= M:
                errors.append(f"Vehicle {k}: invalid street index {j}")
                continue
            s = streets[j]
            if valid_traverse and j not in traversed_set:
                errors.append(
                    f"Vehicle {k}: cleans street {j} but never traverses it"
                )
            if vehicles[k]["cap"] < s["req"]:
                errors.append(
                    f"Vehicle {k} (cap={vehicles[k]['cap']}): "
                    f"cannot clean street {j} (req={s['req']})"
                )
            if s["cat"] == "C":
                errors.append(
                    f"Vehicle {k}: cannot clean connector street {j}"
                )

        all_cleaned.update(cleaned)

    # All mandatory streets must be cleaned
    for j in range(M):
        if streets[j]["cat"] == "M" and j not in all_cleaned:
            errors.append(f"Mandatory street {j} not cleaned by any vehicle!")

    return len(errors) == 0, errors
