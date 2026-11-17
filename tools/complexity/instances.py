"""Find the instances to measure on, reading only their header line."""

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from . import ROOT

INPUT = ROOT / "data" / "input"
SMALL_MAX_STREETS = 1500    # synthetic A-E and Presheva: seconds to minutes
DEFAULT_MAX_STREETS = 6000  # adds Ulqini; bigger cities can take hours


def size_sets(streets: int) -> list[str]:
    """The Run panel's instance groups this instance belongs to."""
    if streets <= SMALL_MAX_STREETS:
        return ["small", "default", "large"]
    if streets <= DEFAULT_MAX_STREETS:
        return ["default", "large"]
    return ["large"]


@dataclass(frozen=True)
class InstanceInfo:
    name: str
    family: str
    path: str  # relative to the repository root
    junctions: int
    streets: int
    vehicles: int
    max_time: int

    def to_dict(self) -> dict:
        return asdict(self)


_HASHES: dict[tuple[str, int, int], str] = {}


def content_hash(path: str | Path) -> str:
    """Hash of the instance file's bytes, so edited inputs are measured again.

    Cached per (path, size, mtime) so repeated plans do not re-read big files.
    """
    full = Path(path) if Path(path).is_absolute() else ROOT / path
    stat = full.stat()
    key = (str(full), stat.st_size, stat.st_mtime_ns)
    if key not in _HASHES:
        digest = hashlib.sha1()
        with open(full, "rb") as source:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                digest.update(chunk)
        _HASHES[key] = digest.hexdigest()[:12]
    return _HASHES[key]


def read_header(path: Path) -> tuple[int, int, int, int]:
    with open(path, encoding="utf-8") as source:
        parts = source.readline().split()
    n, m, t, c = map(int, parts[:4])
    return n, m, t, c


def _info(path: Path, name: str, family: str) -> InstanceInfo | None:
    try:
        n, m, t, c = read_header(path)
    except (OSError, ValueError):
        return None
    return InstanceInfo(name, family, path.relative_to(ROOT).as_posix(), n, m, c, t)


def discover(root: Path = INPUT) -> list[InstanceInfo]:
    """Every instance under data/input, smallest first.

    data/input/<family>/*.txt are single-file instances, and
    data/input/<family>/<City>/instance.txt are city instances.
    """
    found = []
    if not root.exists():
        return found
    for family in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(family.glob("*.txt")):
            if path.name.endswith("_solution.txt") or path.name.startswith("instance."):
                continue
            info = _info(path, path.stem, family.name)
            if info:
                found.append(info)
        for path in sorted(family.glob("*/instance.txt")):
            info = _info(path, path.parent.name, family.name)
            if info:
                found.append(info)
    found.sort(key=lambda i: (i.streets, i.junctions, i.name))
    return found


def select(available: list[InstanceInfo], names: list[str] | None = None,
           families: list[str] | None = None,
           max_streets: int | None = DEFAULT_MAX_STREETS) -> list[InstanceInfo]:
    chosen = available
    if names:
        wanted = {n.lower() for n in names}
        chosen = [i for i in chosen if i.name.lower() in wanted
                  or f"{i.family}/{i.name}".lower() in wanted]
        missing = wanted - {i.name.lower() for i in chosen} - {
            f"{i.family}/{i.name}".lower() for i in chosen}
        if missing:
            raise ValueError(f"unknown instance(s): {', '.join(sorted(missing))}")
        return chosen  # explicit names ignore the size cap
    if families:
        chosen = [i for i in chosen if i.family in families]
    if max_streets is not None:
        chosen = [i for i in chosen if i.streets <= max_streets]
    return chosen
