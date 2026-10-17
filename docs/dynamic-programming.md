# Dynamic-programming solvers

Two solvers built from dynamic programs whose states are defined over
sub-problems, next to the greedy baseline and the recursive solvers. The code
lives in `clipp/dp/`; like the other algorithms they plug into `main.py`
through `solve(instance) -> Solution` and are selected with `--algorithm`.

```powershell
python main.py data/input/syntetic_generated/instance_E.txt --algorithm dp-simple    # Solution A
python main.py data/input/syntetic_generated/instance_E.txt --algorithm dp-advanced  # Solution B
python scripts/run_dp.py data/input/syntetic_generated/instance_E.txt --method advanced
python scripts/benchmark_dp.py                                                       # all instances
python -m unittest tests.test_dp                                                     # tests
```

Python 3.10+, standard library only. As with the other algorithms, valid
solutions are written to `data/output/dp_simple/` or `data/output/dp_advanced/`
as `<instance>_solution.txt` (real cities: `<City>_instance_solution.txt`);
the best known solutions are committed there, like the greedy outputs.

`scripts/run_dp.py` runs one solver with an option `main.py` does not have
(`--output-dir`), checks the solution with an independent validator written
from the official statement (`clipp/dp/objective.py`) and reports the provable
upper bound and the gap. `scripts/benchmark_dp.py` compares greedy, Solution A
and Solution B on every instance (`--only` for a subset, `--output-dir` to
write elsewhere).

Both solvers are **deterministic**: they use no randomness and no wall-clock
limits, so the same instance always gives exactly the same solution (checked by
`test_advanced_is_deterministic`). Solution A replaces a stored solution only if
it scores higher; Solution B always writes its result, which is the solution of
record.

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
| `split.py` | giant tour → routes (three Split DPs) | optimal for the given tour |
| `local_search.py` | Held–Karp windows, in-route selection DP, best-ratio insertion | optimal per window / per route order |
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
* `split_heterogeneous` (Solution B), the DP also chooses each route's vehicle
  type: state `(c, i)` with `c` = vehicles used per type —
  `O(n · Π(F_x + 1) · 3)`.
* `split_min_routes` (large networks), fewest routes covering a class tour:
  `R[i] = 1 + min_{s in window} R[s]` — `O(n)`.

All three are checked against exhaustive enumeration in `tests/test_dp.py`.

### Held–Karp windows

`H[S][k] = min time from the window's entry through exactly the services in S,
ending with oriented service k`; the window's exit is fixed. Exact for the
window (`O(2^w · (2w)^2)`), verified against all permutations × orientations.

### In-route selection DP

For a route's service order, Pareto labels `(time, value)` at each kept service
`h`: `G[h] = {(time_g + d(b_g, a_h) + t_h, value_g + delta_h)}` over the
previous kept `g` with no mandatory service in between; labels with
`time + d(b_h, depot) > T` are pruned. Picks the most valuable subsequence that
fits in `T` (mandatory services forced). Verified against all subsets.

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

## Solution B – `clipp/dp/advanced.py`

Memetic search over giant tours (order crossover, mutation, replacement of the
worst individual), then a large-neighbourhood search; Solution A is part of the
initial population, so B is never worse than A.

**No randomness.** Every choice follows a fixed rule: the starting tours are
nearest-neighbour tours where every k-th step takes the second-nearest task
(k = 2, 3, 4, …), parents come from a fixed list of rank pairs (best pairs
first), crossover blocks and mutations advance with fixed strides, every third
child is mutated, and the ruin-and-recreate move follows a fixed 40-step cycle.
Each phase stops after a fixed number of iterations (`GENERATIONS = 4000`, or
`STAGNATION = 1500` generations without a new best; `LNS_ITERATIONS = 3000`),
never on wall-clock time, so the result does not depend on the machine.

* Decoder: Held–Karp education of the mandatory subsequence → exact
  `split_heterogeneous` (chooses vehicle types) → optional tasks follow their
  preceding mandatory task → in-route selection DP → Held–Karp windows →
  best-ratio insertion of unserved optional streets.
* Polishing: Lemma 1 → normalisation (cleaned streets become services) →
  Held–Karp → insertion, repeated until no gain.
* LNS moves (exactly scored, equal scores accepted): relocate 1–3 mandatory
  services to their cheapest slot, drop a block of optional services from a
  route, drop the optional services nearest to a chosen service, swap the plans of
  two vehicles of different type (`alpha < 1`); each followed by Held–Karp, the
  selection DP and insertion.
* If Solution A already meets the upper bound it is returned as proven optimal.

## Results

Scores of the solution files kept in `data/output/` (each re-read from disk and
accepted by both validators). Greedy: the optimized greedy outputs in
`data/output/greedy/`. Witness: the feasibility witness `instance.solution.txt`
shipped with each real city. A: `data/output/dp_simple/`. B:
`data/output/dp_advanced/`, the result of the deterministic Solution B (one run;
running it again gives the same file). Time B is the run time of that run.

