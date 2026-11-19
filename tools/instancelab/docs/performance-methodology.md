# Algorithm-score analysis methodology

## Available result sets

The current shared repository contains complete stored solution sets for two
algorithms across all 15 reference instances:

- `greedy`
- `dp_simple`

InstanceLab reads these files without modifying them. Every route is parsed,
checked for legal traversal, depot return, route-time limit, cleaning capability
and mandatory-street coverage before its score enters the analysis.

Algorithm folders are discovered dynamically under `data/output`. A result set
enters the comparison only when it contains one valid solution for every current
reference instance. Incomplete sets are reported and excluded, preventing a
partial experiment from biasing the comparison. For example, the current
`dp_simple_8h` folder is detected but excluded because it covers only part of
the reference collection and represents a different experiment configuration.

## Score

The shared project's official objective is recalculated as:

```text
score = alpha * coverage + (1 - alpha) * efficiency
```

Coverage is cleaned eligible length divided by total eligible length. Efficiency
penalizes cleaning-capacity waste using the same normalization as the shared
scorer. Scores, coverage and efficiency are bounded between zero and one.

## Execution time

Published solution files contain no timings, and InstanceLab never executes an
algorithm to produce new results. Scores always come from the published files.
To report execution time, `python -m instancelab.timing` re-runs exactly the
published (instance, algorithm) pairs:

- a published folder is timeable when its name matches a key of the shared
  `main.py` `ALGORITHMS` table with `-` replaced by `_` (the rule `main.py`
  uses when writing results). `dp_simple_8h` has no such key and is reported
  as not timeable; unpublished algorithms are never run;
- each pair runs in its own subprocess with a timeout; only the algorithm call
  is timed with `time.perf_counter`;
- the re-run solution is written to `results/timing/solutions/` (ignored by
  git), validated and re-scored, and compared with the published score;
- a time is attached to a published score only when the re-run reproduces that
  score. A differing score means the published solution came from an earlier
  version of the algorithm code, so its time would belong to another solution.
  Such pairs are listed separately in the dashboard.

`results/timing/results.csv` and `metadata.json` (shared-repository revision,
machine, Python version, timeout, worker count) are committed so the dashboard
shows times without re-running. Times are from one run per pair on one machine
and are intended for relative comparison and feature-time association.

## Analysis shown

- per-instance algorithm scores and winner;
- mean, minimum and maximum score per algorithm;
- the number of instances on which each algorithm obtains the best score;
- algorithm score over the existing 2D PCA feature projection;
- Pearson correlation between each selected standardized characteristic and
  each algorithm's score.

The PCA axes remain feature-only and are not re-fitted using algorithm scores.
The score overlay therefore shows performance over the established structural
map rather than silently converting it into a supervised projection.

## Limits

- There are only 15 instances and two complete algorithm result sets.
- `dp_simple` has a higher stored score on every current instance. There is no
  contrasting winner region for statistically meaningful algorithm footprints.
- Execution times cover only pairs whose re-run reproduced the published score
  and come from a single run per pair.
- Only the instances published in the shared repository are analysed; no
  instances are generated or added by InstanceLab.
- Pearson correlations are descriptive and do not establish causation or
  out-of-sample predictive accuracy.
- The synthetic and real instance groups differ structurally, while all current
  real-instance `dp_simple` scores equal one. The group split may therefore
  explain part of a feature-score correlation; correlations must not be read as
  isolated causal effects.
- Full supervised ISA, performance prediction and algorithm footprints remain
  deferred until more diverse algorithm outcomes and repeated benchmark timing
  data are available.
