"""Audit city folders before converting them.

Usage (from the repository root):

    python visualization/pipeline/audit.py                 # every city in the dataset
    python visualization/pipeline/audit.py data/input/real_instances/Prishtina --json audit.json

Checks file hashes against manifest.json and every assumption the viewer makes
(see checks.py), and reports which optional fields (silo, demand) are filled.
Large cities load several hundred MB of GeoJSON, so audit them one at a time.
"""

import argparse
import json
from pathlib import Path
import sys

from checks import check_city
from convert import DATASET
from formats import load_city


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="*", type=Path)
    parser.add_argument("--json", type=Path, help="also write the full report to this file")
    args = parser.parse_args(argv)
    folders = args.cities or sorted(p for p in DATASET.iterdir() if (p / "instance.txt").exists())
    reports = []
    for folder in folders:
        report = check_city(load_city(folder), hashes=True)
        reports.append(report)
        status = "OK" if not report["problems"] else "; ".join(report["problems"])
        if report["crlf_only"]:
            status += f" (CRLF line endings: {', '.join(report['crlf_only'])})"
        print(f"{report['city']:<14} {report['nodes']:>8,} junctions {report['streets']:>8,} streets "
              f"{report['vehicles']:>4} vehicles  types {report['types']}  silo={report['silo']} "
              f"demand={report['demand']}  {status}")
    if args.json:
        args.json.write_text(json.dumps(reports, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if any(r["problems"] for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
