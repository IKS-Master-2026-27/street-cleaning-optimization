# CLIPP competition MILP (OR-Tools CP-SAT): cold start vs warm start

The task: run the **existing MILP model** in two variants and report, for both,
the time, objective value, upper/lower bound, optimality gap and result:

| Variant | Initial solution | Instances |
|---|---|---|
| `cold` | none | instance_A–E, Presheva |
| `warm` | Dynamic Programming solution (`data/output/dp_simple/`) as CP-SAT hint (`AddHint`) | all 15 |

Same settings for every run: 1 h solver time, 4 CP-SAT workers, random seed 0,
same computer.

**Status:** the experiment was run on 2026-11-25/26 (21 runs, all finished).
Results and findings: [cpsat-report.md](cpsat-report.md); raw data:
`results/cpsat/`.

## The model

The model is the CLIPP competition model,
[CLIPP-Optimization-Competition/milp-solver](https://github.com/CLIPP-Optimization-Competition/milp-solver)
(commit `cf6ed8a`), copied unchanged into `third_party/clipp_cpsat/` (only its
imports were made relative, see the README there). Formulation:
`third_party/clipp_cpsat/MILP_EXPLANATION.md`.

In short, per vehicle `k`: `f[a,k]` = how often arc `a` is driven (integer,
at most `min(T / t_a, 50)`), `clean[j,k]` = vehicle `k` cleans street `j`,
`cleaned[j]` = street `j` is cleaned. Constraints: flow conservation (closed
walk), route time ≤ T, clean only driven streets with enough capacity, at
most one cleaner per street, all mandatory streets cleaned, a vehicle that
drives must use the depot. The objective is the official score scaled by 1e9
and rounded to integers (the constant `1 − α` is left out). Routes that are not
connected to the depot ("subtours") are removed lazily: solve, look for
components without the depot, add a cut for each, solve again.

## What the tool adds

`clipp/milp/cpsat.py` builds the model with the competition functions, in the
same order as `clipp_cpsat.model.solve_milp`, and runs the same solve loop with
these differences:

1. **Warm start:** the DP solution is converted to values of every variable and
   given as a complete hint. It is first checked: the model is solved with all
   variables fixed to the hint (`fix_variables_to_their_hinted_value`) and the
   routes are checked to be connected to the depot (column `hint_feasible`).
   If several vehicles clean the same street, the smallest truck keeps it (the
   model allows one cleaner per street; the score cannot drop).
2. **Hint in later rounds:** after a round with subtours, the original replaces
   the hint by the last (disconnected) candidate. Cold runs keep exactly this.
   Warm runs keep hinting the better of the seed and the best valid solution
   found so far, so the warm start is not lost after round 1.
3. **One deadline:** the 1 h covers all rounds including the subtour checks
   (the original subtracts only the CP-SAT time). Building the model and
   checking the hint are reported separately (`build_s`, `hint_check_s`).
4. **Valid solutions during a round:** every CP-SAT solution is checked for
   subtours as it is found (models up to 2 million variables), so the time to
   the first valid solution and the best valid solution are known even if the
   round ends with a disconnected candidate.
5. **Early stop:** when a known valid solution (found or the seed) reaches the
   upper bound, it is proven optimal and the run stops.
6. **Warm result never below the seed:** if CP-SAT finds only valid solutions
   worse than the seed, the seed is reported (`result` = `no improvement`).

Every final solution is turned into routes (Hierholzer), checked with this
repository's validator and scored with the official score.

## Report columns (`results/cpsat/results.csv`)

| Column | Meaning |
|---|---|
| `result` | `optimal`, `feasible` (time limit), `no improvement`, `no improvement (seed optimal)`, `no valid solution`, `model not built`, `no result` |
| `reason` | why the run ended, e.g. `stopped: time_limit`, `out of memory while in phase 'build'` |
| `num_vars`, `num_constraints` | model size (variables are counted even if the model cannot be built) |
| `build_s`, `hint_check_s`, `solve_s` | time to build the model, to check the hint, to solve (wall clock) |
| `first_valid_s`, `best_s` | solve time to the first / best valid (connected) solution found by CP-SAT |
| `objective` = `lower_bound` | score of the best valid solution (the seed if CP-SAT found nothing better) |
| `upper_bound` | smallest CP-SAT bound over all rounds (each round solves a relaxation, so it is valid) |
| `gap` | `(UB − LB) / LB` |
| `seed_score`, `improvement_vs_seed` | DP score, official score of the result minus DP score |
| `official_score`, `valid` | score and validity with this repository's validator |
| `rounds`, `cut_rounds`, `cpsat_status` | solve rounds, rounds that added subtour cuts, CP-SAT status per round |
| `peak_rss_mb`, `slept_s` | peak memory; time the computer slept (should be 0) |

The model objective is rounded to integers (×1e9), so `objective` can differ
from `official_score` in the 9th decimal (e.g. 0.9999999960 vs 1.0).

## Running

```bash
pip install -r requirements-milp.txt
python scripts/run_cpsat.py --background            # the whole experiment (~6-8 h), or
python scripts/run_cpsat.py --part 1 --background   # A, B, C cold + warm        (<= 3 h)
python scripts/run_cpsat.py --part 2 --background   # D, E, Presheva cold + warm (<= 3 h)
python scripts/run_cpsat.py --part 3 --background   # other 9 cities, warm       (~1-3 h)
python scripts/cpsat_viewer.py                      # rebuild results/cpsat/viewer.html
python scripts/run_cpsat.py data/input/syntetic_generated/instance_A.txt \
    --time-limit 30 --out ~/Desktop/cpsat_demo      # 30 s demo, outside results/cpsat
python -m unittest tests.test_cpsat
```

A run never replaces a finished result in `--out`: the tool stops and names
the runs that already exist. Use another `--out` folder (as in the demo) or
add `--overwrite` to replace them.

`results/cpsat/viewer.html` shows every run: an overview of all instances,
per instance the cold and warm run side by side with the best score over
time, the professor's four requirements with the runs that answer them, and
the findings. `run_cpsat.py` rebuilds it after every batch.

Scheduling (8 performance cores, 24 GB RAM): instances with at most 200 000
variables run their cold and warm run side by side (2 × 4 workers, 9 GB each);
the larger cities run one at a time afterwards (19 GB). A run is stopped when
it exceeds its memory limit or when building the model takes longer than 1 h;
the report then gives the number of variables, the time and the reason. The
background run uses `caffeinate -dims`; keep the computer on power with the
lid open.

All parts write into the same `--out` folder; `results.csv` / `results.md`
always contain every finished run, and each part keeps its own
`metadata_part<N>.json`.

Files in `results/cpsat/`:

| File | Content |
|---|---|
| `results.csv`, `results.md` | one row per run (columns above) |
| `metadata_part<N>.json` | settings, versions, computer, batches of each part |
| `viewer.html` | interactive results viewer (open in a browser, works offline) |
| `run.txt` | start/end of every run |
| `jobs/<instance>_<variant>/result.json` | the run's row |
| `jobs/<instance>_<variant>/progress.csv` | every solution and bound found, with time (for "score over time") |
| `jobs/<instance>_<variant>/solution.txt` | the best valid solution in the competition format |

During a run the tool also writes `status.txt`, `runner.pid`, `STOP` (to stop
the run) and per job `phase.txt` and `log.txt` (CP-SAT log). They are only
needed while running and are not kept in the repository (`.gitignore`).

## Model size

| Instance | Variables |
|---|---|
| instance_A / B / C / D / E | 451 / 1 213 / 3 319 / 11 856 / 30 585 |
| Presheva | 13 850 |
| Ulqini / Prishtina | 1 234 583 / 1 579 838 |
| Tirana / Shkupi | 3 522 878 / 3 609 329 |
| Ljubljana / Vienna | 8 054 842 / 8 822 423 |
| New-York / Johannesburg / Sydney | 163 924 392 / 190 903 396 / 528 551 534 |

The DP solution scores 1.0 (the maximum) on all 10 real cities, so the model
cannot improve it there; at best it proves it optimal. It did so on the 7
cities up to Vienna; New-York, Johannesburg and Sydney could not be built
within 1 h.
