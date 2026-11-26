"""Cold/warm start runs of the CLIPP competition MILP model (OR-Tools CP-SAT).

Makes the shared repository code (``clipp``) and the unchanged competition
model (``third_party/clipp_cpsat``) importable.
"""

import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2]     # tools/milp
REPO = TOOL.parents[1]                         # repository root
for _path in (REPO, TOOL / "third_party"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
