# Dynamic-programming solvers

A solver (Solution A) built from dynamic programs whose states are defined over
sub-problems, next to the greedy baseline and the recursive solvers. The code
lives in `clipp/dp/`; like the other algorithms it plugs into `main.py`
through `solve(instance) -> Solution` and is selected with `--algorithm`.

```powershell
python main.py data/input/syntetic_generated/instance_E.txt --algorithm dp-simple    # Solution A
python scripts/run_dp.py data/input/syntetic_generated/instance_E.txt
python scripts/benchmark_dp.py                                                       # all instances
python -m unittest tests.test_dp                                                     # tests
```

Python 3.10+, standard library only. As with the other algorithms, valid
solutions are written to `data/output/dp_simple/`
as `<instance>_solution.txt` (real cities: `<City>_instance_solution.txt`);
the best known solutions are committed there, like the greedy outputs.

`scripts/run_dp.py` runs the solver with an option `main.py` does not have
(`--output-dir`), checks the solution with an independent validator written
from the official statement (`clipp/dp/objective.py`) and reports the provable
upper bound and the gap. `scripts/benchmark_dp.py` compares greedy and Solution A
with the upper bound on every instance (`--only` for a subset, `--output-dir` to
write elsewhere).

The solver is **deterministic**: it uses no randomness and no wall-clock
limits, so the same instance always gives exactly the same solution. It
replaces a stored solution only if it scores higher.

## Key identity

With `L_max`, `W_max` as in the statement and no street cleaned twice,

```
Score = (1 - alpha) + sum over cleaned streets j of delta(j, q_j)
delta(j, q) = alpha * L_j / L_max - (1 - alpha) * (q - R_j) * L_j / (1000 * W_max)
```

The score is additive over streets, which is what makes the knapsack and Split
recurrences below exact. Consequences: a street cleaned by a vehicle of exactly
its requirement always has `delta > 0`; with `alpha < 1` an optional street
cleaned by a larger vehicle can have `delta < 0` and is then left uncleaned
even if the vehicle drives over it.

## Building blocks

| Module | Sub-problem solved | Guarantee |
|---|---|---|
| `distances.py` | Dijkstra trees (cached), reverse tree to the depot | exact |
| `assignment.py` | who cleans each traversed street (Lemma 1) | optimal for fixed moves |
| `knapsack.py` | spare time → extra optional streets (0/1 knapsack over depot-free loops) | optimal for the candidates and time buckets |
| `split.py` | giant tour → routes (two Split DPs) | optimal for the given tour |
| `bounds.py` | upper bound on the optimal score (Theorem 3) | provable |

### Lemma 1 – cleaning assignment

Once every vehicle's movement is fixed, give each traversed street to the
vehicle with the largest `delta` (mandatory: always, optional: only if
`delta > 0`). The terms of the additive score are independent, so this is
optimal. It also collects streets cleaned "for free" while deadheading.

### Split DPs (route-first, cluster-second)

Tour tasks `0..n-1` (oriented streets). A segment `s..e` served by one vehicle
takes `time(s,e) = from[s] + cum[e] - cum[s] + t[e] + to[e]`. Distances are
shortest paths, so by the triangle inequality the feasible starts of a segment
ending at `e` form a window `[lo(e), e]` whose left border never moves back.
With additive segment values each recurrence is evaluated with a monotone
deque, i.e. in linear time per vehicle (cf. Vidal 2016).

* `split_ordered` (Solution A), fleet in a fixed order, optional tasks may be
  dropped between routes:
  `P_k[i] = max(P_{k-1}[i], P_k[i-1] if task i-1 optional,
  V_q[i] + max_{s in window} (P_{k-1}[s] - V_q[s]))` — `O(n·C)`.
* `split_min_routes` (large networks), fewest routes covering a class tour:
  `R[i] = 1 + min_{s in window} R[s]` — `O(n)`.

Both are checked against exhaustive enumeration in `tests/test_dp.py`.

