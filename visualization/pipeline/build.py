"""Instance -> algorithm -> 3D simulation, for one or more cities.

Usage (from the repository root):

    python visualization/pipeline/build.py Presheva
    python visualization/pipeline/build.py Presheva --algorithm greedy --rerun

1. reads the city's instance generated for the course (data/input/real_instances/<City>/),
2. runs the algorithm on it, unless its solution already exists, and checks the
   solution with clipp's validator; the solution is kept in the validator's format
   at data/output/<algorithm>/<City>_instance_solution.txt,
3. with --buildings, downloads the city's 3D buildings once (see buildings.py),
4. exports the city and the solution for the 3D app (see convert.py),
5. with --sumo, drives the solution in Eclipse SUMO for the app's realistic mode
   (see sumo_run.py; --traffic adds background cars).

Then start the app (cd visualization; npm run dev). New algorithms are added in
algorithms.py.
"""

import argparse
import sys

from algorithms import ALGORITHMS, run_algorithm, solution_path
from buildings import build_buildings
from convert import DATASET, OUTPUT, city_folder, convert, display, write_index


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="+", help="city names (e.g. Presheva) or folders")
    parser.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="greedy")
    parser.add_argument("--buildings", action="store_true",
                        help="also download 3D buildings for the city (see buildings.py; "
                             "a few minutes per city the first time)")
    parser.add_argument("--sumo", action="store_true",
                        help="also run the realistic mode in Eclipse SUMO (see sumo_run.py)")
    parser.add_argument("--traffic", type=float, default=None, metavar="DENSITY",
                        help="with --sumo: background cars per hour per km of lane; try 1")
    parser.add_argument("--rerun", action="store_true",
                        help="run the algorithm again even if its solution already exists")
    args = parser.parse_args(argv)

    failed = False
    for name in args.cities:
        try:
            folder = city_folder(name)
            output = solution_path(args.algorithm, folder.name)
            if args.rerun or not output.exists():
                print(f"{folder.name}: running {args.algorithm}...", flush=True)
                seconds = run_algorithm(args.algorithm, folder / "instance.txt", output)
                print(f"  solved in {seconds:.1f} s -> {display(output)}")
            else:
                print(f"{folder.name}: using existing {display(output)} (--rerun to solve again)")
            if args.buildings and not (OUTPUT / folder.name / "buildings.json").exists():
                try:
                    build_buildings(folder, OUTPUT)
                except (OSError, ValueError) as exc:  # buildings are optional; keep going
                    print(f"  buildings skipped: {exc}", file=sys.stderr)
            convert(folder, OUTPUT)
            if args.sumo:
                from sumo_run import sumo_city  # needs SUMO installed only when asked for
                sumo_city(folder, OUTPUT, args.algorithm, traffic=args.traffic)
        except (ValueError, OSError, KeyError, SystemExit) as exc:  # SystemExit: sumo_run.py's errors
            print(f"error: {exc}", file=sys.stderr)
            failed = True
    write_index(OUTPUT, DATASET)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
