"""Assemble the dashboard: one self-contained HTML file (no CDN, works offline).

The page is ui/index.html, ui/style.css and the scripts in ui/js/, all
inlined here into one HTML file. With data the
page is a static snapshot; without data (live=True) it asks the local server
started by `python -m tools.complexity serve` and can start new runs.
"""

import json
from pathlib import Path

UI = Path(__file__).with_name("ui")


def _safe_json(data) -> str:
    # keep "</script>" and friends from closing the data tag
    return (json.dumps(data, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


# The dashboard scripts in ui/js/, joined in this order. Shared helpers come
# first; main.js starts the page and uses everything else, so it comes last.
SCRIPTS = (
    "core/state.js", "core/format.js", "core/tooltip.js", "core/dropdown.js", "core/data.js",
    "charts/line-chart.js", "charts/bar-chart.js", "charts/chart-card.js",
    "tabs/overview.js", "tabs/algorithms.js", "tabs/functions.js", "tabs/compare.js",
    "live/measure.js", "live/progress.js",
    "main.js",
)


def script_source() -> str:
    """All scripts in order, inside one function: they share one scope and
    nothing leaks into the page's globals."""
    parts = [(UI / "js" / name).read_text(encoding="utf-8") for name in SCRIPTS]
    return '(() => {\n"use strict";\n' + "\n".join(parts) + "\n})();\n"


# Markers in ui/index.html. They are HTML comments, which code formatters keep
# (an empty /* */ comment inside <style> or <script> can be removed by them).
STYLE_MARKER = "<!-- STYLES: dashboard.py puts ui/style.css here -->"
SCRIPT_MARKER = "<!-- SCRIPTS: dashboard.py puts the ui/js/ files here -->"
DATA_MARKER = "__BOOT__"


def render(data: dict | None = None, live: bool = False) -> str:
    page = (UI / "index.html").read_text(encoding="utf-8")
    for marker in (STYLE_MARKER, SCRIPT_MARKER, DATA_MARKER):
        if marker not in page:
            raise ValueError(f"ui/index.html lost the marker {marker!r}; put it back "
                             "or the dashboard has no styles, scripts or data")
    style = (UI / "style.css").read_text(encoding="utf-8")
    boot = {"live": live, "data": data}
    return (page.replace(STYLE_MARKER, f"<style>\n{style}\n</style>")
                .replace(SCRIPT_MARKER, f"<script>\n{script_source()}</script>")
                .replace(DATA_MARKER, _safe_json(boot)))