### Upper bound (Theorem 3)

`UB = (1-alpha) + sum_M delta*_j + fractional knapsack of optional streets
(delta*_j > 0, servable) with capacity C·T - sum_M t_j`, where `delta*_j` is the
best contribution over vehicle types in the fleet. Every cleaned street costs at
least its own traversal time, so `UB >= optimum`. It ignores deadheading, so it
is tight when time is plentiful (all real cities) and loose on the tight
synthetic instances.

## Solution A – `clipp/dp/simple.py`

1. Useful tasks: every mandatory street, and optional streets with
   `delta > 0` for some vehicle type in the fleet; tasks whose single round trip
   exceeds `T` are excluded (mandatory ones are reported).
2. Small/medium networks: four deterministic tours (class-ordered or plain
   nearest neighbour; with or without optional tasks) → `split_ordered` with the
   fleet sorted L, M, S → routes → Lemma 1 → knapsack DP → Lemma 1. The best
   final plan is kept.
3. Large networks: every street goes to the smallest vehicle type able to clean
   it (zero avoidable waste); one nearest-neighbour tour per class (incremental
   multi-target Dijkstra, no all-pairs table) and `split_min_routes`. If a class
   has too few vehicles, `split_ordered` selects the most valuable subset.

## Results

Scores of the solution files kept in `data/output/` (each re-read from disk and
accepted by both validators). Greedy: the optimized greedy outputs in
`data/output/greedy/`. Witness: the feasibility witness `instance.solution.txt`
shipped with each real city. A: `data/output/dp_simple/`.

