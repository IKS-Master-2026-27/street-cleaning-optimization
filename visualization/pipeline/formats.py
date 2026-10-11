"""Readers for one real-city folder: the CLIPP instance, its solutions and the OSM files.

The pipeline keeps its own small parser instead of importing ``clipp`` so the
visualization can be maintained separately from the solver.
"""

from dataclasses import dataclass
from array import array
import hashlib
import json
from pathlib import Path

CAPACITIES = {"S": 10, "M": 20, "L": 30}
STREET_TYPES = "MOC"  # index stored in the browser files: 0 = M, 1 = O, 2 = C


@dataclass
class Instance:
    nodes: int
    time_limit: int
    depot: int
    alpha: float
    a: list[int]
    b: list[int]
    way: list[int]
    time: list[int]
    length: list[int]
    type: list[str]
    req: list[int]
    fleet: list[str]

    @property
    def streets(self) -> int:
        return len(self.a)


@dataclass
class Route:
    junctions: list[int]
    cleaned: list[int]


@dataclass
class City:
    folder: Path
    instance: Instance
    mapping: dict          # instance.json
    manifest: dict         # manifest.json
    roads: "Roads"         # the road features the instance uses
    geography: dict        # geography.json

    @property
    def name(self) -> str:
        return self.manifest.get("requested_name") or self.folder.name


def read_json(path: Path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def parse_instance(text: str) -> Instance:
    lines = text.splitlines()
    n, m, t, c, s, w = lines[0].split()
    n, m, t, c, s = map(int, (n, m, t, c, s))
    inst = Instance(n, t, s, float(w), [], [], [], [], [], [], [], [])
    for k in range(m):
        a, b, way, time, length, kind, req = lines[1 + k].split()
        inst.a.append(int(a))
        inst.b.append(int(b))
        inst.way.append(int(way))
        inst.time.append(int(time))
        inst.length.append(int(length))
        inst.type.append(kind)
        inst.req.append(int(req))
    inst.fleet = lines[1 + m].split()
    if len(inst.fleet) != c:
        raise ValueError(f"fleet line has {len(inst.fleet)} vehicles, header says {c}")
    return inst


def parse_solution(text: str) -> list[Route]:
    """Validator format: vehicle count, then per vehicle: steps, junctions, cleaned ids."""
    lines = text.splitlines()
    count = int(lines[0])
    routes = []
    pos = 1
    for v in range(count):
        steps = int(lines[pos])
        junctions = [int(x) for x in lines[pos + 1].split()]
        cleaned_line = lines[pos + 2] if pos + 2 < len(lines) else ""
        cleaned = [int(x) for x in cleaned_line.split()]
        if len(junctions) != steps + 1:
            raise ValueError(f"vehicle {v}: {steps} steps but {len(junctions)} junctions")
        routes.append(Route(junctions, cleaned))
        pos += 3
    return routes


def iter_features(path: Path, chunk: int = 1 << 22):
    """Yield the features of a GeoJSON FeatureCollection one at a time.

    The largest cities' road files are hundreds of MB; loading them whole into
    Python takes several GB. This decodes one feature at a time from a moving
    window of the file instead.
    """
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as source:
        buffer = source.read(chunk)
        start = buffer.find('"features"')
        if start < 0:
            raise ValueError(f"{path}: no features list")
        pos = buffer.index("[", start) + 1
        while True:
            while True:  # skip separators, reading more text when needed
                while pos < len(buffer) and buffer[pos] in " \t\r\n,":
                    pos += 1
                if pos < len(buffer):
                    break
                more = source.read(chunk)
                if not more:
                    return
                buffer, pos = more, 0
            if buffer[pos] == "]":
                return
            try:
                feature, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                more = source.read(chunk)  # the feature continues past the window
                if not more:
                    raise
                buffer, pos = buffer[pos:] + more, 0
                continue
            yield feature
            pos = end
            if pos > chunk:
                buffer, pos = buffer[pos:], 0


class Roads:
    """The road features the instance uses, kept in compact arrays."""

    def __init__(self, path: Path, wanted):
        wanted = set(wanted)
        self.index = {}  # road id -> position
        self.u, self.v, self.names, self.highways = [], [], [], []
        self.maxspeed, self.lanes = [], []  # raw OSM tags, used by the SUMO network (sumo_run.py)
        self.direction = array("b")
        self.seconds = array("l")
        self.meters = array("d")
        self.offsets = array("L", [0])
        self.lonlat = array("d")  # lon, lat, lon, lat, ...
        for feature in iter_features(path):
            p = feature["properties"]
            if p["id"] not in wanted:
                continue
            self.index[p["id"]] = len(self.u)
            tags = p.get("tags", {})
            self.u.append(p["u"])
            self.v.append(p["v"])
            self.names.append(tags.get("name"))
            self.highways.append(str(tags.get("highway", "road")))
            self.maxspeed.append(tags.get("maxspeed"))
            self.lanes.append(tags.get("lanes"))
            self.direction.append(int(p["direction"]))
            self.seconds.append(p["seconds"])
            self.meters.append(p["meters"])
            for lon, lat in feature["geometry"]["coordinates"]:
                self.lonlat.extend((lon, lat))
            self.offsets.append(len(self.lonlat) // 2)

    def get(self, road_id):
        """Position of the road with this id, or None."""
        return self.index.get(road_id)

    def points(self, i):
        """[(lon, lat), ...] of road position i."""
        flat = self.lonlat[2 * self.offsets[i]:2 * self.offsets[i + 1]]
        return list(zip(flat[0::2], flat[1::2]))


def load_city(folder: Path) -> City:
    folder = Path(folder)
    instance = parse_instance((folder / "instance.txt").read_text(encoding="utf-8"))
    mapping = read_json(folder / "instance.json")
    geography = read_json(folder / "geography.json")
    # only the count of excluded ways is used; the list itself is large
    geography["excluded_count"] = len(geography.pop("excluded", []))
    return City(
        folder=folder,
        instance=instance,
        mapping=mapping,
        manifest=read_json(folder / "manifest.json"),
        roads=Roads(folder / "roads.geojson", mapping["road_ids"]),
        geography=geography,
    )


def sha256(path: Path, normalize_newlines: bool = False) -> str:
    """Hash a file; with normalize_newlines, CRLF is hashed as LF (Git autocrlf checkouts)."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        if normalize_newlines:
            digest.update(source.read().replace(b"\r\n", b"\n"))
        else:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                digest.update(chunk)
    return digest.hexdigest()
