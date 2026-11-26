"""
Instance file parser for CLIPP.
"""

__all__ = ["parse_instance"]

# Vehicle capacity lookup (litres per km)
VEHICLE_CAPACITY = {"S": 10, "M": 20, "L": 30}

# Valid street categories
VALID_CATEGORIES = {"M", "O", "C"}


def parse_instance(filepath: str) -> dict:
    """
    Parse a CLIPP instance file.

    Supported header formats
    ------------------------
    ``N M T C S``       – *alpha* defaults to 0.5, no junction coordinates.
    ``N M T C S alpha`` – *alpha* given, no junction coordinates.

    After the header an **optional** junction-coordinate block (N lines of two
    floats) may appear, followed by M street lines and one vehicle-types line.

    Parameters
    ----------
    filepath : str
        Path to the ``.txt`` instance file.

    Returns
    -------
    dict
        Keys: ``N``, ``M``, ``T``, ``C``, ``S``, ``alpha``, ``streets``,
        ``vehicles``, ``junction_coords``.
    """
    with open(filepath) as fh:
        raw = [ln.strip() for ln in fh if ln.strip()]

    idx = 0

    # ---- Header ------------------------------------------------------------
    header = raw[idx].split()
    idx += 1

    N = int(header[0])   # junctions
    M = int(header[1])   # streets
    T = int(header[2])   # time limit (seconds)
    C = int(header[3])   # vehicles
    S = int(header[4])   # depot junction
    alpha = float(header[5]) if len(header) >= 6 else 0.5
    assert 0.0 <= alpha <= 1.0, f"alpha must be in [0,1], got {alpha}"

    # ---- Optional junction-coordinate block --------------------------------
    junction_coords: list[tuple[float, float]] = []
    if idx < len(raw):
        tokens = raw[idx].split()
        if len(tokens) == 2:
            try:
                float(tokens[0])
                float(tokens[1])
                for _ in range(N):
                    parts = raw[idx].split()
                    junction_coords.append((float(parts[0]), float(parts[1])))
                    idx += 1
            except ValueError:
                pass  # tokens aren't floats – no coordinate block

    # ---- Street lines ------------------------------------------------------
    streets: list[dict] = []
    for j in range(M):
        parts = raw[idx].split()
        idx += 1

        a      = int(parts[0])
        b      = int(parts[1])
        d      = int(parts[2])   # 1 = one-way A→B, 2 = two-way
        cost   = int(parts[3])   # traversal time (seconds)
        length = int(parts[4])   # length in metres
        cat    = parts[5]        # M / O / C
        req    = int(parts[6])   # cleaning requirement (L/km); 0 for connectors

        assert 0 <= a < N and 0 <= b < N and a != b, \
            f"Street {j}: invalid junctions"
        assert d in (1, 2), \
            f"Street {j}: direction must be 1 or 2"
        assert cat in VALID_CATEGORIES, \
            f"Street {j}: unknown category '{cat}'"

        streets.append({
            "id": j, "a": a, "b": b, "dir": d,
            "cost": cost, "length": length,
            "cat": cat, "req": req,
        })

    # ---- Vehicle-types line ------------------------------------------------
    vehicle_tokens = raw[idx].split()
    assert len(vehicle_tokens) == C, (
        f"Expected {C} vehicle types, got {len(vehicle_tokens)}: {vehicle_tokens}"
    )
    vehicles = [{"type": t, "cap": VEHICLE_CAPACITY[t]} for t in vehicle_tokens]

    return {
        "N": N, "M": M, "T": T, "C": C, "S": S, "alpha": alpha,
        "streets": streets, "vehicles": vehicles,
        "junction_coords": junction_coords,
    }
