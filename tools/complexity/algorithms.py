"""Which algorithms the tool measures.

The tool reads ALGORITHMS from main.py, so an algorithm added there is
measured automatically. EXTRA lists solvers that have a `solve(instance)`
function but are not (yet) selectable in main.py; prefer main.py when you can.
"""

import importlib
import sys
from dataclasses import dataclass
from typing import Callable

from . import ROOT

# name -> "module:function". Only for solvers that are not in main.ALGORITHMS.
EXTRA: dict[str, str] = {
    "bidirectional": "clipp.bidirectional_search:solve",
}


@dataclass(frozen=True)
class Algorithm:
    name: str
    function: Callable
    source: str  # "main.py" or "extra"

    @property
    def location(self) -> str:
        return f"{self.function.__module__}:{self.function.__qualname__}"


def _import(target: str) -> Callable:
    module_name, _, attribute = target.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def load(reload: bool = False) -> dict[str, Algorithm]:
    """All measurable algorithms, main.py first, in a stable order.

    reload=True re-reads main.py, so a running dashboard server sees an
    algorithm added after it started.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if reload and "main" in sys.modules:
        importlib.invalidate_caches()
        main = importlib.reload(sys.modules["main"])
    else:
        main = importlib.import_module("main")
    found = {name: Algorithm(name, function, "main.py")
             for name, function in main.ALGORITHMS.items()}
    for name, target in EXTRA.items():
        if name in found:
            continue
        try:
            found[name] = Algorithm(name, _import(target), "extra")
        except (ImportError, AttributeError) as exc:  # keep the tool usable
            print(f"warning: cannot load extra algorithm {name} ({target}): {exc}",
                  file=sys.stderr)
    return found
