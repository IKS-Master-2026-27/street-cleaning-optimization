# Street Cleaning Optimization

This repository is being developed for an Advanced Algorithms course project on a **Street Cleaning Optimization Problem** based on graph-routing and coverage algorithms.

The goal is to find efficient routes for a fleet of street-cleaning vehicles while considering operational constraints such as time, street priority, vehicle capabilities, and available resources.

The project is designed to work with different street networks and should not depend on a specific city. A city is represented as input data, allowing the same algorithms to be tested on small networks as well as large urban areas.

## Problem Overview

A city is represented as a graph:

- **Vertices** represent street intersections.
- **Edges** represent streets.
- Streets may be one-way or bidirectional.
- Streets may have different traversal times, lengths, and cleaning requirements.
- Vehicles start from a common depot and return to the depot after completing their route.

Streets can have different roles:

- **Mandatory streets** must be cleaned.
- **Optional streets** provide additional value when cleaned.
- **Connector streets** are used for movement through the network but do not directly contribute to the cleaning objective.

The fleet may contain different vehicle types with different capabilities and resource limitations.

The main objective is to generate routes that satisfy the required constraints while maximizing useful street coverage and minimizing unnecessary travel and resource usage.

The problem is computationally difficult and is intended to be approached using graph algorithms, heuristics, approximation methods, and other optimization techniques.

## Run the deterministic CLIPP baseline

Requires Python 3.10 or newer. No third-party Python packages are required.
Run from the repository root:

```powershell
python main.py
# Or specify another instance
python main.py data/input/syntetic_generated/instance_E.txt


The default input is `data/input/syntetic_generated/instance_E.txt`. Valid solutions are written to
`data/output/<instance-name>_solution.txt`. A greedy assignment failure is reported
with diagnostics and a nonzero exit status. The current implementation may take
several minutes on instance_E because shortest paths are recomputed for candidates.

The supplied instance_E solution was accepted by the external validator with all
356 mandatory streets and 91 optional streets cleaned, at score 0.58363268951526.
See [the baseline notes](docs/greedy-baseline.md) for the algorithm and formats.

## Project Structure

```text
street-cleaning-optimization/
├── main.py
├── clipp/
│   ├── __init__.py
│   ├── parser.py
│   ├── graph.py
│   ├── solver.py
│   ├── validator.py
│   ├── scoring.py
│   └── output.py
├── data/
│   ├── input/
│   └── output/
├── tests/
├── docs/
├── visualization/
│   ├── public/
│   └── src/
├── README.md
└── CONTRIBUTING.md
```

### `clipp/`

The Python package separates parsing, graph routing, greedy solving, validation,
scoring, and output. `main.py` coordinates these modules. The visualization remains
separate; it does not need to be installed to run the Python solver.

### `visualization/`

Contains the Three.js application used to visualize the street network and calculated routes.

The visualization is kept separate from the routing and optimization logic.
It runs an algorithm on a real city's instance and replays the solution in 3D.
See [visualization/README.md](visualization/README.md):

```powershell
python visualization/pipeline/build.py Presheva   # prepares the app (runs the greedy only if no solution exists)
cd visualization; npm install; npm run dev
```

```text
City Data
    ↓
Graph
    ↓
Algorithms
    ↓
Routes / Results
    ↓
Visualization
```

### `data/`

Contains input datasets and generated results.

```text
data/input/
```

Contains city and street-network datasets.

Different cities or generated graph instances can be stored independently.

Example:

```text
data/input/
├── small-city/
├── medium-city/
└── large-city/
```

```text
data/output/
```

Contains generated routes and algorithm results.

### `tests/`

Contains tests for the graph model, algorithms, constraints, and route calculations.

### `docs/`

Contains project documentation, problem definitions, algorithm notes, complexity analysis, and experiment results.

## Scalability

The project should support different graph sizes without being designed around one specific city.

Algorithms can therefore be evaluated using:

- Small test graphs
- Medium-sized city networks
- Large city networks

This allows different approaches to be compared in terms of:

- Solution quality
- Total distance
- Street coverage
- Resource usage
- Execution time
- Scalability

## Git Workflow

The `main` branch contains the stable version of the project.

Do not work directly on `main`.

Before starting new work:

```bash
git checkout main
git pull
```

Create a branch for your task:

```bash
git checkout -b feature/your-feature-name
```

Examples:

```text
feature/graph-model
feature/routing-algorithm
feature/fleet-model
feature/threejs-visualization
feature/city-data-import
```

After finishing your work:

```bash
git add .
git commit -m "feat: add graph model"
git push -u origin feature/your-feature-name
```

Then create a Pull Request or Merge Request:

```text
feature/your-feature-name
        ↓
       main
```

Changes should be reviewed before being merged.

## Git Rules

- Do not push directly to `main`.
- Create one branch per task or feature.
- Pull the latest `main` before starting new work.
- Keep commits clear and focused.
- Create a Pull Request or Merge Request when the work is ready.
- Delete the branch after it has been merged.
