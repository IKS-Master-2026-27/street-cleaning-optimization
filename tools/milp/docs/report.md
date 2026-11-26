# MILP cold start vs warm start: results report

Experiment run 2026-11-25/26. Raw results: `tools/milp/results/results.csv`,
`tools/milp/results/results.md`, per run `tools/milp/results/jobs/<instance>_<variant>/`.
Tool and method: [`tools/milp/README.md`](../README.md).

## 1. Task

Run the existing MILP model in two variants and report time, objective,
upper/lower bound, optimality gap and result for both:

- **cold**: the model starts with no initial solution;
- **warm**: the model starts from the best existing algorithm, the Dynamic
  Programming solution by Albena, Erblin and Ardit (`data/output/dp_simple`),
  given to the solver as a hint (`AddHint`).

As agreed with Prof. Kadri (2026-11-25):

- model: the CLIPP competition CP-SAT model
  ([milp-solver](https://github.com/CLIPP-Optimization-Competition/milp-solver), commit `cf6ed8a`);
- cold on instance_A–E and Presheva, warm on all 15 instances;
- 1 h per run, same number of workers and same computer for both variants;
- the DP solution is checked to be valid for the model before it is used;
- report the time to the first valid solution and how much the model improves the DP;
- where the model cannot be built or cannot improve the DP: number of
  variables, time and reason.

## 2. Setup

| Setting | Value |
|---|---|
| Solver | OR-Tools CP-SAT 9.15.6755, Python 3.14.5 |
| Computer | MacBook (Apple silicon, 8 performance + 4 efficiency cores, 24 GB RAM), macOS, on power, sleep disabled (`caffeinate`) |
| Time limit | 3600 s solve time per run (all subtour rounds included) |
| Build limit | 3600 s to build the model |
| Workers | 4 CP-SAT workers per run |
| Random seed | 0 |
| Parallel runs | small instances: cold and warm side by side (2 × 4 workers); real cities: one at a time |
| Seed | `dp_simple`, checked with all variables fixed to the hint + connectivity check |

The computer did not sleep during any run (`slept_s` = 0 everywhere).

**Measures.** Objective = official score (maximised). Lower bound (LB) = score
of the best valid solution (routes connected to the depot). Upper bound (UB) =
the smallest CP-SAT bound over all rounds. Gap = (UB − LB) / LB.

## 3. Results: synthetic instances and Presheva (cold and warm)

| Instance | Variables | Variant | Result | First valid solution (s) | LB (score) | UB | Gap | DP score | Improvement vs DP |
|---|---|---|---|---|---|---|---|---|---|
| A | 451 | cold | feasible (time limit) | 132.7 | 0.9064 | 0.9332 | 2.96% | – | – |
| A | 451 | warm | feasible (time limit) | 0.01 | **0.9096** | 0.9332 | **2.59%** | 0.5448 | **+0.3648** |
| B | 1 213 | cold | feasible (time limit) | 2429.7 | **0.9977** | 1.0000 | **0.24%** | – | – |
| B | 1 213 | warm | feasible (time limit) | 0.03 | 0.9039 | 1.0000 | 10.64% | 0.7432 | **+0.1607** |
| C | 3 319 | cold | no valid solution | – | – | 1.0000 | – | – | – |
| C | 3 319 | warm | feasible (time limit) | 0.09 | **0.8433** | 1.0000 | 18.59% | 0.7610 | **+0.0822** |
| D | 11 856 | cold | no valid solution | – | – | 1.0000 | – | – | – |
| D | 11 856 | warm | no improvement | 0.84 | 0.7494 (DP) | 1.0000 | 33.44% | 0.7494 | 0 |
| E | 30 585 | cold | no solution at all | – | – | – | – | – | – |
| E | 30 585 | warm | no improvement | 1.94 | 0.6305 (DP) | 1.0000 | 58.60% | 0.6305 | 0 |
| Presheva | 13 850 | cold | no valid solution | – | – | 1.0000 | – | – | – |
| Presheva | 13 850 | warm | **DP proven optimal** (0.3 s) | – | 1.0000 (DP) | 1.0000 | 0.00% | 1.0000 | 0 |

"First valid solution" is the solver time to its own first valid solution. In
the warm runs the DP solution itself is valid from the start.

Solve rounds (each round ends with subtour cuts and a new solve):

| Instance | cold rounds | warm rounds |
|---|---|---|
| A | 23 | 21 |
| B | 13 | 6 |
| C | 1 | 1 |
| D | 1 | 1 |
| E | 1 (no candidate found) | 1 |
| Presheva | 159 | 1 (stopped: DP optimal) |

### Best valid score over time (A, B, C)

| Run | 1 s | 10 s | 60 s | 5 min | 10 min | 30 min | 60 min |
|---|---|---|---|---|---|---|---|
| A cold | – | – | – | 0.9064 | 0.9064 | 0.9064 | 0.9064 |
| A warm | 0.6129 | 0.6129 | 0.6129 | 0.6129 | 0.6129 | 0.6129 | 0.9096 |
| B cold | – | – | – | – | – | – | 0.9977 |
| B warm | 0.8024 | 0.8024 | 0.8024 | 0.8024 | 0.8024 | 0.8668 | 0.9039 |
| C cold | – | – | – | – | – | – | – |
| C warm | 0.7747 | 0.7820 | 0.8433 | 0.8433 | 0.8433 | 0.8433 | 0.8433 |

## 4. Results: real cities (warm only)

| City | Variables | Build (s) | DP check (s) | Solve (s) | Result | Memory |
|---|---|---|---|---|---|---|
| Presheva | 13 850 | 0.08 | 0.06 | 0.3 | DP proven optimal | <1.5 GB |
| Ulqini | 1 234 583 | 7.8 | 5.1 | 26.2 | DP proven optimal | 3.0 GB |
| Prishtina | 1 579 838 | 10.3 | 6.2 | 37.2 | DP proven optimal | 4.4 GB |
| Tirana | 3 522 878 | 25.0 | 15.5 | 80.5 | DP proven optimal | 5.0 GB |
| Shkupi | 3 609 329 | 26.4 | 14.9 | 87.3 | DP proven optimal | 5.6 GB |
| Ljubljana | 8 054 842 | 55.1 | 36.3 | 1300.3 | DP proven optimal | 8.7 GB |
| Vienna | 8 822 423 | 64.2 | 39.3 | 263.5 | DP proven optimal | 9.1 GB |
| New-York | 163 924 392 | > 3600 | – | – | model not built within 1 h | 10.1 GB |
| Johannesburg | 190 903 396 | > 3600 | – | – | model not built within 1 h | 10.0 GB |
| Sydney | 528 551 534 | > 3600 | – | – | model not built within 1 h | 7.7 GB |

On every city where the model was built, the DP solution was accepted as a
valid hint and the model's upper bound equals the DP score (1.0): the DP
solution is **proven optimal**. The model objective is rounded to integers
(×1e9), so the LB/UB in `results.csv` can differ from 1.0 in the 7th–9th
decimal (e.g. 0.9999995360 or 1.0000002610); the official score of every
solution is exactly 1.0.

**New-York, Johannesburg, Sydney.** The model was not built, so CP-SAT gives
no result there. The DP solution is still optimal: the score is
α·coverage + (1 − α)·efficiency with both parts at most 1, so 1 is the
highest possible score, and the DP reaches 1.0 on these cities. In the team's
results spreadsheet the MILP warm value for these three cities may therefore
be filled in as 1, marked as an **assumption** (not a measured MILP result).

## 5. Findings

1. **Warm start gives a valid solution immediately.** Warm runs always had a
   valid solution (the DP) from second 0, and the solver found its own valid
   solution in 0.01–1.94 s. Cold runs needed 133 s (A) and 2430 s (B), and on
   C, D, E and Presheva found no valid solution in 1 h.

2. **The model improves the DP on small instances.** A: 0.545 → 0.910
   (+67%), B: 0.743 → 0.904 (+22%), C: 0.761 → 0.843 (+11%).

3. **The model proves the DP optimal on 7 real cities** (Presheva, Ulqini,
   Prishtina, Tirana, Shkupi, Ljubljana, Vienna), in 0.3 s to 22 min.

4. **The model does not scale.**
   - From ~3 000 variables (C, D, E) only one round finishes in 1 h, so the
     subtour cuts cannot remove the disconnected routes. On D and E the warm
     run does not improve the DP; on E the cold run does not even find a
     candidate (status UNKNOWN, no bound).
   - New-York, Johannesburg and Sydney (164–529 million variables) cannot be
     built within 1 h.

5. **Warm is not always better at the end.** On B the cold run ended at
   0.9977 (gap 0.24%), the warm run at 0.9039 (gap 10.6%). A likely reason:
   the warm run keeps hinting the DP solution in every round, which keeps the
   search near the DP routes. On A warm ended slightly better (0.9096 vs
   0.9064), but cold reached its result much earlier (133 s vs 2599 s).

6. **Presheva cold:** 159 rounds in 1 h, every candidate still had
   disconnected routes. The warm run proved the DP optimal in 0.3 s.

7. **Size limit in this experiment (1 h, 4 workers).** Cold start found a
   valid solution only up to ~1 200 variables (A, B); from ~3 300 variables
   (C) upward it found none. Warm start always had a valid solution and
   proved the DP optimal up to ~8.8 million variables (Vienna). This is not a
   hard limit of the model: it depends on the time limit and on the instance
   (with no time limit, our HiGHS model found a valid solution for C).

## 6. Extra comparison: our HiGHS model (earlier run, no time limit)

An earlier, own MILP formulation of the same problem (HiGHS 1.16), cold, no
time limit, run 2026-11-23/24 (the computer switched off after ~9.5 h). Only
its results are kept, as a comparison (agreed with Prof. Kadri); its code is
not part of this repository.

| Instance | HiGHS cold, no time limit | CP-SAT cold, 1 h | CP-SAT warm, 1 h |
|---|---|---|---|
| A | optimal 0.9179 after ~3.2 h | 0.9064 | 0.9096 |
| B | optimal 1.0 after ~2.9 h | 0.9977 | 0.9039 |
| C | 0.9250, UB 0.9723, gap 5.1% after ~9.5 h | no valid solution | 0.8433 |
| D | no feasible solution after ~9.5 h | no valid solution | 0.7494 (DP) |
| E | no feasible solution after ~9.5 h | no solution | 0.6305 (DP) |
| Presheva | no feasible solution after ~9.5 h | no valid solution | 1.0 (DP, optimal) |

With the optimum of A known (0.9179), the true gap of the CP-SAT warm result
on A is (0.9179 − 0.9096) / 0.9096 = 0.9%, smaller than the reported 2.59%.

## 7. Notes on the method

- The DP solution was checked for every instance before use: the model was
  solved with every variable fixed to the DP values and the routes were checked
  to be connected to the depot. It was valid on all 12 instances where the
  model was built (column `hint_feasible`).
- Every result was turned into routes and checked with this repository's
  validator and official score; all valid.
- Changes to the original solve loop (details in `tools/milp/README.md`): one 1 h
  deadline for all rounds; warm runs keep hinting the best valid solution;
  valid solutions are recorded during a round; the run stops when a valid
  solution reaches the upper bound.
- A reporting bug was found and fixed during the experiment: when the solver
  found only solutions worse than the DP, the report used the solver's
  solution instead of the DP (instance_D warm, first reported 0.7356). The
  row was recomputed from the saved run. The search itself was not affected
  (that run had a single round).
