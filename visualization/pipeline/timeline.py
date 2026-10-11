"""Rebuild each vehicle's timeline from a solution, and score it.

A solution only lists junctions and cleaned street ids. Every consecutive pair
of junctions is mapped to the one street joining them; the clock starts at 0 at
the depot and adds each street's time. A street in a vehicle's cleaned list is
marked as cleaned on that vehicle's first traversal of it (the file does not
say which traversal cleans, so this is an assumption shared with the browser).
"""

from dataclasses import dataclass, field

from formats import CAPACITIES, Instance, Route

REVERSE = 1   # step flag: driven b -> a
CLEANS = 2    # step flag: this traversal cleans the street


@dataclass
class Timeline:
    """Steps of all vehicles, flattened; vehicle v owns steps offsets[v]..offsets[v+1]."""
    offsets: list[int] = field(default_factory=lambda: [0])
    street: list[int] = field(default_factory=list)
    enter: list[float] = field(default_factory=list)
    flags: list[int] = field(default_factory=list)
    end: list[float] = field(default_factory=list)  # time the vehicle is back at the depot


def pair_lookup(inst: Instance) -> dict[tuple[int, int], int]:
    lookup = {}
    for k in range(inst.streets):
        a, b = inst.a[k], inst.b[k]
        lookup[(a, b)] = k
        if inst.way[k] == 2:
            lookup.setdefault((b, a), k)
    return lookup


def build_timeline(inst: Instance, routes: list[Route]) -> tuple[Timeline, list[str]]:
    """Return the timeline and a list of problems (empty for a valid route set)."""
    if len(routes) != len(inst.fleet):
        return Timeline(), [f"{len(routes)} routes for {len(inst.fleet)} vehicles"]
    lookup = pair_lookup(inst)
    timeline = Timeline()
    errors = []
    cleaned_by_any = set()
    for v, route in enumerate(routes):
        capacity = CAPACITIES[inst.fleet[v]]
        too_small = [k for k in route.cleaned if 0 <= k < inst.streets and inst.req[k] > capacity]
        if too_small:
            errors.append(f"vehicle {v} ({inst.fleet[v]}, capacity {capacity}) cleans streets "
                          f"needing more: {too_small[:5]}")
        cleaned_by_any.update(route.cleaned)
        js = route.junctions
        if js and (js[0] != inst.depot or js[-1] != inst.depot):
            errors.append(f"vehicle {v}: route does not start and end at the depot")
        to_clean = set(route.cleaned)
        clock = 0.0
        for i in range(len(js) - 1):
            k = lookup.get((js[i], js[i + 1]))
            if k is None:
                errors.append(f"vehicle {v}: no street from {js[i]} to {js[i + 1]}")
                break
            flag = 0 if inst.a[k] == js[i] else REVERSE
            if k in to_clean:
                flag |= CLEANS
                to_clean.discard(k)
            timeline.street.append(k)
            timeline.enter.append(clock)
            timeline.flags.append(flag)
            clock += inst.time[k]
        if to_clean:
            errors.append(f"vehicle {v}: cleans streets it never drives: {sorted(to_clean)[:5]}")
        if clock > inst.time_limit:
            errors.append(f"vehicle {v}: {clock:.0f} s exceeds the time limit {inst.time_limit} s")
        timeline.offsets.append(len(timeline.street))
        timeline.end.append(clock)
    uncleaned = [k for k in range(inst.streets) if inst.type[k] == "M" and k not in cleaned_by_any]
    if uncleaned:
        errors.append(f"{len(uncleaned)} mandatory streets are not cleaned, e.g. {uncleaned[:5]}")
    return timeline, errors


def score(inst: Instance, routes: list[Route]) -> dict:
    """The CLIPP score, same formula as clipp/scoring.py and the external validator."""
    cleaned = set()
    waste = 0.0
    for v, route in enumerate(routes):
        capacity = CAPACITIES[inst.fleet[v]]
        for k in route.cleaned:
            if inst.type[k] in ("M", "O"):
                cleaned.add(k)
                waste += (capacity - inst.req[k]) * inst.length[k] / 1000
    eligible = [k for k in range(inst.streets) if inst.type[k] in ("M", "O")]
    max_length = sum(inst.length[k] for k in eligible)
    max_waste = sum((30 - inst.req[k]) * inst.length[k] / 1000 for k in eligible)
    length = sum(inst.length[k] for k in cleaned)
    coverage = length / max_length if max_length else 0.0
    efficiency = 1.0 - waste / max_waste if max_waste else 1.0
    mandatory = [k for k in range(inst.streets) if inst.type[k] == "M"]
    return {
        "value": inst.alpha * coverage + (1 - inst.alpha) * efficiency,
        "coverage": coverage,
        "efficiency": efficiency,
        "cleanedLength": length,
        "maxLength": max_length,
        "waste": waste,
        "maxWaste": max_waste,
        "cleanedMandatory": sum(1 for k in mandatory if k in cleaned),
        "mandatory": len(mandatory),
        "cleanedOptional": sum(1 for k in cleaned if inst.type[k] == "O"),
        "optional": sum(1 for k in eligible if inst.type[k] == "O"),
    }
