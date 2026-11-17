"""Measure time, memory and Big O of every algorithm and the functions it uses.

Run from the repository root:

    python -m tools.complexity            # measure and write the dashboard
    python -m tools.complexity serve      # interactive dashboard in the browser

See tools/complexity/README.md.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "output" / "complexity"
SCHEMA = 2
