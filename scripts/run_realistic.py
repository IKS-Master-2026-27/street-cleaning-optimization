"""Run an algorithm on the realistic instances (data/input/realistic_instances).

Usage (from the repository root):
    python scripts/run_realistic.py --algorithm dp-memo                 # all 10 cities
    python scripts/run_realistic.py --algorithm dp-memo --city Presheva

Every solution is checked by the repository's validator (clipp/validator.py)
before it is written. Valid solutions go to
    data/output/realistic_instances/<algorithm_name>/<City>_instance_solution.txt
(a separate folder, so they do not overwrite the results for data/input/real_instances,
which use the same file names). One line per run (score, time, status) is appended to
    data/output/realistic_instances/results.csv
"""

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import ALGORITHMS  # noqa: E402
from clipp.output import write_solution  # noqa: E402
from clipp.parser import parse_instance  # noqa: E402
from clipp.scoring import calculate_score  # noqa: E402
from clipp.validator import validate_solution  # noqa: E402

INPUT = ROOT / "data" / "input" / "realistic_instances"
OUTPUT = ROOT / "data" / "output" / "realistic_instances"
FIELDS = ["date", "algorithm", "city", "status", "score", "mandatory_cleaned",
          "mandatory_total", "vehicles", "time_limit", "max_route_time", "seconds", "note"]


def run(algorithm: str, city: str) -> dict:
    path = INPUT / city / "instance.txt"
    row = {"date": datetime.now().isoformat(timespec="seconds"), "algorithm": algorithm,
           "city": city, "note": ""}
    instance = parse_instance(path)
    mandatory = {s.id for s in instance.streets if s.category == "M"}
    row.update(mandatory_total=len(mandatory), vehicles=instance.num_vehicles,
               time_limit=instance.max_time)
    started = time.perf_counter()
    try:
        solution = ALGORITHMS[algorithm](instance)
    except Exception as exc:  # the algorithm found no solution
        row.update(status="FAILED", seconds=f"{time.perf_counter() - started:.1f}",
                   note=f"{type(exc).__name__}: {exc}"[:300])
        return row
    row["seconds"] = f"{time.perf_counter() - started:.1f}"
    errors = validate_solution(instance, solution)
    cleaned = {s for r in solution.routes for s in r.cleaned_street_ids}
    row.update(mandatory_cleaned=len(cleaned & mandatory),
               max_route_time=max((r.total_time for r in solution.routes), default=0))
    if errors:
        row.update(status="INVALID", note="; ".join(map(str, list(errors)[:3]))[:300])
        return row
    row.update(status="VALID", score=f"{calculate_score(instance, solution).score:.6f}")
    folder = OUTPUT / algorithm.replace("-", "_")
    write_solution(solution, folder / f"{city}_instance_solution.txt")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--algorithm", required=True, choices=sorted(ALGORITHMS))
    parser.add_argument("--city", action="append", help="city folder name (repeatable)")
    args = parser.parse_args()
    cities = args.city or sorted(p.parent.name for p in INPUT.glob("*/instance.txt"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    log = OUTPUT / "results.csv"
    ok = True
    for city in cities:
        row = run(args.algorithm, city)
        ok &= row["status"] == "VALID"
        new = not log.exists()
        with log.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, FIELDS)
            if new:
                writer.writeheader()
            writer.writerow(row)
        print(f"{row['status']:7} {args.algorithm:10} {city:13} score {row.get('score', '-'):>8} "
              f"{row['seconds']:>8}s  {row['note']}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
