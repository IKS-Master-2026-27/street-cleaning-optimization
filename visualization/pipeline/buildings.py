"""3D buildings for a city from Microsoft's Global ML Building Footprints.

Usage (from the repository root; build.py also runs it when needed):

    python visualization/pipeline/buildings.py Presheva

OpenStreetMap is often incomplete for buildings (Presheva's centre has ~51
mapped buildings per km^2), so the footprints come from Microsoft's open
dataset (ODbL, https://github.com/microsoft/GlobalMLBuildingFootprints), which
has ~600 there. The dataset is split into zoom-9 map tiles ("quadkeys") per
country; every tile file covering the city is downloaded once into
pipeline/cache/ (git-ignored). Only buildings inside the city boundary are kept.

The footprints have no heights, so heights are estimated from the footprint
area (bigger footprint, more floors, 3 m per floor) with a small deterministic
variation; the app says they are estimated.

Writes visualization/public/data/<City>/buildings.bin and buildings.json, which
convert.py links into city.json.
"""

import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import sys
import time
import urllib.request

from binfile import write_buffers
from formats import read_json
from projection import projector_for

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / "cache" / "buildings"
OUTPUT = ROOT / "visualization" / "public" / "data"
DATASET = ROOT / "data" / "input" / "real_instances"
LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
SOURCE = "Microsoft Global ML Building Footprints (ODbL)"
ZOOM = 9  # the dataset's tile level


def download(url: str, path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "clipp-3d-replay (course project)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = response.read()
            break
        except OSError as exc:
            if attempt == 2:
                raise OSError(f"download failed: {url}: {exc}") from exc
            time.sleep(5 * (attempt + 1))
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    return path


def tile(lon: float, lat: float) -> tuple[int, int]:
    n = 2 ** ZOOM
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return int((lon + 180) / 360 * n), int(min(max(y, 0), n - 1))


def quadkey(x: int, y: int) -> str:
    return "".join(str(((x >> i) & 1) + 2 * ((y >> i) & 1)) for i in range(ZOOM - 1, -1, -1))


def inside_ring(x: float, y: float, ring) -> bool:
    result = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            result = not result
        j = i
    return result


def inside(lon: float, lat: float, geometry: dict) -> bool:
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for outer, *holes in polygons:
        if inside_ring(lon, lat, outer) and not any(inside_ring(lon, lat, h) for h in holes):
            return True
    return False


def estimated_height(area: float, x: float, y: float) -> float:
    floors = 1 if area < 60 else 2 if area < 160 else 3 if area < 450 else 4 if area < 1200 else 6
    jitter = (math.sin(x * 12.9898 + y * 78.233) * 43758.5453) % 1  # stable per building
    return round(floors * 3.0 + 0.6 + jitter * 1.8, 1)


def ring_area(points) -> float:
    return abs(sum(points[i][0] * points[i - 1][1] - points[i - 1][0] * points[i][1]
                   for i in range(len(points)))) / 2


def build_buildings(folder: Path, output: Path = OUTPUT) -> dict:
    started = time.time()
    geography = read_json(folder / "geography.json")
    coords = geography["node_coordinates"]
    boundary = geography["boundary"]["geometry"]
    project = projector_for(coords)  # same projection as the streets (convert.py)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    margin = 0.01
    x0, y1 = tile(min(lons) - margin, min(lats) - margin)
    x1, y0 = tile(max(lons) + margin, max(lats) + margin)
    wanted = {quadkey(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}

    links = download(LINKS_URL, CACHE / "dataset-links.csv")
    with open(links, encoding="utf-8") as source:
        rows = [r for r in csv.DictReader(source) if r["QuadKey"] in wanted]
    if not rows:
        raise ValueError(f"{folder.name}: no building tiles cover this city")

    offsets, points, heights = [0], [], []
    for row in rows:
        path = download(row["Url"], CACHE / f"{row['QuadKey']}-{row['Location']}.csv.gz")
        with gzip.open(path, "rt", encoding="utf-8") as source:
            for line in source:
                feature = json.loads(line)
                geometry = feature["geometry"]
                if geometry["type"] != "Polygon":
                    continue
                ring = geometry["coordinates"][0]
                lon = sum(p[0] for p in ring) / len(ring)
                lat = sum(p[1] for p in ring) / len(ring)
                if not (min(lons) <= lon <= max(lons) and min(lats) <= lat <= max(lats)):
                    continue
                if not inside(lon, lat, boundary):
                    continue
                projected = [project(p[0], p[1]) for p in ring]
                if projected[0] == projected[-1]:
                    projected.pop()  # the browser closes the ring itself
                if len(projected) < 3:
                    continue
                given = feature.get("properties", {}).get("height", -1)
                cx = sum(p[0] for p in projected) / len(projected)
                cy = sum(p[1] for p in projected) / len(projected)
                heights.append(given if given and given > 0
                               else estimated_height(ring_area(projected), cx, cy))
                for x, y in projected:
                    points.extend((round(x, 2), round(y, 2)))
                offsets.append(len(points) // 2)

    out = output / folder.name
    buffers = write_buffers(out / "buildings.bin", {
        "offsets": ("uint32", offsets),
        "points": ("float32", points),
        "height": ("float32", heights),
    })
    meta = {"count": len(heights), "file": "buildings.bin", "buffers": buffers,
            "source": SOURCE, "heights": "estimated from footprint area"}
    (out / "buildings.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"{folder.name}: {len(heights):,} buildings from {len(rows)} tile file(s) "
          f"in {time.time() - started:.1f} s")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="+", help="city names (e.g. Presheva)")
    args = parser.parse_args(argv)
    for name in args.cities:
        folder = Path(name) if (Path(name) / "geography.json").exists() else DATASET / name
        build_buildings(folder.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
