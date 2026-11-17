"""Turn measurements into a measured Big O.

From points (n, y), with n = number of streets, two estimates are made:

* the log-log slope b of y ~ a * n^b (least squares on log n, log y), and
* the growth class from CLASSES whose curve c * f(n) fits best; the simplest
  class within 10 % of the best residual wins, so a noisy linear curve is not
  reported as n log n.
"""

import math
from dataclasses import asdict, dataclass

MIN_POINTS = 3

# Growth classes, ordered from slowest to fastest. f(n) is used for n >= 2.
CLASSES = [
    ("O(1)", lambda n: 1.0),
    ("O(log n)", lambda n: math.log2(n)),
    ("O(sqrt n)", lambda n: math.sqrt(n)),
    ("O(n)", lambda n: n),
    ("O(n log n)", lambda n: n * math.log2(n)),
    ("O(n^1.5)", lambda n: n ** 1.5),
    ("O(n^2)", lambda n: n * n),
    ("O(n^2 log n)", lambda n: n * n * math.log2(n)),
    ("O(n^3)", lambda n: n ** 3),
]


@dataclass
class Fit:
    points: int
    slope: float | None = None
    r2: float | None = None
    model: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _usable(xs, ys):
    return [(float(x), float(y)) for x, y in zip(xs, ys)
            if x is not None and y is not None and x > 0 and y > 0]


def power_fit(xs, ys) -> tuple[float, float, float] | None:
    """(slope, intercept, r2) of log y = intercept + slope * log x."""
    pairs = _usable(xs, ys)
    if len(pairs) < 2 or len({x for x, _ in pairs}) < 2:
        return None
    lx = [math.log(x) for x, _ in pairs]
    ly = [math.log(y) for _, y in pairs]
    mx, my = sum(lx) / len(lx), sum(ly) / len(ly)
    sxx = sum((x - mx) ** 2 for x in lx)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(lx, ly)) / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ly)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(lx, ly))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return slope, intercept, r2


def best_class(xs, ys) -> str | None:
    pairs = [(max(x, 2.0), y) for x, y in _usable(xs, ys)]
    if len(pairs) < MIN_POINTS:
        return None
    scored = []
    for name, f in CLASSES:
        logs = [math.log(y) - math.log(f(x)) for x, y in pairs]
        c = sum(logs) / len(logs)
        scored.append((sum((value - c) ** 2 for value in logs), name))
    best = min(score for score, _ in scored)
    for score, name in scored:  # CLASSES is ordered simplest first
        if score <= best * 1.10 + 1e-9:
            return name
    return None


def growth(xs, ys) -> Fit:
    pairs = _usable(xs, ys)
    distinct = len({x for x, _ in pairs})
    if distinct < MIN_POINTS:
        return Fit(points=distinct, reason="too few points")
    slope, _, r2 = power_fit(xs, ys)
    return Fit(points=distinct, slope=round(slope, 3), r2=round(r2, 3),
               model=best_class(xs, ys))
