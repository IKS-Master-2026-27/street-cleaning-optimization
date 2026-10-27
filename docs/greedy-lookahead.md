# Greedy with look-ahead

Selected with `--algorithm greedy-lookahead` (code: `clipp/greedy_lookahead.py`).

```powershell
python main.py data/input/syntetic_generated/instance_E.txt --algorithm greedy-lookahead
python -m unittest tests.test_greedy_lookahead
```

## Idea

The baseline greedy commits the nearest feasible street. This solver is still
greedy (one street per step, a committed street is never undone), but each
decision *looks ahead* before it commits:

1. For a vehicle at junction `v`, take its `width` best candidate streets
   (shortest approach path + one street to clean).
2. Extend each candidate by a greedy rollout of `depth - 1` further streets
   (always the nearest feasible street). This is one line, not a tree.
3. Score the line by `value / (time + return_weight * time_home_from_its_end)`.
4. Commit **only the first street** of the best line; throw the rollout away
   and plan again at the next step (rolling horizon).

`width = 1, depth = 1` is the plain nearest-street greedy; larger values trade
time for foresight. One decision costs `width * depth` probes.

## Phases

* Mandatory streets are served hardest class first (requirement 30, 20, 10) by
  the vehicles that can clean the class, so large vehicles are not used up on
  streets a smaller vehicle could clean. Across vehicles, the vehicle whose
  best look-ahead line has the highest score moves next; only the vehicle that
  moved and vehicles whose line used the just-cleaned street are re-planned.
* Optional phase: the same look-ahead picks optional streets with positive
  score gain, valued by `gain / time`, until no vehicle has time left.
* Every candidate is feasible only while a shortest way back to the depot still
  fits in `T`. Vehicles are then closed, and a final sweep cleans eligible
  streets the routes already drive over.

## Configurations

For up to 1,500 streets the solver builds a solution for every
`(width, depth) in {(1,1),(3,2),(4,3),(6,4)}` with `return_weight in {0, 0.5}`,
validates each and keeps the best score (deterministic, no randomness). Larger
instances use fewer configurations: up to 60,000 streets `(1,1),(3,2)`, above
that only `(1,1)`. `solve(instance, width=, depth=, return_weight=)` runs one.

## How it differs from the other algorithms

| | commits | foresight |
|---|---|---|
| greedy | nearest street | none |
| recursive | nearest street, rollback if a branch pays nothing | none |
| recursive-enum | street of the best enumerated branch, with rollback | all `width^depth` branches |
| **greedy-lookahead** | first street of the best rollout, no rollback | one greedy line per candidate |

## Results (score, `main.py`)

| Instance | greedy | recursive-enum | **greedy-lookahead** |
|---|---:|---:|---:|
| instance_A | 0.3883 | 0.5392 | **0.5542** |
| instance_B | 0.7594 | 0.7238 | **0.8437** |
| instance_C | 0.6835 | 0.6971 | **0.7861** |
| instance_D | 0.6718 | 0.7362 | **0.7548** |
| instance_E | 0.5836 | 0.5972 | **0.6260** |
| Presheva (real) | 0.6169 | – | 0.9691 |

All solutions were accepted by the repository validator with every mandatory
street cleaned.

## Limitations

* Deeper look-ahead does not always win: on some instances `(1,1)` scores
  better, which is why several configurations are tried.
* Greedy: no optimality guarantee, and a failed assignment does not prove
  infeasibility (`GreedyAssignmentError` as in the baseline).
* Large cities (above the all-pairs preprocessing limit) run Dijkstra per probe;
  only the cheapest configuration is used there.
