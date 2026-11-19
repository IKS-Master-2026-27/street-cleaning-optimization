# Research basis and scope

InstanceLab is a small Python implementation inspired by Instance Space
Analysis (ISA). It does not copy or reimplement the complete MATLAB toolkit.
The project adopts only the techniques justified by the current street-cleaning
data.

## Professor-provided references

1. Kate Smith-Miles, **Stress-testing Algorithms, Solvers, and Models via
   Instance Space Analysis**, Gurobi webinar:
   <https://www.gurobi.com/resources/webinar-events/stress-testing-algorithms-kate-smith-miles-replay/>
2. Muñoz and Smith-Miles, **Instance Space Analysis Toolkit**:
   <https://github.com/andremun/InstanceSpace>
3. **MATILDA — Melbourne Algorithm Test Instance Library with Data Analytics**:
   <https://matilda.unimelb.edu.au/>
4. OPTIMA, **Instance Space Analysis**:
   <https://optima.org.au/instance/>
5. Smith-Miles and Muñoz, **Instance Space Analysis for Algorithm Testing:
   Methodology and Software Tools**, ACM Computing Surveys 55(12), 2023:
   <https://doi.org/10.1145/3572895>

## Techniques adopted

- Every instance is represented by a reproducible vector of meaningful
  structural characteristics rather than by its file name or source alone.
- Features are transformed and standardized before dimensionality reduction.
- Redundant features are reviewed before projection so correlated measurements
  do not silently receive repeated weight.
- A two-dimensional projection supports visual review of instance distribution,
  similarity and diversity.
- Loadings, explained variance, correlations and leave-one-out sensitivity are
  exposed so the projection is interpretable rather than a black box.
- Analysis outputs can be exported with fitted preprocessing parameters for
  reproducibility.

## Techniques deliberately deferred

Complete ISA models the relationship between instance characteristics and the
observed performance of one or more algorithms. It may construct algorithm
footprints, predict performance and recommend an algorithm for regions of the
space.

InstanceLab has a complete committed score matrix for `greedy` and `dp_simple`
over the 15 current reference instances. It uses that matrix only for
descriptive comparison and feature-score correlations. `dp_simple` has the best
stored score on every instance, so there is no contrasting winner region from
which a defensible algorithm footprint can be inferred. Execution times are
measured only for published pairs whose re-run reproduces the published score
(see `docs/performance-methodology.md`).

The **exploratory unsupervised feature-space PCA** remains fitted from instance
characteristics only. It is not supervised PILOT, an algorithm footprint or a
performance predictor. Those stages should be added only after published
results exist for more diverse instances and for more algorithms.

## Current scientific limitation

The reference collection contains only the 15 instances published in the
shared repository; InstanceLab deliberately adds no instances of its own. Correlation and
leave-one-out diagnostics help reveal sensitivity, but they do not create more
statistical evidence. Conclusions are limited to the current reference set and
must be revisited as new class instances are added.
