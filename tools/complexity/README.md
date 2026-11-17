# CLIPP Performance Analyzer

The CLIPP Performance Analyzer measures how long each algorithm takes, how much memory it uses, and how both grow as the city gets bigger. It does this for every algorithm in the project and for every function those algorithms call.

The tool runs the selected algorithms on a set of instances, measures them and presents the results in a dashboard with charts and tables. For each algorithm and each function it also estimates how time and memory grow, in Big O terms, for example "time grows like n²".

The tool requires Python 3.10 or newer and uses only the standard library; no pip or npm packages are needed.

## Quick start

Run from the repository root:

```powershell
python -m tools.complexity serve
```

The dashboard opens in the browser at http://127.0.0.1:8765. Choose what to measure in the panel on the left and press **Run**; the charts update while the measurements run. Press Ctrl+C in the terminal to stop the server.

To measure from the terminal instead, the following command measures the default set and opens the result as a single HTML file, which can also be shared:

```powershell
python -m tools.complexity run --open
```

## The dashboard

**Left panel:**

- **Measure** (only with `serve`): three steps, followed by Run.
  1. *Algorithm*: one algorithm, or all of them.
  2. *Instances*: small (fast), small + medium (recommended), all including the big cities (very slow), or a single instance.
  3. *Measure*: time and memory only (quickest), plus functions (recommended), or also the memory of every function (slowest).

  Before a run starts, the panel shows an estimate of its duration. Long runs are marked with a red warning and require confirmation. Results already measured with unchanged code are reused rather than measured again.
- **Show results for**: All, Synthetic or Real cities. This filter only changes what is shown; it does not start a measurement.
- **Summary · all algorithms**: the fastest algorithm, the best score, and the number of measured algorithms and instances.

**Tabs on the right:**

- **Overview**: one chart (time, memory or score against instance size) and a table of how each algorithm grows.
- **Algorithms**: one algorithm in detail: the Big O of its time and memory, its chart, and the functions that take the most time.
- **Functions**: every function the algorithm calls, with its share of the solve time and the growth of its time and memory per call. Selecting a row shows the details.
- **Compare**: two algorithms side by side.

Hovering over a chart shows the exact values, selecting a legend entry hides that line, and **Table** shows the same data as a table.

## How the measurements work

Each measurement runs in a separate Python process, one after another. A crash or an endless loop in one algorithm therefore cannot affect the others, and concurrent runs cannot distort the timings.

There are four kinds of measurement. They run separately, because measuring memory or function calls slows the code down and would distort the timing:

| Measurement | Result | Method |
|---|---|---|
| Time | how long `solve()` takes (median of 3 runs) | `time.perf_counter()` |
| Memory | the peak memory allocated by Python while solving | `tracemalloc` |
| Functions | the number of calls and the time spent in each function | `cProfile` |
| Memory per function | the peak memory of one call of each function | `tracemalloc`, reset at every call |

Only solving is measured; reading the instance file is not. Every solution is checked with the project's validator and scored, so an invalid or failed solution appears in the dashboard together with its error message.

Results are stored and reused as long as nothing they depend on has changed: the algorithm's code and the modules it imports, the measuring code, and the instance file itself. When a new algorithm is added, only that algorithm is measured. When code or an instance changes, the dashboard marks the affected results as **outdated** until they are measured again.

## Adding a new algorithm

Register the algorithm in `ALGORITHMS` in `main.py`, like the existing ones. The tool reads that dictionary, so the new algorithm appears in the dashboard without any change to the tool. To measure only the new algorithm:

```powershell
python -m tools.complexity -a algorithm-name
```

Alternatively, select it in the dashboard and press Run.

## Commands

```powershell
python -m tools.complexity serve           # dashboard with a Run button
python -m tools.complexity run --open      # measure the default set, then open the result
python -m tools.complexity report --open   # rebuild the dashboard without measuring
python -m tools.complexity list            # algorithms and instances found by the tool
```

`serve` also accepts `--port 8766` (another port) and `--no-browser` (do not open the browser). Every command accepts `--out DIR` to use another results folder.

Options for `run`:

| Option | Effect |
|---|---|
| `-a greedy,beam-search` | only these algorithms |
| `-i instance_A,Presheva` | only these instances (any size) |
| `-f syntetic_generated` | only this group of instances |
| `--all` | include the big cities (by default, instances up to 6,000 streets) |
| `-m time,memory` | only some measurements: `time`, `memory`, `profile`, `fmemory` |
| `-r 5` | number of timing repetitions; the median is used (default 3) |
| `-t 600` | time limit per measurement, in seconds (default 300; ×3 for the function measurements) |
| `--fresh` | measure again even if a stored result exists |
| `--out DIR` | use another results folder |

The default set consists of the five synthetic instances plus Presheva and Ulqini.

## Files

The results are written to `data/output/complexity/`, which is not committed:

| File | Content |
|---|---|
| `dashboard.html` | the dashboard as a single file; works offline and can be shared |
| `report.md` | the same tables in Markdown, for a pull request or a report |
| `runs.csv`, `functions.csv` | the results as tables for a spreadsheet |
| `results.json` | the data behind the dashboard |
| `results.jsonl` | every individual measurement, as recorded |

The code in this folder:

| File | Role |
|---|---|
| `__main__.py` | the terminal commands |
| `algorithms.py` | finds the algorithms in `main.py` |
| `instances.py` | finds the instances in `data/input` |
| `worker.py` | performs the measurements, in a separate process |
| `runner.py` | runs the measurements one by one with a time limit and reuses stored results |
| `fit.py` | turns the measurements into a Big O estimate |
| `analysis.py` | collects everything the dashboard shows |
| `report.py`, `dashboard.py` | write the output files |
| `server.py` | the live dashboard behind `serve` |
| `ui/` | the dashboard page: `index.html`, `style.css`, and the scripts in `ui/js/`: shared helpers in `core/`, charts in `charts/`, one file per tab in `tabs/`, the Measure panel and progress in `live/`, and `main.js`, which starts the page |

The tests are in `tests/test_complexity_tool.py` (run them with `python -m unittest tests.test_complexity_tool`). A solver that is not yet registered in `main.py` can be added to `EXTRA` in `algorithms.py`.
