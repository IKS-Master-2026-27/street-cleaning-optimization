# CLIPP 3D Replay

A 3D simulator of street cleaning on the real street map of a city. It works in
three steps:

1. it takes the instance generated for a city (`data/input/real_instances/<City>/`),
2. it runs one of the team's algorithms on it to get a solution (now: the greedy
   in `clipp/`),
3. it shows the S/M/L trucks driving that solution in 3D, turning streets green
   as they clean them, for the instance's whole time limit.

Steps 1 and 2 are one terminal command per city (`build.py`); step 3 is the web
app. It works the same for every city, from Presheva (744 junctions) up to Sydney
(255,428 junctions, 697 trucks). Nothing in the code is specific to one city.

There are two timings, switched in the app:

- **Exact** (default): trucks move on the solver's own timeline, each street's time
  from the instance added from 0 at the depot. This is exactly what the validator
  scores.
- **Realistic (SUMO)**: the same routes driven in [Eclipse SUMO](https://eclipse.dev/sumo/),
  a traffic simulator, with acceleration, junction rules and optional background
  traffic. It shows how much longer each truck would take on real roads and
  which trucks would miss the time limit.

The work is split into an offline Python pipeline and a browser app. The browser
only loads the exported files; it never reads the raw dataset or runs an algorithm.

```text
visualization/
├── pipeline/              Python 3.10+, standard library only
│   ├── build.py           instance -> algorithm -> files for the browser (the main command)
│   ├── algorithms.py      the algorithms the tool can run; add new ones here
│   ├── convert.py         city + its solutions -> files for the browser (used by build.py)
│   ├── sumo_run.py        realistic mode: drives a solution in Eclipse SUMO (used by build.py --sumo)
│   ├── buildings.py       3D building footprints for a city (used by build.py)
│   ├── audit.py           checks a city folder (hashes, ids, geometry)
│   ├── formats.py         parsers for instance.txt, solutions and the OSM files
│   ├── projection.py      lon/lat -> UTM metres around the city centre
│   ├── timeline.py        rebuilds each truck's timeline and the CLIPP score
│   ├── checks.py          consistency checks shared by audit and convert
│   └── binfile.py         typed arrays -> one binary file
├── src/                   Three.js app (Vite)
│   ├── loaders/           city, buildings and solution files; uploaded solutions
│   ├── playback/          street geometry, vehicle positions, cleaning events, live score, analysis
│   ├── scene/             ground, streets, buildings, trees, trucks, route, spray, daylight, picking
│   └── ui/                side panel, details card, analysis drawer, styles
├── public/data/           pipeline output (one folder per city + index.json)
└── index.html
```

## Quick start

From the repository root:

```powershell
# 1. Run the algorithm on a city (skipped when its solution already exists)
#    and prepare the app; add --buildings for 3D buildings
python visualization/pipeline/build.py Presheva

# 2. Optional: the realistic mode in Eclipse SUMO, with background traffic
python visualization/pipeline/build.py Presheva --sumo --traffic 1

# 3. Start the app
cd visualization
npm install
npm run dev
```

Then open http://localhost:5173. The URL keeps the city and solution, for
example `http://localhost:5173/#Presheva/greedy`.

`build.py` saves the algorithm's solution in the validator's format at
`data/output/<algorithm>/<City>_instance_solution.txt` (for example
`data/output/greedy/Presheva_instance_solution.txt`), checks it with `clipp`'s
validator, and reuses it next time. Use `--rerun` after the algorithm changes.

Requirements: Python 3.10+ and Node.js 16+ (Vite 4). The pipeline uses no
third-party Python packages. The realistic mode also needs
[Eclipse SUMO](https://eclipse.dev/sumo/) with `SUMO_HOME` set (tested with 1.27.1).

Built so far: **all 10 cities**, with the team's greedy solutions
(`data/output/greedy/<City>_instance_solution.txt`) and without buildings;
Presheva, Ulqini and Prishtina also have a SUMO run (`--traffic 1`). The
road files are read one street at a time, so even the largest stay light:

| City | Streets | Route steps | Build time | Peak memory | App data | Loads in browser |
|---|---:|---:|---:|---:|---:|---:|
| Vienna | 56,787 | 98,675 | 7 s | 107 MB | 4.5 MB | about 3 s |
| New York | 182,700 | 308,600 | 33 s | 268 MB | 14 MB | about 3 s |
| Johannesburg | 204,280 | 303,826 | 39 s | 282 MB | 16 MB | about 4 s |
| Sydney | 316,886 | 542,301 | 52 s | 422 MB | 26 MB | about 7 s |

The largest cities draw hundreds of thousands of street ribbons, so they need a
real graphics card to play smoothly; hiding street types under **Show** helps on
weak laptops.

## Adding a new algorithm

Every algorithm's solutions live in `data/output/<algorithm>/<City>_instance_solution.txt`,
in the validator's format (the greedy's are in `data/output/greedy/`). The app
shows, for the open city, every **registered** algorithm that has such a file.

### 1. Write the algorithm

A Python function that takes a `clipp.parser.Instance` and returns a
`clipp.solver.Solution`, like the greedy's `clipp.solver.solve`:

```python
# clipp/better.py
from clipp.parser import Instance
from clipp.solver import Solution, VehicleRoute

def solve(instance: Instance) -> Solution:
    ...  # one VehicleRoute per truck, in the order of the fleet line,
         # starting and ending at the depot
```

`build.py` checks the result with `clipp/validator.py` and writes it with
`clipp/output.py`, so an invalid solution is never saved.

### 2. Register it

Add one line to `ALGORITHMS` in `visualization/pipeline/algorithms.py`:

```python
ALGORITHMS = {
    "greedy": Algorithm("Greedy", "clipp.solver", "solve"),
    "better": Algorithm("Better heuristic", "clipp.better", "solve"),  # name shown in the app, module, function
}
```

The key (`better`) is the algorithm's id: the folder under `data/output/` and the
value of `--algorithm`.

### 3. Build it for a city

```powershell
python visualization/pipeline/build.py Prishtina --algorithm better
# with its realistic mode too:
python visualization/pipeline/build.py Prishtina --algorithm better --sumo --traffic 1
```

This runs the algorithm, saves `data/output/better/Prishtina_instance_solution.txt`,
and adds **Better heuristic** to the app's **Solution** list next to **Greedy**.
Refresh the page to see it. Solutions already built (the greedy's, and its SUMO
run) are kept.

### If the solution file comes from someone else

When another group sends you the solution file instead of the code, the
algorithm does not need to run:

1. Register the algorithm id in `algorithms.py` as above (the module and function
   are only used when solving).
2. Save the file as `data/output/<id>/<City>_instance_solution.txt`, for example
   `data/output/better/Prishtina_instance_solution.txt`.
3. Run `python visualization/pipeline/build.py Prishtina --algorithm better`. It
   finds the file, checks it and exports it without solving (`--rerun` would solve
   again and overwrite it).

A file in a folder whose id is not registered in `algorithms.py` is ignored.

### Upload or build?

| | **Upload** button in the app | `build.py --algorithm <id>` |
|---|---|---|
| What you need | only the solution file | the algorithm registered in `algorithms.py` (and its code, or its solution file) |
| Where it is processed | in the browser, in about a second | by the Python pipeline |
| Checks and score | yes, same rules as the validator | yes: `clipp`'s validator when it solves, and the pipeline's own checks (same rules) on every file |
| Saved? | **no**: only in that browser tab; gone after a reload, closing the app or switching city | **yes**: in `data/output/<id>/` and `public/data/<City>/`, for everyone who opens the app |
| Realistic (SUMO) mode | no | yes, with `--sumo` |
| Use it for | a quick look at a file someone sent you | solutions to keep, compare and present |

## Using the app

| Action | How |
|---|---|
| Play / pause | ▶ button or <kbd>Space</kbd>; speed from ×1 to ×10000 |
| Jump in time | drag the timeline; for an uploaded solution that runs past the time limit T, a yellow mark shows T |
| Pan, rotate, zoom | left drag, right drag, mouse wheel |
| See or set how far you are zoomed | the small box at the bottom left of the map shows how wide the view is (e.g. "≈ 850 m"); choose a width from its list (50 m … 10 km, or the whole city), or use its **−** / **+** buttons or the **−** / **+** keys to halve or double it |
| Street or truck details | hover for a tooltip, click for the details card |
| Focus on a truck | click a truck or a row in the truck list: other trucks fade, its route shows the part already driven (dark) and still ahead (faint blue), and the card shows progress bars for its route, its cleaning and its place in the shift |
| Follow a truck | after selecting it, **Follow** or <kbd>F</kbd>: the camera moves with it and you can still rotate and zoom |
| Back to the whole city from above | **Top view** in the time bar or <kbd>R</kbd> |
| Analyse the solution | **Analysis** in the time bar or <kbd>A</kbd> (see below) |
| See where trucks drive repeatedly | **Times driven** under **Show** colours every street by how often trucks drive it (pale red = once, then redder up to deep red = 4 times or more, light grey = never) |
| Exact or realistic timing | the **Exact / Realistic (SUMO)** switch under **Solution** (greyed out for a city without a SUMO run); the line below it gives the median truck delay and how many trucks miss the time limit, and the truck list's **Δ SUMO** column each truck's extra time |
| Hide street types, truck types or the SUMO background cars | the checkboxes under **Show** |
| Make trucks bigger or smaller | the **Truck size** slider under **Show**: up close trucks stay near real size, and they grow by this factor as you zoom out (remembered by the browser) |
| Make roads wider or narrower | the **Road width** slider under **Show** (×2 by default; remembered by the browser) |
| Hide buildings, trees, water spray or day/night | the **Buildings**, **Trees**, **Water spray** and **Time of day** checkboxes under **Show** |
| Check a solution file quickly | **Upload** (or drop the file on the page) a solution in the validator format for the open city; it is not saved (see "Upload or build?") |

Colours follow the course slides: red = mandatory, blue = optional, grey =
connector, green = cleaned, yellow = depot. Trucks are cyan (S), orange (M) and
magenta (L); they are bright while cleaning, paler while only driving, and grey
once back at the depot. Selecting a truck turns the other trucks grey, keeps it
in full colour and outlines its route. A freshly cleaned street shines pale blue
("wet") for about 15 simulated minutes, and trucks spray water from their front
corners while they clean.

The scene is styled as a white city model: light ground, white buildings, toy-like
glossy trucks (cab, water tank, wheels, roof beacon) and bubble cars for the SUMO
traffic. The trees are decorative: the dataset has none, so they are placed the
same way every time along both sides of the streets, never on a road or inside a
building, and hidden when the camera is far away.

With **Time of day** on, the sun, sky and shadows follow the shift clock. The
instances have no wall-clock time, so the shift is **assumed to start at 06:00**;
the assumed time is shown next to the clock (☀ 06:00) and only affects the look.

### Analysis

The **Analysis** drawer shows how the solution uses the trucks:

| Number | Meaning |
|---|---|
| Distance driven | all trucks' kilometres, and how many of them were cleaning |
| Driving without cleaning | share of the trucks' working time spent driving streets they do not clean |
| Fleet busy | share of all trucks' shift time spent out of the depot |
| Waiting at the depot | truck-hours of the shift not used |
| Repeated driving | share of street traversals that go over a street already driven |
| All mandatory done | when the last mandatory street is cleaned (or how many are left) |

Below them, a timeline has one row per truck over the shift: green = cleaning,
thin blue = driving without cleaning, empty = at the depot, white line = now.
Hover a bar for its times; click to select that truck and jump to that moment. For the greedy on Presheva, for
example, trucks spend about two thirds of their working time driving without
cleaning and are back at the depot within about 2 of the 8 hours.

An uploaded solution is parsed and timed in the browser (no pipeline needed) and
appears in the **Solution** list as "Upload: <file name>". It must be for the open
city (a file with another number of trucks is rejected). The app shows its score
and lists problems such as moves between unconnected junctions, routes that do not
start and end at the depot, routes over the time limit, trucks cleaning streets
that need a larger capacity, and mandatory streets left uncleaned; such a file is
still played so the problem can be seen (only a move between two junctions with no
street between them stops the upload). Uploads are **not saved**: a reload
removes them, and they have no realistic mode. To keep a solution, add it with
`build.py` (see "Adding a new algorithm").

## Pipeline

### `build.py`

```text
python visualization/pipeline/build.py CITY... [--algorithm NAME] [--rerun] [--buildings] [--sumo [--traffic DENSITY]]
```

Runs the algorithm (default `greedy`) on each city unless its solution file
already exists, checks the solution with `clipp`'s validator, adds 3D buildings
when asked (`--buildings`, see below), calls `convert.py`, and with `--sumo` runs
the realistic mode (see `sumo_run.py`). A city can be given by name (`Presheva`)
or folder.

### `convert.py`

```text
python visualization/pipeline/convert.py CITY... [--out DIR]
```

Exports a city with every algorithm solution found in
`data/output/<algorithm>/<City>_instance_solution.txt`. It checks the data
(`checks.py`), projects all coordinates with the UTM zone of the city centre, and
writes:

| File | Content |
|---|---|
| `city.json` | name, projection, boundary, depot, fleet, time limit, street names and road classes, buffer layout |
| `streets.bin` | per street: a, b, way, time, length, metres, type, req, road class, name, polyline offsets; all polyline points |
| `solutions/<id>.json` | vehicles (type, steps, end), score, buffer layout |
| `solutions/<id>.steps.bin` | per step: street, entry time, flags (bit 0 = driven b→a, bit 1 = cleans) |
| `index.json` | every city of `catalog.json`, marked as converted or not |

Every solution is checked again as it is converted: each junction pair must be a
street, routes must start and end at the depot and fit the time limit, cleaned
streets must be driven by a truck with enough capacity, and every mandatory street
must be cleaned. Files of solutions that no longer exist are removed. The
dataset's own solution (`instance.solution.txt`) is not shown in the app; the tests use it to check the
timeline rules against the generator's route times and validator score.

### `sumo_run.py`

```text
python visualization/pipeline/sumo_run.py CITY... [--solution ALGORITHM] [--profile realistic|ideal] [--traffic DENSITY]
```

Drives an exported solution in Eclipse SUMO (also run by `build.py --sumo`):

| CLIPP | SUMO |
|---|---|
| junction i | node `j{i}` at its projected position (`priority`, or `unregulated` for `ideal`) |
| street k | edge `s{k}_f` (a→b), plus `s{k}_r` (b→a) for a two-way street; the real shape and length, speed from OSM `maxspeed` or the road class (never below the trucks' 20 km/h), lanes from OSM |
| turns the routes use | netconvert builds the network twice: first with its own turns, then adding only the turns the routes need that it left out (mostly U-turns). Edges that get an added turn keep all their computed turns, lane by lane, so other traffic is not cut off. The run stops if any turn a route needs is still missing |
| truck v | vehicle `v{v}` of type S, M or L (at most 20 km/h), departing at 0 with its exact list of edges |
| background traffic | `randomTrips.py --insertion-density DENSITY` (cars per hour per km of lane, so it scales with the city) |

SUMO runs with `--vehroute-output.exit-times`, so only the time each vehicle
leaves each road is kept, not per-second positions. The result is written as
`solutions/<id>.sumo.bin` in the same step format as the exact timeline, so the
app plays both with the same code. A SUMO run is kept when the city is
re-exported with an unchanged solution file. SUMO's networks and raw outputs
stay in `pipeline/work/` (git-ignored).

Profiles:

- `realistic` (default): SUMO's default driver model and priority junctions.
- `ideal`: near-instant acceleration, no internal junction lanes and no turn-speed
  limit. It shows how close SUMO gets to the solver's timing; trucks come out a
  few percent *faster*, because SUMO does not round each street time up to a whole
  second as the instance does.

Results with `--traffic 1` for the greedy solutions: see the app's realistic mode;
on Presheva, trucks take a median 28 % longer than planned.

### `buildings.py`

```text
python visualization/pipeline/buildings.py CITY...
```

OpenStreetMap is very incomplete for buildings in many of the course's cities
(about 51 mapped buildings in Presheva's central km²), so building footprints come
from Microsoft's open [Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints)
(ODbL), which has about 600 there. The dataset is split into map tiles per
country; the tiles covering the city are downloaded once into `pipeline/cache/`
(git-ignored) and only buildings inside the city boundary are kept (4,319 for
Presheva, 217 KB for the app). The footprints have no heights, so heights are
**estimated** from the footprint area (1 to 6 floors of 3 m); the app says so in
its attribution line. Buildings are optional: `build.py <City> --buildings` runs
this step (a few minutes per city the first time); the app works without them,
and no city has them at the moment.

### `audit.py`

```text
python visualization/pipeline/audit.py [CITY_FOLDER...] [--json report.json]
```

Checks each city's file hashes against `manifest.json` and every assumption the
viewer relies on: each street has a road feature with the same time, direction and
end nodes; junction coordinates match the polyline ends; no self-loops; no two
streets between the same junctions (so a junction-only route is never ambiguous).
On Windows, Git may check text files out with CRLF line endings
(`core.autocrlf`); the audit detects that and reports those files as matching.

## Assumptions and limits

- A solution file says which streets each truck cleans, not when. The viewer
  assumes a street is cleaned on the truck's **first** traversal of it, and turns
  it green when that traversal ends.
- Turn restrictions from OSM are not part of the CLIPP model, so a valid route
  may make turns that are forbidden in reality.
- Coordinates are projected to metres around the city centre, so 32-bit floats in
  the browser keep centimetre precision even in the largest cities.
- The demand, fleet and speed of the dataset are synthetic assumptions on a real
  map (see each city's `manifest.json`).

Map data © OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright.
Building footprints: Microsoft Global ML Building Footprints, ODbL.
