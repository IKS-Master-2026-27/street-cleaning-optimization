"""Consistency checks between the instance and the OSM files of one city.

Every assumption the converter and the browser rely on is checked here, so a
city that breaks one is reported instead of being drawn wrongly.
"""

from collections import Counter

from formats import City, sha256


def check_city(city: City, hashes: bool = False) -> dict:
    inst, mapping = city.instance, city.mapping
    problems = []

    def fail(message, count):
        if count:
            problems.append(f"{message}: {count}")

    node_ids = mapping["node_ids"]
    road_ids = mapping["road_ids"]
    coords = city.geography["node_coordinates"]
    fail("node_ids length differs from the junction count", int(len(node_ids) != inst.nodes))
    fail("node_coordinates length differs from the junction count", int(len(coords) != inst.nodes))
    fail("road_ids length differs from the street count", int(len(road_ids) != inst.streets))

    missing = mismatch = ends = self_loops = 0
    pairs = Counter()
    for k in range(inst.streets):
        roads = city.roads
        r = roads.get(road_ids[k])
        if r is None:
            missing += 1
            continue
        a, b = inst.a[k], inst.b[k]
        if roads.seconds[r] != inst.time[k] or roads.direction[r] != inst.way[k]:
            mismatch += 1
        if roads.u[r] != node_ids[a] or roads.v[r] != node_ids[b]:
            ends += 1
        line = roads.points(r)
        first, last = line[0], line[-1]
        if max(abs(first[0] - coords[a][0]), abs(first[1] - coords[a][1]),
               abs(last[0] - coords[b][0]), abs(last[1] - coords[b][1])) > 1e-6:
            ends += 1
        self_loops += a == b
        pairs[(min(a, b), max(a, b))] += 1
    fail("streets without a road feature", missing)
    fail("streets whose time or direction differ from the road", mismatch)
    fail("streets whose ends differ from the road's u/v or coordinates", ends)
    fail("self-loop streets", self_loops)
    fail("junction pairs joined by more than one street", sum(1 for c in pairs.values() if c > 1))

    report = {
        "city": city.name,
        "nodes": inst.nodes,
        "streets": inst.streets,
        "vehicles": len(inst.fleet),
        "types": dict(Counter(inst.type)),
        "silo": mapping.get("silo"),
        "demand": bool(mapping.get("demand")),
        "problems": problems,
    }
    if hashes:
        report["hash_mismatches"], report["crlf_only"] = [], []
        for name, digest in city.manifest.get("files", {}).items():
            path = city.folder / name
            if not path.exists() or sha256(path) == digest:
                continue
            if sha256(path, normalize_newlines=True) == digest:
                report["crlf_only"].append(name)  # same content, Windows line endings
            else:
                report["hash_mismatches"].append(name)
        problems.extend(f"hash mismatch: {n}" for n in report["hash_mismatches"])
    return report
