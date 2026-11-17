"""Command line of the complexity tool. Run from the repository root.

    python -m tools.complexity                 measure (default set) and write the dashboard
    python -m tools.complexity run --open      ... and open it in the browser
    python -m tools.complexity serve           interactive dashboard with a Run button
    python -m tools.complexity report          rebuild the dashboard from stored results
    python -m tools.complexity list            algorithms and instances the tool can see
"""

import argparse
import sys
import webbrowser
from pathlib import Path

from . import OUTPUT
from .algorithms import load
from .instances import DEFAULT_MAX_STREETS, discover, select
from .report import write_all
from .runner import MODES, Runner, plan


def _split(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def _progress(event: dict) -> None:
    kind = event["type"]
    if kind == "start":
        print(f"[{event['index']:>3}/{event['total']}] {event['label']} ...", end="", flush=True)
    elif kind == "done":
        print(f" {event['status']} ({event['wall_seconds']:.1f} s)", flush=True)
    elif kind == "skip":
        print(f"[{event['index']:>3}/{event['total']}] {event['label']} skipped: {event['reason']}")
    elif kind == "cancelled":
        print("\ncancelled")


def command_run(args) -> int:
    algorithms = load()
    wanted = _split(args.algorithms)
    if wanted:
        unknown = [a for a in wanted if a not in algorithms]
        if unknown:
            print(f"unknown algorithm(s): {', '.join(unknown)}; "
                  f"available: {', '.join(algorithms)}", file=sys.stderr)
            return 2
        algorithms = {a: algorithms[a] for a in wanted}
    try:
        instances = select(discover(), _split(args.instances), _split(args.families),
                           None if args.all else args.max_streets)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not instances:
        print("no instances selected", file=sys.stderr)
        return 2
    modes = _split(args.modes) or list(MODES)
    bad = [m for m in modes if m not in MODES]
    if bad:
        print(f"unknown mode(s): {', '.join(bad)}; use {', '.join(MODES)}", file=sys.stderr)
        return 2
    job_plan = plan(algorithms, instances, modes, fresh=args.fresh, folder=args.out)
    print(f"{len(algorithms)} algorithm(s) x {len(instances)} instance(s) x {len(modes)} mode(s): "
          f"{len(job_plan.jobs)} to measure, {job_plan.cached} reused")
    runner = Runner(repeat=args.repeat, timeout=args.timeout, folder=args.out, on_event=_progress)
    try:
        runner.run(job_plan.jobs)
    except KeyboardInterrupt:
        runner.cancel()
        print("\ninterrupted; writing what was measured")
    return command_report(args)


def command_report(args) -> int:
    write_all(load(), args.out)
    dashboard = args.out / "dashboard.html"
    print(f"Dashboard: {dashboard}\nReport:    {args.out / 'report.md'}")
    if getattr(args, "open", False):
        webbrowser.open(dashboard.as_uri())
    return 0


def command_serve(args) -> int:
    from .server import serve

    serve(port=args.port, open_browser=not args.no_browser, folder=args.out)
    return 0


def command_list(args) -> int:
    print("Algorithms:")
    for name, algorithm in load().items():
        print(f"  {name:<18} {algorithm.location:<45} [{algorithm.source}]")
    print(f"\nInstances (default: up to {DEFAULT_MAX_STREETS} streets; --all for every one):")
    for i in discover():
        mark = "*" if i.streets <= DEFAULT_MAX_STREETS else " "
        print(f"  {mark} {i.family + '/' + i.name:<40} N={i.junctions:<7} M={i.streets:<7} K={i.vehicles}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.complexity",
                                     description="Measure time, memory and Big O of the "
                                                 "project's algorithms and their functions.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", type=Path, default=OUTPUT,
                        help="output folder (default data/output/complexity)")
    sub = parser.add_subparsers(dest="command")
    commands = ("run", "report", "serve", "list")

    run = sub.add_parser("run", parents=[common], help="measure and write the dashboard (default)")
    run.add_argument("-a", "--algorithms", action="append",
                     help="comma-separated names (default: all)")
    run.add_argument("-i", "--instances", action="append",
                     help="comma-separated instance names, e.g. instance_A,Presheva")
    run.add_argument("-f", "--families", action="append",
                     help="instance families, e.g. syntetic_generated")
    run.add_argument("--max-streets", type=int, default=DEFAULT_MAX_STREETS,
                     help=f"skip larger instances (default {DEFAULT_MAX_STREETS})")
    run.add_argument("--all", action="store_true", help="include every instance, even huge cities")
    run.add_argument("-m", "--modes", action="append",
                     help=f"subset of {','.join(MODES)} (default: all)")
    run.add_argument("-r", "--repeat", type=int, default=3, help="timing repetitions (median)")
    run.add_argument("-t", "--timeout", type=float, default=300.0,
                     help="seconds per measurement (x3 for profile modes)")
    run.add_argument("--fresh", action="store_true", help="re-measure even if cached")
    run.add_argument("--open", action="store_true", help="open the dashboard when done")
    run.set_defaults(handler=command_run)

    report = sub.add_parser("report", parents=[common], help="rebuild the dashboard from stored results")
    report.add_argument("--open", action="store_true")
    report.set_defaults(handler=command_report)

    serve = sub.add_parser("serve", parents=[common], help="interactive dashboard on http://127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    serve.set_defaults(handler=command_serve)

    sub.add_parser("list", parents=[common], help="algorithms and instances").set_defaults(handler=command_list)

    argv = sys.argv[1:] if argv is None else argv
    if not argv or (argv[0] not in commands and argv[0] not in ("-h", "--help")):
        argv = ["run", *argv]  # plain `python -m tools.complexity [options]` means run
    args = parser.parse_args(argv)
    args.out = args.out.resolve()  # as_uri() for --open needs an absolute path
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
