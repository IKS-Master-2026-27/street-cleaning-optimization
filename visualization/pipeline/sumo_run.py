"""Realistic mode: drive a converted solution in Eclipse SUMO.

Usage (from the repository root, after build.py has exported the city):

    python visualization/pipeline/sumo_run.py Presheva
    python visualization/pipeline/sumo_run.py Prishtina --traffic 1 --profile realistic

The solver assumes every truck drives each street at exactly 20 km/h. SUMO
(Simulation of Urban MObility) drives the same routes with real driving
behaviour: acceleration, junctions and right of way, and optional background
car traffic. The result shows how much longer each truck would take on real
roads and which trucks would miss the time limit.

Steps:
1. write SUMO's plain input files: nodes (junctions), edges (streets), the turns
   the routes need, and one vehicle per truck with its exact list of edges,
2. build the road network with netconvert (twice, see write_missing_turns),
3. optionally add background cars with randomTrips.py,
4. run sumo with --vehroute-output.exit-times, which records when every vehicle
   leaves every road,
5. store those times as solutions/<id>.sumo.bin, in the same step format as the
   exact timeline, so the app plays both with the same code.

Profiles:
    realistic  SUMO's default driver model and priority junctions (default)
    ideal      near-instant acceleration, no turn-speed limit, no internal
               junction lanes: shows how close SUMO gets to the solver's timing

SUMO must be installed, with SUMO_HOME set. Networks and raw outputs are kept in
pipeline/work/ (git-ignored).
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

from binfile import write_buffers
from convert import DATASET, OUTPUT, ROOT, city_folder
from formats import load_city, parse_solution
from projection import projector_for
from timeline import REVERSE, build_timeline

WORK = Path(__file__).resolve().parent / "work"
TRUCK_SPEED = 20 / 3.6  # settings.speed of the dataset: every street time assumes it

# km/h when a road has no usable maxspeed tag, and junction priority, per road class
ROAD_CLASSES = {
    "motorway": (100, 14), "trunk": (80, 13), "primary": (60, 12), "secondary": (50, 11),
    "tertiary": (50, 10), "motorway_link": (60, 9), "trunk_link": (50, 9),
    "primary_link": (50, 9), "secondary_link": (40, 8), "tertiary_link": (40, 8),
    "unclassified": (40, 7), "residential": (40, 6), "living_street": (20, 5),
    "service": (25, 4), "road": (40, 6),
}
VTYPES = {  # length, width (metres), colour
    "S": (5.0, 2.0, "77,208,225"),
    "M": (7.0, 2.4, "255,152,0"),
    "L": (9.0, 2.5, "224,64,251"),
}


def tool(name: str) -> str:
    home = os.environ.get("SUMO_HOME")
    if home:
        for candidate in (Path(home) / "bin" / name, Path(home) / "bin" / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found: install Eclipse SUMO and set SUMO_HOME")
    return found


def speed_limit(highway: str, maxspeed) -> float:
    """Road speed in m/s, never below the trucks' 20 km/h so trucks are not slowed."""
    kmh, _ = ROAD_CLASSES.get(highway, ROAD_CLASSES["road"])
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph)?", str(maxspeed or ""))
    if match:
        kmh = float(match.group(1)) * (1.609 if match.group(2) else 1)
    return max(kmh / 3.6, TRUCK_SPEED + 0.01)


