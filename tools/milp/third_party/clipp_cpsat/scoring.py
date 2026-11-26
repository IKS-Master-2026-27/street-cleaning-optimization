"""
Objective-function evaluation for CLIPP solutions.
"""

__all__ = ["compute_score"]


def compute_score(
    instance: dict,
    clean_per_vehicle: list[list[int]],
) -> tuple[float, float, float, int, float, int, float, set[int]]:
    """
    Compute the CLIPP normalized objective value for a given solution.

    Parameters
    ----------
    instance : dict
        Parsed instance.
    clean_per_vehicle : list[list[int]]
        Per-vehicle lists of cleaned street indices.

    Returns
    -------
    score : float
        ``alpha * coverage + (1 - alpha) * efficiency``.
    coverage : float
        Normalized coverage in ``[0, 1]``.
    efficiency : float
        Normalized efficiency in ``[0, 1]``.
    total_length : int
        Sum of cleaned street lengths (metres).
    total_waste : float
        Total water wasted (litres).
    L_max : int
        Sum of lengths of all mandatory/optional streets.
    W_max : float
        Worst-case waste if all mandatory/optional streets are cleaned by L.
    cleaned_set : set[int]
        Set of cleaned street indices.
    """
    streets  = instance["streets"]
    vehicles = instance["vehicles"]
    alpha    = instance["alpha"]

    cleaned_length: dict[int, int] = {}  # j → length (counted once)
    total_waste = 0.0

    for k, cleaned in enumerate(clean_per_vehicle):
        for j in cleaned:
            s = streets[j]
            if s["cat"] == "C":
                continue
            waste = (vehicles[k]["cap"] - s["req"]) * s["length"] / 1000.0
            total_waste += waste
            if j not in cleaned_length:
                cleaned_length[j] = s["length"]

    total_length = sum(cleaned_length.values())
    L_max = sum(s["length"] for s in streets if s["cat"] != "C")
    W_max = sum(
        max(0, 30 - s["req"]) * s["length"] / 1000.0
        for s in streets if s["cat"] != "C"
    )

    coverage = (total_length / L_max) if L_max > 0 else 1.0
    efficiency = 1.0 - (total_waste / W_max) if W_max > 0 else 1.0
    efficiency = max(0.0, min(1.0, efficiency))
    score = alpha * coverage + (1.0 - alpha) * efficiency

    return (
        score,
        coverage,
        efficiency,
        total_length,
        total_waste,
        L_max,
        W_max,
        set(cleaned_length.keys()),
    )
