import argparse
from pathlib import Path

from clipp import recursive, recursive_enum
from clipp.graph import build_graph, shortest_path
from clipp.output import write_solution
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.solver import GreedyAssignmentError, solve
from clipp.validator import validate_solution

ALGORITHMS = {
    "greedy": solve,
    "recursive": recursive.solve,
    "recursive-enum": recursive_enum.solve,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", nargs="?", default="data/input/instance_E.txt")
    parser.add_argument("--algorithm", choices=sorted(ALGORITHMS), default="greedy")
    args = parser.parse_args()
    try:
        instance = parse_instance(args.instance)
        mandatory_count = sum(s.category == "M" for s in instance.streets)
        try:
            solution = ALGORITHMS[args.algorithm](instance)
        except GreedyAssignmentError as exc:
            print(f"FAILED: {exc}")
            print("No complete solution generated; no solution file or score produced.")
            partial = exc.partial_solution
            cleaned = {s for r in partial.routes for s in r.cleaned_street_ids}
            print(f"Mandatory streets cleaned before failure: {len(cleaned)}/{mandatory_count}")
            graph = build_graph(instance)
            for route in partial.routes:
                home = shortest_path(graph, route.current_junction, instance.depot)
                closed_time = route.total_time + home.total_time if home else "unreachable"
                print(f"Vehicle {route.vehicle_id}: committed time {route.total_time}, "
                      f"time including return {closed_time}; "
                      f"cleaned {route.cleaned_street_ids}")
            for reason in exc.reasons:
                print(reason)
            return 1

        errors = validate_solution(instance, solution)
        cleaned = {s for r in solution.routes for s in r.cleaned_street_ids}
        mandatory_ids = {s.id for s in instance.streets if s.category == "M"}
        print(f"Solution generated: {'INVALID' if errors else 'VALID'}")
        print(f"Mandatory streets cleaned: {len(cleaned & mandatory_ids)}/{mandatory_count}")
        for route in solution.routes:
            print(f"Vehicle {route.vehicle_id}: route time {route.total_time}/{instance.max_time}")
        if errors:
            for error in errors:
                print(error)
            return 1
        score = calculate_score(instance, solution)
        name = Path(args.instance).stem
        if name == "instance":
            name = f"{Path(args.instance).parent.name}_instance"
        folder = Path("data/output")
        if args.algorithm != "greedy":
            folder = folder / args.algorithm.replace("-", "_")
        output = folder / f"{name}_solution.txt"
        write_solution(solution, output)
        print(f"Score: {score.score} (cleaned length {score.cleaned_length}, "
              f"water waste {score.total_water_waste:g})")
        print(f"Output: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
