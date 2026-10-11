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

Trucks move on the solver's own timeline: each street's time from the instance,
added from 0 at the depot. This is exactly what the validator scores.

The work is split into an offline Python pipeline and a browser app. The browser
only loads the exported files; it never reads the raw dataset or runs an algorithm.

```text
visualization/
├── pipeline/              Python 3.10+, standard library only
│   ├── build.py           instance -> algorithm -> files for the browser (the main command)
│   ├── algorithms.py      the algorithms the tool can run; add new ones here
│   ├── convert.py         city + its solutions -> files for the browser (used by build.py)
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
│   ├── scene/             ground, streets, buildings, trucks, route, spray, daylight, picking
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

# 2. Start the app
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
third-party Python packages.

Built so far: **all 10 cities**, with the team's greedy solutions
(`data/output/greedy/<City>_instance_solution.txt`) and without buildings. The
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

1. Write a function that takes a `clipp.parser.Instance` and returns a
   `clipp.solver.Solution`, like `clipp.solver.solve`.
2. Register it in `visualization/pipeline/algorithms.py`:
   `"better": Algorithm("Better heuristic", "clipp.better", "solve")`.
3. Run `python visualization/pipeline/build.py Presheva --algorithm better`.

The app then offers every algorithm that has a solution for the open city in its
**Solution** list. Solutions already built are kept; nothing else has to change.

## Using the app

| Action | How |
|---|---|
| Play / pause | ▶ button or <kbd>Space</kbd>; speed from ×1 to ×10000 |
| Jump in time | drag the timeline; for an uploaded solution that runs past the time limit T, a yellow mark shows T |
| Pan, rotate, zoom | left drag, right drag, mouse wheel |
| Street or truck details | hover for a tooltip, click for the details card |
| Focus on a truck | click a truck or a row in the truck list: other trucks fade, its route shows the part already driven (white) and still ahead (faint blue), and the card shows progress bars for its route, its cleaning and its place in the shift |
| Follow a truck | after selecting it, **Follow** or <kbd>F</kbd>: the camera moves with it and you can still rotate and zoom |
| Ride along (driver's view) | after selecting it, **Driver view** or <kbd>V</kbd>: the camera sits low behind the truck and turns with it; <kbd>V</kbd> again to get the mouse back |
| Analyse the solution | **Analysis** in the time bar or <kbd>A</kbd> (see below) |
| See where trucks drive repeatedly | **Times driven** under **Show** colours every street by how often trucks drive it (almost white = once, then redder up to deep red = 4 times or more, dark grey = never) |
| Hide street types or truck types | the checkboxes under **Show** |
| Make trucks bigger or smaller | the **Truck size** slider under **Show**: up close trucks stay near real size, and they grow by this factor as you zoom out (remembered by the browser) |
| Make roads wider or narrower | the **Road width** slider under **Show** (×2 by default; remembered by the browser) |
| Hide buildings, water spray or day/night | the **Buildings**, **Water spray** and **Time of day** checkboxes under **Show** |
| Check your own solution | **Upload** (or drop the file on the page) a solution in the validator format for the open city |

Colours follow the course slides: red = mandatory, blue = optional, grey =
connector, green = cleaned, yellow = depot. Trucks are cyan (S), orange (M) and
magenta (L); they are bright while cleaning, dimmed while only driving, and grey
once back at the depot. The selected truck is white and its route is outlined.
A freshly cleaned street shines pale blue ("wet") for about 15 simulated minutes,
and trucks spray water from their front corners while they clean.

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

An uploaded solution is parsed and timed in the browser (no pipeline needed). The
app shows its score and lists problems such as moves between unconnected junctions,
routes that do not start and end at the depot, routes over the time limit, trucks
cleaning streets that need a larger capacity, and mandatory streets left uncleaned.

## Pipeline

### `build.py`

```text
python visualization/pipeline/build.py CITY... [--algorithm NAME] [--rerun] [--buildings]
```

Runs the algorithm (default `greedy`) on each city unless its solution file
already exists, checks the solution with `clipp`'s validator, adds 3D buildings
when asked (`--buildings`, see below), then calls `convert.py`. A city can be given by name (`Presheva`) or folder.

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
