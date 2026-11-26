"""
Solution file I/O for CLIPP.
"""

__all__ = ["write_output"]


def write_output(
    filepath: str,
    routes: list[list[int]],
    clean_per_vehicle: list[list[int]],
    C: int,
) -> None:
    """
    Write solution in the required CLIPP submission format.

    Format per vehicle (3 lines)::

        n                         <- number of streets traversed (= len(route)-1)
        j_0 j_1 ... j_n          <- n+1 junction indices (starts/ends at depot)
        s_0 s_1 ...              <- street indices cleaned (empty line if none)

    If the vehicle never leaves the depot (``route=[S]``), writes ``n=0``
    with a single junction ``[S]``.

    Parameters
    ----------
    filepath : str
        Destination path for the solution file.
    routes : list[list[int]]
        Per-vehicle junction sequences.
    clean_per_vehicle : list[list[int]]
        Per-vehicle lists of cleaned street indices.
    C : int
        Number of vehicles.
    """
    with open(filepath, "w") as fh:
        fh.write(f"{C}\n")
        for k in range(C):
            route   = routes[k]
            cleaned = sorted(clean_per_vehicle[k])
            n = len(route) - 1
            fh.write(f"{n}\n")
            fh.write(" ".join(map(str, route)) + "\n")
            fh.write(" ".join(map(str, cleaned)) + "\n")
