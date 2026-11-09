# Divide and Conquer: splitting the city into zones

*Një algoritëm Divide and Conquer për ndarjen e qytetit në zona.*

Selected with `--algorithm divide-conquer` (code: `clipp/divide_conquer.py`).

```powershell
python main.py data/input/syntetic_generated/instance_D.txt --algorithm divide-conquer
python -m unittest tests.test_divide_conquer
```

Python 3.10+, standard library only, deterministic (no randomness, no time
limits). Valid solutions are written to `data/output/divide_conquer/`.

## Algorithm: workload-balanced Recursive Graph Bisection

The city graph is cut in two, each half is cut in two again, and so on, until
every zone has exactly one vehicle. This is **Recursive Graph Bisection**
(Simon, 1991), with the two cut ends found by the pseudo-peripheral node
"double sweep" of George and Liu. Here the cut balances **cleaning workload**
instead of the number of streets.

A zone is a set of streets (all categories, so connectors keep zones
connected) plus the vehicles that serve them. The root zone is the whole city
with the whole fleet.

```text
bisect(zone):
    if zone has 1 vehicle (or < 2 streets, or max depth reached):
        return [zone]                                  # base case
    left_vehicles, right_vehicles = deal vehicles alternately, largest first
    shares = expected work of each vehicle per requirement class (water-filling)
    a = farthest junction from a seed; b = farthest junction from a
    sort streets by (dist_a - dist_b) of their midpoint      # sweep a -> b
    for each requirement class r (30, 20, 10, connectors):
        cut the class's streets where the left half holds
        sum(shares[r][v] for v in left_vehicles) / total_r of its workload
    return bisect(left) + bisect(right)                # conquer
```

### Divide

1. **Double sweep.** On the undirected sub-graph of the zone's streets
   (weights = traversal time) run Dijkstra from a seed to find the farthest
   junction `a`, then from `a` to find the farthest junction `b`. `a` and `b`
   are the two ends of the zone. The seed is taken from the connected piece
   that holds the most mandatory work.
2. **Sweep order.** Every street gets the key
   `((d_a(u)+d_a(v)) - (d_b(u)+d_b(v))) / 2`: negative near `a`, positive
   near `b`. Sorting by the key sweeps the zone from `a` to `b`, so any prefix
   of the list is one contiguous side of the zone.
3. **Vehicles.** The zone's vehicles are sorted by capacity (L, M, S) and dealt
   alternately, so both halves get a similar mix of vehicle types. The left half
   gets `ceil(k/2)` vehicles.
4. **Capacity-aware cut.** A street with requirement 30 can only be cleaned by
   an L vehicle, so cutting one list at "half the work" can overload the L
   vehicles. Instead the expected work of every vehicle is estimated by
   **water-filling**: the hardest class is poured onto the vehicles able to
   clean it, then each easier class onto all vehicles able to clean it, always
   raising the least loaded first. Each requirement class is then cut
   separately along the same sweep, at the share of its work the left half's
   vehicles are expected to do. A half never receives mandatory streets that
   none of its vehicles can clean.

### Conquer

The recursion stops when a zone has one vehicle. That vehicle then routes
**only inside its zone**: repeatedly drive to the nearest uncleaned mandatory
street of the zone (shortest path, any street may be used for travel), as long
as a shortest way back to the depot still fits in `T`. Zones shared by several
vehicles (see *Depth ladder*) serve requirement classes hardest first, and the
vehicle with the nearest next street moves. Zones do not influence each other,
so they could be solved in parallel.

### Combine

1. All zone routes are put together in one solution.
2. Mandatory streets a zone could not finish in time (the workload estimate
   ignores travel) are handed to any vehicle with time left: first a city-wide
   greedy pass over the leftovers, then a street-by-street repair.
3. Spare time goes to optional streets with positive score gain, ranked by gain
   per second: first inside the vehicle's own zone, then anywhere.
4. Every vehicle returns to the depot, then each route cleans the eligible
   streets it already drives over (`SearchSpace.sweep_traversed`).

