"""Write results.json, report.md, runs.csv, functions.csv and dashboard.html."""

import csv
import json
from pathlib import Path

from . import OUTPUT
from .analysis import ALL, build
from .dashboard import render
from .runner import load_records


def _bytes(value) -> str:
    if value is None:
        return "–"
    for unit in ("B", "kB", "MB", "GB"):
        if abs(value) < 1000 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return str(value)


def _seconds(value) -> str:
    if value is None:
        return "–"
    if value < 1e-3:
        return f"{value * 1e6:.0f} µs"
    if value < 1:
        return f"{value * 1e3:.1f} ms"
    return f"{value:.2f} s"


def _growth(block: dict, family: str = ALL) -> str:
    fit = (block.get(family) or {}).get("fit") or {}
    if not fit.get("model"):
        return fit.get("reason") or "–"
    return f"{fit['model']} (n^{fit['slope']:.2f})"


def default_family(data: dict) -> str:
    """The family with the most instances (as the dashboard does), else all."""
    counts: dict[str, int] = {}
    for instance in data["instances"]:
        counts[instance["family"]] = counts.get(instance["family"], 0) + 1
    if len(counts) < 2:
        return ALL
    family = max(counts, key=counts.get)
    return family if counts[family] >= 3 else ALL


def markdown(data: dict) -> str:
    meta = data["meta"]
    family = default_family(data)
    fitted = "all instances" if family == ALL else f"the {family} instances"
    lines = [
        "# CLIPP Performance Analyzer report", "",
        f"Generated {meta['generated']} from {meta['measurements']} measurements; "
        f"revision {meta['revision']}; Python {meta['python']} on {meta['platform']}. "
        f"{meta['size_variable']}. Growth is fitted on {fitted}, because instance families "
        f"differ in more than size. Open dashboard.html for the interactive version.", "",
        "## Algorithms", "",
        "Measured Big O: the growth class that best fits the measurements, with the fitted "
        "exponent in brackets.", "",
        "| Algorithm | Time grows | Memory grows |",
        "|---|---|---|",
    ]
    for a in data["algorithms"]:
        lines.append(f"| {a['name']} | {_growth(a['time'], family)} | {_growth(a['memory'], family)} |")
    names = [a["name"] for a in data["algorithms"]]
    for title, field, fmt in (("Solve time (median)", "seconds", _seconds),
                              ("Peak traced memory while solving", "peak_bytes", _bytes),
                              ("Score", "score", lambda v: "–" if v is None else f"{v:.6f}")):
        lines += ["", f"## {title}", "",
                  "| Instance | Family | Streets | " + " | ".join(names) + " |",
                  "|---|---|---|" + "---|" * len(names)]
        for instance in data["instances"]:
            cells = []
            for a in data["algorithms"]:
                run = next((r for r in a["runs"] if r["path"] == instance["path"]), None)
                if run is None:
                    cells.append("")
                elif run["status"] != "ok" and run.get(field) is None:
                    cells.append(run["status"])
                else:
                    cells.append(fmt(run.get(field)))
            lines.append(f"| {instance['name']} | {instance['family']} | {instance['streets']} | "
                         + " | ".join(cells) + " |")
    for a in data["algorithms"]:
        functions = [f for f in data["functions"].get(a["name"], []) if not f["helper"]][:25]
        if not functions:
            continue
        lines += ["", f"## Functions: {a['name']}", "",
                  "| Function | Share | Calls grow | Time/call grows | Memory/call grows |",
                  "|---|---|---|---|---|"]
        for f in functions:
            share = "–" if f["share"] is None else f"{f['share'] * 100:.1f}%"
            lines.append(f"| `{f['key']}` | {share} | {_growth(f['calls'], family)} | "
                         f"{_growth(f['per_call'], family)} | {_growth(f['memory'], family)} |")
    return "\n".join(lines) + "\n"


def _csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(header)
        writer.writerows(rows)


def write_all(algorithms: dict, folder: Path = OUTPUT) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    data = build(load_records(folder), algorithms)
    (folder / "results.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (folder / "report.md").write_text(markdown(data), encoding="utf-8")
    _csv(folder / "runs.csv",
         ["algorithm", "instance", "family", "junctions", "streets", "status", "seconds",
          "peak_bytes", "max_rss_bytes", "score"],
         [[a["name"], r["instance"], r["family"], r["junctions"], r["streets"], r["status"],
           r["seconds"], r["peak_bytes"], r["max_rss_bytes"], r["score"]]
          for a in data["algorithms"] for r in a["runs"]])
    rows = []
    for name, functions in data["functions"].items():
        for f in functions:
            fit = lambda block: (block.get(ALL) or {}).get("fit") or {}
            rows.append([name, f["key"], f["share"], fit(f["calls"]).get("model"),
                         fit(f["per_call"]).get("model"), fit(f["per_call"]).get("slope"),
                         fit(f["memory"]).get("model"), fit(f["memory"]).get("slope")])
    _csv(folder / "functions.csv",
         ["algorithm", "function", "share", "calls_model", "time_per_call_model",
          "time_per_call_slope", "memory_model", "memory_slope"], rows)
    (folder / "dashboard.html").write_text(render(data), encoding="utf-8")
    return data
