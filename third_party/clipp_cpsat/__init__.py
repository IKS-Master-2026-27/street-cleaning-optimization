"""
CLIPP – Climate-Integrated Street Cleaning Routing Problem
===========================================================

Submodules
----------
parser          – Instance file parsing
graph           – Graph construction & shortest-path utilities
model           – CP-SAT MILP formulation & subtour elimination
reconstruction  – Eulerian-circuit route reconstruction
validator       – Solution feasibility checking
scoring         – Objective-function evaluation
io              – Solution file I/O
"""

from .parser import parse_instance
from .graph import (
    build_arcs,
    dijkstra,
    dijkstra_with_prev,
    shortest_path_nodes,
    build_adj_multigraph,
    connected_components,
)
from .model import solve_milp
from .reconstruction import reconstruct_route
from .validator import validate_solution
from .scoring import compute_score
from .io import write_output

__all__ = [
    "parse_instance",
    "build_arcs",
    "dijkstra",
    "dijkstra_with_prev",
    "shortest_path_nodes",
    "build_adj_multigraph",
    "connected_components",
    "solve_milp",
    "reconstruct_route",
    "validate_solution",
    "compute_score",
    "write_output",
]
