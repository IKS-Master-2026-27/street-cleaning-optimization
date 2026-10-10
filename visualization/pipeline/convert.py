"""Convert real-city folders into the compact files the 3D viewer loads.

Usually run through build.py, which first runs the algorithm. On its own it
re-exports cities whose solutions already exist (from the repository root):

    python visualization/pipeline/convert.py Presheva

It exports every algorithm solution found in data/output/<algorithm>/<City>_instance_solution.txt
(see algorithms.py). For each city it writes, under visualization/public/data/<City>/:

    city.json                 metadata, projection, boundary, names, buffer layout
    streets.bin               street attributes and projected polylines (a -> b)
    solutions/<id>.json       vehicles, score and buffer layout of one solution
    solutions/<id>.steps.bin  every step: street, entry time, flags

and refreshes visualization/public/data/index.json from the dataset catalog.
"""

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import sys
import time

from algorithms import ALGORITHMS, solution_path
from binfile import write_buffers
from checks import check_city
from formats import STREET_TYPES, City, load_city, parse_solution, read_json
from projection import projector_for
from timeline import build_timeline, score

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "input" / "real_instances"
OUTPUT = ROOT / "visualization" / "public" / "data"


def display(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def project_boundary(geometry: dict, project) -> list:
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    return [
        [[[round(c, 1) for c in project(lon, lat)] for lon, lat in ring] for ring in polygon]
        for polygon in polygons
    ]


def export_city(city: City, out: Path) -> tuple[dict, object]:
    inst, mapping = city.instance, city.mapping
    coords = city.geography["node_coordinates"]
    project = projector_for(coords)

    roads = city.roads
    names, name_index = [], {}
    highways, highway_index = [], {}
    name_of, highway_of, meters = [], [], []
    offsets, points = array("I", [0]), array("f")  # compact: large cities have millions of points
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for k in range(inst.streets):
        r = roads.get(mapping["road_ids"][k])
        name = roads.names[r]
        if name is None:
            name_of.append(-1)
        else:
            name_of.append(name_index.setdefault(name, len(names)))
            if name_of[-1] == len(names):
                names.append(name)
        highway = roads.highways[r]
        highway_of.append(highway_index.setdefault(highway, len(highways)))
        if highway_of[-1] == len(highways):
            highways.append(highway)
        meters.append(roads.meters[r])
        for lon, lat in roads.points(r):
            x, y = project(lon, lat)
            points.extend((x, y))
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
        offsets.append(len(points) // 2)

    buffers = write_buffers(out / "streets.bin", {
        "a": ("uint32", inst.a),
        "b": ("uint32", inst.b),
        "way": ("uint8", inst.way),
        "time": ("uint32", inst.time),
        "length": ("uint32", inst.length),
        "meters": ("float32", meters),
        "type": ("uint8", [STREET_TYPES.index(t) for t in inst.type]),
        "req": ("uint8", inst.req),
        "highway": ("uint8", highway_of),
        "name": ("int32", name_of),
        "offsets": ("uint32", offsets),
        "points": ("float32", points),
    })

    depot_x, depot_y = project(*coords[inst.depot])
    manifest = city.manifest
    data = {
        "version": 1,
        "city": manifest.get("city_id"),
        "directory": city.folder.name,
        "name": city.name,
        "osmName": manifest.get("osm_name"),
        "country": manifest.get("country"),
        "osmUrl": manifest.get("osm_url"),
        "scope": manifest.get("scope"),
        "attribution": manifest.get("attribution", "© OpenStreetMap contributors, ODbL 1.0"),
        "projection": {"utm": project.label, "origin": list(project.origin)},
        "bounds": [round(min_x, 1), round(min_y, 1), round(max_x, 1), round(max_y, 1)],
        "boundary": project_boundary(city.geography["boundary"]["geometry"], project),
        "nodes": inst.nodes,
        "depot": {"node": inst.depot, "x": round(depot_x, 2), "y": round(depot_y, 2)},
        "timeLimit": inst.time_limit,
        "alpha": inst.alpha,
        "fleet": "".join(inst.fleet),
        "silo": mapping.get("silo"),
        "demand": bool(mapping.get("demand")),
        "highways": highways,
        "names": names,
        "streets": {"count": inst.streets, "file": "streets.bin", "buffers": buffers},
        "stats": {
            "mandatory": inst.type.count("M"),
            "optional": inst.type.count("O"),
            "connector": inst.type.count("C"),
            "km": round(sum(meters) / 1000, 1),
            "excludedWays": city.geography.get("excluded_count", 0),
        },
        "solutions": [],
    }
    return data, project


def export_solution(city: City, solution_id: str, label: str, path: Path, out: Path) -> dict:
    inst = city.instance
    text = path.read_text(encoding="utf-8")
    routes = parse_solution(text)
    timeline, errors = build_timeline(inst, routes)
    if errors:
        raise ValueError(f"{display(path)}: " + "; ".join(errors[:5]))
    buffers = write_buffers(out / "solutions" / f"{solution_id}.steps.bin", {
        "offsets": ("uint32", timeline.offsets),
        "street": ("uint32", timeline.street),
        "enter": ("float32", timeline.enter),
        "flags": ("uint8", timeline.flags),
    })
    vehicles = []
    for v, route in enumerate(routes):
        vehicles.append({
            "type": inst.fleet[v],
            "steps": timeline.offsets[v + 1] - timeline.offsets[v],
            "end": timeline.end[v],
            "cleans": len(route.cleaned),
        })
    meta_path = out / "solutions" / f"{solution_id}.json"
    data = {
        "id": solution_id,
        "label": label,
        "source": display(path),
        "sourceSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),  # which file version
        "steps": len(timeline.street),
        "file": f"{solution_id}.steps.bin",
        "buffers": buffers,
        "vehicles": vehicles,
        "score": score(inst, routes),
    }
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def find_solutions(city_name: str) -> list[tuple[str, str, Path]]:
    """(id, label, path) of every registered algorithm that has a solution for this city."""
    return [
        (name, spec.label, solution_path(name, city_name))
        for name, spec in ALGORITHMS.items()
        if solution_path(name, city_name).exists()
    ]


def write_index(output: Path, dataset: Path) -> dict:
    catalog = read_json(dataset / "catalog.json")
    cities = []
    for entry in catalog["cities"]:
        directory = entry["directory"]
        city_file = output / directory / "city.json"
        solutions = read_json(city_file)["solutions"] if city_file.exists() else []
        cities.append({
            "directory": directory,
            "name": entry.get("requested_name") or directory,
            "country": entry.get("country"),
            "nodes": entry.get("nodes"),
            "streets": entry.get("streets"),
            "vehicles": entry.get("vehicles"),
            "timeLimit": entry.get("time_limit"),
            "available": bool(solutions),
        })
    cities.sort(key=lambda c: (not c["available"], c["nodes"] or 0))
    index = {"attribution": catalog.get("attribution"), "cities": cities}
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


def remove_stale(out: Path, keep: set[str]):
    """Delete exported files of solutions that no longer exist (e.g. a removed algorithm)."""
    folder = out / "solutions"
    if not folder.exists():
        return
    for path in folder.iterdir():
        solution_id = path.name.split(".")[0]
        if solution_id not in keep and path.suffix in (".json", ".bin"):
            path.unlink()


def convert(folder: Path, output: Path) -> dict:
    """Export the city and every algorithm solution found for it."""
    started = time.time()
    solutions = find_solutions(folder.name)
    if not solutions:
        raise ValueError(f"{folder.name}: no algorithm solution found; run "
                         f"build.py {folder.name} --algorithm greedy first")
    city = load_city(folder)
    report = check_city(city)
    if report["problems"]:
        raise ValueError(f"{city.name}: data checks failed: {report['problems']}")
    out = output / folder.name
    data, _ = export_city(city, out)
    buildings = out / "buildings.json"  # written by buildings.py
    data["buildings"] = read_json(buildings) if buildings.exists() else None
    for solution_id, label, path in solutions:
        sol = export_solution(city, solution_id, label, path, out)
        data["solutions"].append({"id": solution_id, "label": label})
        s = sol["score"]
        print(f"  {solution_id}: {sol['steps']:,} steps, score {s['value']:.6f} "
              f"(coverage {s['coverage']:.4f}, efficiency {s['efficiency']:.4f})")
    remove_stale(out, {solution_id for solution_id, _, _ in solutions})
    (out / "city.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{city.name}: {city.instance.nodes:,} junctions, {city.instance.streets:,} streets, "
          f"{len(city.instance.fleet)} vehicles, UTM {data['projection']['utm']} "
          f"-> {display(out)} in {time.time() - started:.1f} s")
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="*", help="city names (e.g. Presheva) or folders")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    failed = False
    for name in args.cities:
        try:
            convert(city_folder(name, args.dataset), args.out.resolve())
        except (ValueError, OSError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            failed = True
    write_index(args.out.resolve(), args.dataset.resolve())
    return 1 if failed else 0


def city_folder(name: str, dataset: Path = DATASET) -> Path:
    """Accept a city name ("Presheva") or a path to its folder."""
    path = Path(name)
    folder = path if (path / "instance.txt").exists() else dataset / name
    if not (folder / "instance.txt").exists():
        raise ValueError(f"no city {name!r}: expected {dataset / name}/instance.txt")
    return folder.resolve()


if __name__ == "__main__":
    sys.exit(main())