### Depth ladder (merging zones)

`partition(instance, max_depth=d)` stops the recursion after `d` levels, so
sibling zones stay merged and share their vehicles. `d = ceil(log2 k)` gives
one vehicle per zone; `d = 0` is the whole city as one zone.
`solve` builds the solution for every depth from finest to coarsest and keeps
the best valid score. If a fine partition cannot finish all mandatory streets,
coarser ones can. Instances above 5,000 streets stop at the first valid depth,
to limit running time.

## Complexity

Let `m` be the number of streets, `n` the number of junctions and `k` the
number of vehicles.

* One split of a zone with `m_z` streets runs three Dijkstras and one sort:
  `O(m_z log m_z)`.
* The zones on one level of the recursion are disjoint, so a whole level costs
  `O(m log m)`.
* The recursion has `ceil(log2 k)` levels:

```text
T(m, k) = T(m_1, ceil(k/2)) + T(m_2, floor(k/2)) + O(m log m),  m_1 + m_2 = m
        = O(m log m · log k)
```

For a balanced split (`m_1 = m_2 = m/2`, `k ≈ m`) this is the Master theorem
case `T(m) = 2T(m/2) + O(m log m) = O(m log² m)`.

Routing then costs one bounded Dijkstra probe per cleaned street (as in the
recursive solvers), and the depth ladder repeats the build at most
`ceil(log2 k) + 1` times.

## Results

Scores with the official formula. Instances A–E use `alpha = 1`, so the score is
coverage only.

| Instance | greedy | dp-simple | D&C, one vehicle per zone | D&C, best depth (`solve`) |
|---|---:|---:|---:|---:|
| A | 0.3883 | 0.5448 | infeasible | 0.5909 (d0) |
| B | 0.6859 | 0.7432 | 0.7369 | 0.8355 (d0) |
| C | 0.6520 | 0.7610 | 0.7103 | 0.7604 (d0) |
| D | 0.5928 | 0.7494 | 0.7061 | 0.7783 (d0) |
| E | 0.5836 | 0.6305 | infeasible (d1: 0.5931) | 0.6291 (d0) |

Real cities (above 5,000 streets only the first valid depth is built). All
solutions are valid, with every mandatory street cleaned:

| City | Streets | Vehicles | greedy | dp-simple | D&C | Time |
|---|---:|---:|---:|---:|---:|---:|
| Presheva | 838 | 6 | 0.6169 | 1.0000 | 0.9918 | 1 s |
| Prishtina | 8,729 | 72 | 0.6202 | 1.0000 | 0.9973 | 9 s |
| Ulqini | 5,074 | 92 | | | 0.9979 | 7 s |
| Shkupi | 16,658 | 87 | | | 0.9993 | 26 s |
| Tirana | 19,175 | 75 | | | 0.9947 | 36 s |
| Ljubljana | 34,104 | 94 | | | 0.9952 | 73 s |
| Vienna | 56,787 | 68 | | | 0.9996 | 121 s |

New-York, Johannesburg and Sydney have not been run yet.

### Observations

* With one vehicle per zone, the zones beat the greedy baseline wherever they
  are feasible: routes stay short and compact.
* On the small synthetic instances the coarsest depth scores best, because a
  shared zone lets idle vehicles help their neighbours. Strict zoning wastes
  spare time near zone borders. This is the usual trade-off of zoning:
  simpler, local routes against flexibility.
* Instances A and E are infeasible with one vehicle per zone. The workload
  estimate counts cleaning time but not the travel to a zone and back to the
  depot, so far zones get too much work. Merging zones (the depth ladder)
  fixes this.

## Possible improvements

* Add the travel time from the depot to the zone to its workload, so far zones
  get less cleaning work.
* Rebalance after routing: move border streets from overloaded zones to
  neighbours with time left (a local "combine" step), instead of merging
  whole levels.
* Real cities have coordinates (`geography.json`). Recursive Coordinate
  Bisection (cut at the median x / y) is a simpler alternative there, and the
  zones could be coloured in the 3D visualizer.