| Instance | N | M | C | α | Greedy | Witness | **A** | UB | Gap A | Time A (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| instance_A | 20 | 45 | 4 | 1.0 | 0.3883 | – | 0.5448 | **0.9096** | 1.0000 | 9.04% | 0.0 | 40.8 |
| instance_B | 40 | 100 | 5 | 1.0 | 0.6859 | – | 0.7432 | **1.0000** | 1.0000 | 0.00% | 0.0 | 95.8 |
| instance_C | 70 | 250 | 6 | 1.0 | 0.6520 | – | 0.7610 | **0.8913** | 1.0000 | 10.87% | 0.1 | 365.9 |
| instance_D | 120 | 600 | 9 | 0.7 | 0.5928 | – | 0.7494 | **0.8564** | 0.9962 | 14.04% | 0.6 | 2112.0 |
| instance_E | 200 | 1,200 | 12 | 1.0 | 0.5836 | – | 0.6305 | **0.7161** | 0.8833 | 18.93% | 1.3 | 2646.3 |
| Presheva | 744 | 838 | 6 | 0.5 | 0.6169 | 0.6064 | **1.0000** | 1.0000 | 0.00% | 2.7 |
| Ulqini | 4,610 | 5,074 | 92 | 0.5 | 0.5539 | 0.6050 | **1.0000** | 1.0000 | 0.00% | 0.2 |
| Prishtina | 7,400 | 8,729 | 72 | 0.5 | 0.6202 | 0.6063 | **1.0000** | 1.0000 | 0.00% | 0.5 |
| Shkupi | 13,771 | 16,658 | 87 | 0.5 | 0.5994 | 0.6017 | **1.0000** | 1.0000 | 0.00% | 1.0 |
| Tirana | 16,951 | 19,175 | 75 | 0.5 | 0.6132 | 0.5965 | **1.0000** | 1.0000 | 0.00% | 1.4 |
| Ljubljana | 30,278 | 34,104 | 94 | 0.5 | 0.6262 | 0.6014 | **1.0000** | 1.0000 | 0.00% | 3.4 |
| Vienna | 45,049 | 56,787 | 68 | 0.5 | 0.6464 | 0.5998 | **1.0000** | 1.0000 | 0.00% | 4.9 |
| New-York | 132,300 | 182,700 | 392 | 0.5 | 0.6217 | 0.6358 | **1.0000** | 1.0000 | 0.00% | 15.6 |
| Johannesburg | 157,587 | 204,280 | 379 | 0.5 | 0.5915 | 0.5998 | **1.0000** | 1.0000 | 0.00% | 15.1 |
| Sydney | 255,428 | 316,886 | 697 | 0.5 | 0.6395 | 0.6001 | **1.0000** | 1.0000 | 0.00% | 33.1 |

### Exact scores from `main.py`

The solver is deterministic, so `python main.py <instance> --algorithm
dp-simple` reproduces these scores exactly on every run (printed by
`main.py` after the repository validator accepted the solution; all mandatory
streets cleaned in every case).

| Instance | Solution A (`dp-simple`) |
|---|---:|
| instance_A | 0.5448013996947474 |
| instance_B | 0.7431717746506777 |
| instance_C | 0.7610409776674996 |
| instance_D | 0.7494036565131714 |
| instance_E | 0.6305051248665259 |
| Presheva | 1.0 |
| Ulqini | 1.0 |
| Prishtina | 1.0 |
| Shkupi | 1.0 |
| Tirana | 1.0 |
| Ljubljana | 1.0 |
| Vienna | 1.0 |
| New-York | 1.0 |
| Johannesburg | 1.0 |
| Sydney | 1.0 |

Solution A meets the upper bound, and is therefore proven optimal, on all ten
real cities. On every instance it beats greedy (synthetic: +8% to +40%; the
cities: +55% to +81%, because the solutions clean every street with the
right-sized truck and waste no water).

## Real cities with an 8-hour shift

Most real instances allow far more time per vehicle than a working day (Vienna
137 h, New York and Johannesburg 205 h, Sydney 227 h). `scripts/make_8h_instances.py`
writes variants with the time limit capped at 8 h (`T = min(T, 28800)`; nothing
else changes) to `data/input/real_instances_8h/` (generated, not committed):

```powershell
python scripts/make_8h_instances.py
python scripts/run_dp.py data/input/real_instances_8h/Vienna/instance.txt --output-dir data/output/dp_simple_8h
```

Sydney is left out: 163 of its mandatory streets need more than 8 h just for
depot → street → depot, so no valid plan exists. Results (both validators accept
every solution):

| City | T original → 8 h | Solution A | UB | Coverage | Water waste |
|---|---|---:|---:|---:|---:|
| Presheva | 8 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Ulqini | 12 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Prishtina | 8 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Shkupi | 18 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Tirana | 18 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Ljubljana | 40.5 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| New-York | 205 h → 8 h | 1.000000 | 1.000000 | 1.000000 | 100% | 0 |
| Vienna | 137 h → 8 h | 0.849957 | 0.849957 | 1.000000 | 70.0% | 0 |
| Johannesburg | 205 h → 8 h | 0.908388 | 0.908388 | 1.000000 | 81.7% | 0 |

With an 8-hour shift seven cities are still cleaned completely (more vehicles
are simply put to work). In Vienna and Johannesburg every mandatory street is
cleaned, but the vehicles of each class cannot also reach all optional streets
in 8 h; the class mandatory-first tour in `plan_by_class` lets the Split DP cover
the mandatory streets first and spend the remaining vehicles on the most
valuable optional ones. The upper bound (1.0) only limits the fleet's total
time, not the driving to far-away streets, so the 9–15% gap there is an
overestimate.

## Limitations

* Optimality is proven per sub-problem, not globally (the problem is strongly
  NP-hard). On the tight synthetic instances the upper bound ignores
  deadheading, so the reported gap overestimates the true distance to optimum.
* Unused vehicles receive the cheapest `depot -> x -> depot` loop so that every
  route has at least one move, as the official format requires `n >= 1`.
* Output follows the repository/official-validator convention for `n`
  (number of moves); the statement's prose says "number of junctions", but its
  own example and the accepted baseline files use the number of moves.