| Instance | N | M | C | α | Greedy | Witness | A | **B** | UB | Gap B | Time A (s) | Time B (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| instance_A | 20 | 45 | 4 | 1.0 | 0.3883 | – | 0.5448 | **0.9096** | 1.0000 | 9.04% | 0.0 | 40.8 |
| instance_B | 40 | 100 | 5 | 1.0 | 0.6859 | – | 0.7432 | **1.0000** | 1.0000 | 0.00% | 0.0 | 95.8 |
| instance_C | 70 | 250 | 6 | 1.0 | 0.6520 | – | 0.7610 | **0.8913** | 1.0000 | 10.87% | 0.1 | 365.9 |
| instance_D | 120 | 600 | 9 | 0.7 | 0.5928 | – | 0.7494 | **0.8564** | 0.9962 | 14.04% | 0.6 | 2112.0 |
| instance_E | 200 | 1,200 | 12 | 1.0 | 0.5836 | – | 0.6305 | **0.7161** | 0.8833 | 18.93% | 1.3 | 2646.3 |
| Presheva | 744 | 838 | 6 | 0.5 | 0.6169 | 0.6064 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 2.7 | 0.0 |
| Ulqini | 4,610 | 5,074 | 92 | 0.5 | 0.5539 | 0.6050 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 0.2 | 0.0 |
| Prishtina | 7,400 | 8,729 | 72 | 0.5 | 0.6202 | 0.6063 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 0.5 | 0.0 |
| Shkupi | 13,771 | 16,658 | 87 | 0.5 | 0.5994 | 0.6017 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 1.0 | 0.0 |
| Tirana | 16,951 | 19,175 | 75 | 0.5 | 0.6132 | 0.5965 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 1.4 | 0.0 |
| Ljubljana | 30,278 | 34,104 | 94 | 0.5 | 0.6262 | 0.6014 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 3.4 | 0.0 |
| Vienna | 45,049 | 56,787 | 68 | 0.5 | 0.6464 | 0.5998 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 4.9 | 0.0 |
| New-York | 132,300 | 182,700 | 392 | 0.5 | 0.6217 | 0.6358 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 15.6 | 0.0 |
| Johannesburg | 157,587 | 204,280 | 379 | 0.5 | 0.5915 | 0.5998 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 15.1 | 0.0 |
| Sydney | 255,428 | 316,886 | 697 | 0.5 | 0.6395 | 0.6001 | 1.0000 | **1.0000** | 1.0000 | 0.00% | 33.1 | 0.0 |

### Exact scores from `main.py`

Both solvers are deterministic, so `python main.py <instance> --algorithm
dp-simple|dp-advanced` reproduces these scores exactly on every run (printed by
`main.py` after the repository validator accepted the solution; all mandatory
streets cleaned in every case).

| Instance | Solution A (`dp-simple`) | Solution B (`dp-advanced`) |
|---|---:|---:|
| instance_A | 0.5448013996947474 | 0.9096452369430071 |
| instance_B | 0.7431717746506777 | 1.0 |
| instance_C | 0.7610409776674996 | 0.8913221526839433 |
| instance_D | 0.7494036565131714 | 0.8563561683951457 |
| instance_E | 0.6305051248665259 | 0.7160944928651553 |
| Presheva | 1.0 | 1.0 |
| Ulqini | 1.0 | 1.0 |
| Prishtina | 1.0 | 1.0 |
| Shkupi | 1.0 | 1.0 |
| Tirana | 1.0 | 1.0 |
| Ljubljana | 1.0 | 1.0 |
| Vienna | 1.0 | 1.0 |
| New-York | 1.0 | 1.0 |
| Johannesburg | 1.0 | 1.0 |
| Sydney | 1.0 | 1.0 |

Where A meets the upper bound it is proven optimal and B is not run (time 0):
all ten real cities. instance_B also reaches the bound, so 11 of the 15
instances are solved to proven optimality. On every instance both solutions beat
greedy (B: +23% on instance_E up to +134% on instance_A; the cities: +55% to
+81%, because the solutions clean every street with the right-sized truck and
waste no water).

## Real cities with an 8-hour shift

Most real instances allow far more time per vehicle than a working day (Vienna
137 h, New York and Johannesburg 205 h, Sydney 227 h). `scripts/make_8h_instances.py`
writes variants with the time limit capped at 8 h (`T = min(T, 28800)`; nothing
else changes) to `data/input/real_instances_8h/` (generated, not committed):

```powershell
python scripts/make_8h_instances.py
python scripts/run_dp.py data/input/real_instances_8h/Vienna/instance.txt --method simple --output-dir data/output/dp_simple_8h
```

Sydney is left out: 163 of its mandatory streets need more than 8 h just for
depot → street → depot, so no valid plan exists. Results (both validators accept
every solution; Solution B equals Solution A on networks above 2,000 junctions):

| City | T original → 8 h | Solution A | Solution B | UB | Coverage | Water waste |
|---|---|---:|---:|---:|---:|---:|
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
* The dense memetic search needs all-pairs distances and is used for networks
  up to 2,000 junctions; on larger networks Solution A already reaches the
  upper bound on every instance in the repository.
* Unused vehicles receive the cheapest `depot -> x -> depot` loop so that every
  route has at least one move, as the official format requires `n >= 1`.
* Output follows the repository/official-validator convention for `n`
  (number of moves); the statement's prose says "number of junctions", but its
  own example and the accepted baseline files use the number of moves.