def lane_count(lanes, two_way: bool) -> int:
    try:
        count = int(str(lanes or "1").split(";")[0])
    except ValueError:
        count = 1
    return max(1, min(count // 2 if two_way else count, 4))


def edge_id(street: int, reverse: bool) -> str:
    return f"s{street}_{'r' if reverse else 'f'}"


def parse_edge(edge: str):
    """'s12_r' -> (12, REVERSE); None for SUMO's internal junction edges."""
    match = re.fullmatch(r"s(\d+)_([fr])", edge)
    return (int(match.group(1)), REVERSE if match.group(2) == "r" else 0) if match else None


def write_network(city, project, work: Path, profile: str):
    """Plain XML nodes and edges: one node per junction, one edge per street
    direction (two for a two-way street), with the street's real shape."""
    inst, roads = city.instance, city.roads
    node_type = "unregulated" if profile == "ideal" else "priority"
    with open(work / "net.nod.xml", "w", encoding="utf-8") as out:
        out.write("<nodes>\n")
        for i, (lon, lat) in enumerate(city.geography["node_coordinates"]):
            x, y = project(lon, lat)
            out.write(f'  <node id="j{i}" x="{x:.2f}" y="{y:.2f}" type="{node_type}"/>\n')
        out.write("</nodes>\n")

    with open(work / "net.edg.xml", "w", encoding="utf-8") as out:
        out.write("<edges>\n")
        for k in range(inst.streets):
            r = roads.get(city.mapping["road_ids"][k])
            shape = [project(lon, lat) for lon, lat in roads.points(r)]
            two_way = inst.way[k] == 2
            highway = roads.highways[r]
            _, priority = ROAD_CLASSES.get(highway, ROAD_CLASSES["road"])
            common = (f'priority="{priority}" numLanes="{lane_count(roads.lanes[r], two_way)}" '
                      f'speed="{speed_limit(highway, roads.maxspeed[r]):.2f}" length="{roads.meters[r]:.2f}"')
            params = (f'    <param key="type" value="{inst.type[k]}"/>\n'
                      f'    <param key="req" value="{inst.req[k]}"/>\n')
            if roads.names[r]:
                params += f'    <param key="name" value={quoteattr(roads.names[r])}/>\n'
            directions = [(False, inst.a[k], inst.b[k], shape)]
            if two_way:
                directions.append((True, inst.b[k], inst.a[k], shape[::-1]))
            for reverse, a, b, points in directions:
                shape_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
                out.write(f'  <edge id="{edge_id(k, reverse)}" from="j{a}" to="j{b}" {common} '
                          f'shape="{shape_text}">\n{params}  </edge>\n')
        out.write("</edges>\n")


def route_turns(routes_steps) -> set[tuple[str, str]]:
    """Every (from edge, to edge) turn the trucks' routes use."""
    turns = set()
    for steps in routes_steps:
        for (k1, r1), (k2, r2) in zip(steps, steps[1:]):
            turns.add((edge_id(k1, r1), edge_id(k2, r2)))
    return turns


def net_turns(net_file: Path):
    """Lane-level turns (to edge, from lane, to lane) per edge of a built network,
    and the lane count of each edge. SUMO's internal edges are left out."""
    turns: dict[str, set[tuple[str, int, int]]] = {}
    lanes: dict[str, int] = {}
    for _, element in ElementTree.iterparse(net_file, events=("end",)):
        if element.tag == "connection" and not element.get("from", ":").startswith(":"):
            turns.setdefault(element.get("from"), set()).add(
                (element.get("to"), int(element.get("fromLane")), int(element.get("toLane"))))
        elif element.tag == "edge" and element.get("function") != "internal":
            lanes[element.get("id")] = sum(1 for child in element if child.tag == "lane")
        if element.tag in ("connection", "edge"):
            element.clear()
    return turns, lanes


def edge_turns(turns) -> set[tuple[str, str]]:
    return {(a, b) for a, targets in turns.items() for b, _, _ in targets}


def write_missing_turns(needed: set[tuple[str, str]], built, lanes, path: Path) -> int:
    """Connection file adding the turns the routes need that netconvert left out
    (mostly U-turns at simple junctions).

    netconvert drops every computed turn of an edge that gets a user-defined one,
    so for such an edge all its computed turns are listed again, lane by lane
    (edge-level and lane-level turns of one edge do not mix). Without this, other
    traffic loses those turns and the network jams. A missing turn goes from the
    leftmost lane to the leftmost lane, as a U-turn would.
    """
    missing: dict[str, set[str]] = {}
    for a, b in needed - edge_turns(built):
        missing.setdefault(a, set()).add(b)
    with open(path, "w", encoding="utf-8") as out:
        out.write("<connections>\n")
        for a in sorted(missing):
            lane_turns = set(built.get(a, set()))
            lane_turns |= {(b, lanes[a] - 1, lanes[b] - 1) for b in missing[a]}
            for b, from_lane, to_lane in sorted(lane_turns):
                out.write(f'  <connection from="{a}" to="{b}" fromLane="{from_lane}" toLane="{to_lane}"/>\n')
        out.write("</connections>\n")
    return sum(len(v) for v in missing.values())


def write_routes(inst, routes_steps, work: Path, profile: str):
    """One SUMO vehicle per truck, departing at 0 with its exact list of edges."""
    with open(work / "trucks.rou.xml", "w", encoding="utf-8") as out:
        out.write("<routes>\n")
        for name, (length, width, color) in VTYPES.items():
            extra = ' accel="100" decel="100" emergencyDecel="100" sigma="0" tau="0.1" minGap="0.5"' \
                if profile == "ideal" else ""
            out.write(f'  <vType id="{name}" vClass="delivery" length="{length}" width="{width}" '
                      f'maxSpeed="{TRUCK_SPEED:.4f}" color="{color}"{extra}/>\n')
        for v, steps in enumerate(routes_steps):
            if not steps:
                continue  # this truck never leaves the depot
            edges = " ".join(edge_id(k, r) for k, r in steps)
            out.write(f'  <vehicle id="v{v}" type="{inst.fleet[v]}" depart="0" departLane="best" '
                      f'departSpeed="max">\n    <route edges="{edges}"/>\n  </vehicle>\n')
        out.write("</routes>\n")


def run(cmd: list[str], log: Path):
    # run inside the work folder: some SUMO tools write helper files to the current directory
    with open(log, "w", encoding="utf-8") as out:
        result = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=log.parent)
    if result.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise SystemExit(f"{Path(cmd[0]).name} failed (exit {result.returncode}), see {log}:\n{tail}")


def read_vehroutes(path: Path):
    """vehicle id -> (depart, edges, exit times, arrival or None when unfinished)."""
    result = {}
    for _, element in ElementTree.iterparse(path, events=("end",)):
        if element.tag != "vehicle":
            continue
        timed = [r for r in element.iter("route") if r.get("exitTimes")]
        if timed:
            route = timed[-1]
            arrival = element.get("arrival")
            result[element.get("id")] = (
                float(element.get("depart")),
                route.get("edges").split(),
                [float(t) for t in route.get("exitTimes").split()],
                float(arrival) if arrival is not None else None,
            )
        element.clear()
    return result


def sumo_city(folder: Path, output: Path = OUTPUT, solution_id: str = "greedy", profile: str = "realistic",
              traffic: float | None = None, seed: int = 42) -> dict:
    started = time.time()
    out = output / folder.name
    sol_path = out / "solutions" / f"{solution_id}.json"
    if not sol_path.exists():
        raise SystemExit(f"{sol_path} not found: run build.py for this city first")
    sol = json.loads(sol_path.read_text(encoding="utf-8"))
    source = ROOT / sol["source"]
    if not source.exists():
        raise SystemExit(f"solution file {source} not found")
    city = load_city(folder)
    inst = city.instance
    routes = parse_solution(source.read_text(encoding="utf-8"))
    exact, errors = build_timeline(inst, routes)
    if errors:
        raise SystemExit("; ".join(errors[:5]))
    routes_steps = [
        [(exact.street[i], bool(exact.flags[i] & REVERSE)) for i in range(exact.offsets[v], exact.offsets[v + 1])]
        for v in range(len(routes))
    ]

    work = WORK / folder.name / solution_id
    work.mkdir(parents=True, exist_ok=True)
    write_network(city, projector_for(city.geography["node_coordinates"]), work, profile)
    write_routes(inst, routes_steps, work, profile)

    netconvert = [
        tool("netconvert"),
        "--node-files", str(work / "net.nod.xml"),
        "--edge-files", str(work / "net.edg.xml"),
        "--offset.disable-normalization", "true",  # keep our coordinates, so SUMO lines up with the app
        "--no-turnarounds.geometry", "false",
        "--junctions.join", "false",
        "--geometry.remove", "false",
        "--no-warnings", "true",
    ]
    if profile == "ideal":
        netconvert += ["--no-internal-links", "true", "--junctions.limit-turn-speed", "-1"]
    # pass 1: netconvert's own turns; pass 2: add the turns the routes still miss
    t0 = time.time()
    plain = work / "net.plain.net.xml"
    run(netconvert + ["--output-file", str(plain)], work / "netconvert.log")
    built, lanes = net_turns(plain)
    needed = route_turns(routes_steps)
    added = write_missing_turns(needed, built, lanes, work / "net.con.xml")
    run(netconvert + ["--connection-files", str(work / "net.con.xml"),
                      "--output-file", str(work / "net.net.xml")], work / "netconvert.log")
    plain.unlink()
    net_seconds = time.time() - t0
    still_missing = sorted(needed - edge_turns(net_turns(work / "net.net.xml")[0]))
    if still_missing:
        raise SystemExit(f"netconvert left out {len(still_missing)} turns the routes need, e.g. {still_missing[:3]}")

    route_files = [str(work / "trucks.rou.xml")]
    if traffic:
        random_trips = Path(os.environ.get("SUMO_HOME", "")) / "tools" / "randomTrips.py"
        if not random_trips.exists():
            raise SystemExit("randomTrips.py not found: set SUMO_HOME")
        # -r routes the trips with duarouter, which drops trips that have no route
        run([sys.executable, str(random_trips), "-n", str(work / "net.net.xml"),
             "-o", str(work / "cars.trips.xml"), "-r", str(work / "cars.rou.xml"),
             "-b", "0", "-e", str(inst.time_limit), "--insertion-density", str(traffic),
             "--prefix", "car", "--seed", str(seed), "--min-distance", "300",
             "--trip-attributes", 'departLane="best"'], work / "randomTrips.log")
        route_files.append(str(work / "cars.rou.xml"))

    t0 = time.time()
    run([tool("sumo"),
         "--net-file", str(work / "net.net.xml"),
         "--route-files", ",".join(route_files),
         "--vehroute-output", str(work / "vehroutes.xml"),
         "--vehroute-output.exit-times", "true",
         "--vehroute-output.write-unfinished", "true",
         "--statistic-output", str(work / "statistics.xml"),
         "--end", str(inst.time_limit * 3),
         "--time-to-teleport", "300",
         "--ignore-route-errors", "true",
         "--no-step-log", "true",
         "--no-warnings", "true",
         "--seed", str(seed)], work / "sumo.log")
    sim_seconds = time.time() - t0

    # SUMO's exit times -> our step format: trucks first (fleet order), then cars
    vehroutes = read_vehroutes(work / "vehroutes.xml")
    offsets, street, enter, flags, ends, trucks = [0], [], [], [], [], []
    for v, steps in enumerate(routes_steps):
        record = vehroutes.get(f"v{v}")
        info = {"steps": 0, "end": 0.0, "depart": 0.0, "complete": not steps}
        if steps and record:
            depart, edges, exits, arrival = record
            matches = edges == [edge_id(k, r) for k, r in steps] and len(exits) == len(edges)
            clock = depart
            for i in range(len(exits) if matches else 0):
                street.append(steps[i][0])
                enter.append(clock)
                flags.append(exact.flags[exact.offsets[v] + i])  # the same streets are cleaned
                clock = exits[i]
            info = {"steps": len(exits) if matches else 0, "end": round(clock, 2), "depart": depart,
                    "complete": matches and arrival is not None}
        ends.append(info["end"])
        offsets.append(len(street))
        trucks.append(info)
    cars = 0
    for vid, (depart, edges, exits, _) in vehroutes.items():
        if not vid.startswith("car"):
            continue
        clock = depart
        for edge, exit_time in zip(edges, exits):
            parsed = parse_edge(edge)
            if parsed:
                street.append(parsed[0])
                enter.append(clock)
                flags.append(parsed[1])
            clock = exit_time
        ends.append(clock)
        offsets.append(len(street))
        cars += 1

    stats = ElementTree.parse(work / "statistics.xml").getroot().find("teleports")
    file_name = f"{solution_id}.sumo.bin"
    buffers = write_buffers(out / "solutions" / file_name, {
        "offsets": ("uint32", offsets),
        "street": ("uint32", street),
        "enter": ("float32", enter),
        "flags": ("uint8", flags),
        "end": ("float32", ends),
    })
    late = sum(1 for t in trucks if t["end"] > inst.time_limit)
    sol["sumo"] = {
        "file": file_name,
        "buffers": buffers,
        "profile": profile,
        "traffic": traffic,
        "trucks": trucks,
        "cars": cars,
        "turnsAdded": added,
        "late": late,
        "incomplete": sum(1 for t in trucks if not t["complete"]),
        "teleports": int(stats.get("total", 0)) if stats is not None else None,
        "sumoVersion": subprocess.run([tool("sumo"), "--version"], capture_output=True, text=True)
                       .stdout.splitlines()[0],
        "sourceSha256": sol.get("sourceSha256"),  # the solution file this run was made from
    }
    sol_path.write_text(json.dumps(sol), encoding="utf-8")

    delays = sorted((t["end"] - exact.end[v]) / exact.end[v] * 100
                    for v, t in enumerate(trucks) if t["steps"] and exact.end[v])
    median = delays[len(delays) // 2] if delays else 0.0
    print(f"{city.name} [{solution_id}, {profile}]: netconvert {net_seconds:.1f} s, SUMO {sim_seconds:.1f} s, "
          f"{cars} background cars, truck delay median {median:+.1f} % "
          f"(min {delays[0] if delays else 0:+.1f} %, max {delays[-1] if delays else 0:+.1f} %), "
          f"{late}/{len(trucks)} trucks over the time limit, {sol['sumo']['incomplete']} incomplete, "
          f"{sol['sumo']['teleports']} teleports; total {time.time() - started:.1f} s")
    return sol["sumo"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="+", help="city names (e.g. Presheva) or folders, already built")
    parser.add_argument("--solution", default="greedy", help="algorithm whose solution to drive (default: greedy)")
    parser.add_argument("--profile", choices=("realistic", "ideal"), default="realistic")
    parser.add_argument("--traffic", type=float, default=None, metavar="DENSITY",
                        help="background cars per hour per km of lane (randomTrips.py "
                             "--insertion-density), so traffic scales with the city; try 1")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    for name in args.cities:
        sumo_city(city_folder(name, DATASET), OUTPUT, args.solution, args.profile, args.traffic, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
