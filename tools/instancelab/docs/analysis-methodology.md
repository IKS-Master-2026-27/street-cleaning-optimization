# Analysis matrix and preprocessing methodology

## What this stage produces

Each validated CLIPP instance becomes one row in a numerical feature table. The
full table retains all 26 documented characteristics for reporting and future
experiments. PCA uses a smaller, explicitly documented subset because the
current class dataset contains only 15 observations.

## Default PCA input

| Feature | Transformation | Reason retained |
|---|---|---|
| `num_junctions` | `log1p` | Network scale; `num_streets` is currently almost identical in information. |
| `time_limit` | `log1p` | Route budget configured by the instance. |
| `out_degree_cv` | identity | Directed-connectivity heterogeneity. |
| `mandatory_service_fraction` | identity | Relative compulsory workload by street count. |
| `bidirectional_street_fraction` | identity | Directional routing flexibility. |
| `travel_time_cv` | identity | Scale-independent travel-time heterogeneity. |
| `high_requirement_fraction` | identity | Concentration of highest-capability service demand. |
| `mandatory_length_per_vehicle` | `log1p` | Mandatory workload relative to fleet size. |
| `mean_mandatory_fleet_coverage` | identity | Fleet interchangeability over mandatory work. |

The remaining catalog features are not deleted. They stay available in the
comparison table and may become informative when more diverse instances are
added. The default subset avoids feeding several near-duplicate measurements
to PCA merely because they are available.

`alpha` also remains in the comparison table, but it is excluded from the
default projection because it has an absolute Pearson correlation of `0.9562`
with `mandatory_service_fraction` in the current 15-instance dataset. The
structural workload characteristic is retained instead of double-weighting the
same observed variation.

## Transformations

`log1p(x) = log(1 + x)` is used for non-negative scale variables spanning
orders of magnitude. It preserves zero and reduces the domination of Sydney-
scale values without discarding size information.

After transformation, every selected column is standardized as:

```text
z = (x - mean) / population_standard_deviation
```

This gives every selected feature mean zero and variance one. Without this
step, raw junction counts would dominate fractions measured between zero and
one solely because of their units.

## Scientific limits

- The current 15-instance sample is small; the projection is exploratory.
- The four time-pressure characteristics are not PCA inputs. On the reference
  set `mandatory_time_pressure` correlates at r = 0.95 with
  `mandatory_service_fraction` and `mean_mandatory_round_trip_ratio` at
  r = 0.87 with `mean_mandatory_fleet_coverage`; adding them would count the
  same information twice. They are reported in the feature tables and are
  related to algorithm score and execution time.
- The full 26-feature catalog must not be placed into PCA without redundancy
  review.
- Constant columns are rejected rather than silently included.
- This is unsupervised feature-space PCA. It is not supervised PILOT, an
  algorithm footprint, or a performance-prediction model.

## PCA computation and outputs

The standardized matrix is factorized with singular value decomposition (SVD).
The first two right-singular vectors define the `PC1` and `PC2` axes. Instance
scores are obtained by multiplying standardized rows by these axes.

InstanceLab reports:

- `PC1` and `PC2` coordinates for every instance;
- feature loadings for interpreting both axes;
- explained variance and explained-variance ratio;
- the combined fraction of variance retained in the 2D view.

SVD component signs are mathematically arbitrary. InstanceLab orients each
component so its largest absolute loading is positive, making repeated plots
and tests deterministic without changing distances or explained variance.

New instances use the reference dataset's fitted transformations, means,
standard deviations and PCA components. They can therefore be placed in the
existing instance space without changing the axes. Re-fitting remains an
explicit choice when the reference collection itself changes.

## Scientific validation diagnostics

The dashboard reports three transparent sensitivity checks over the nine
selected PCA inputs:

1. A Pearson correlation matrix is computed after the documented feature
   transformations. Pairs with absolute correlation of at least `0.85` are
   listed for redundancy review. This threshold is a screening rule, not an
   automatic feature-deletion rule and not evidence of causation.
2. Instance extremeness is summarized by the root mean square of the nine
   standardized values. The largest absolute z-score and its feature are also
   reported. This ranks unusual rows but does not label valid instances as
   erroneous outliers.
3. Leave-one-out sensitivity re-fits preprocessing and PCA once per reference
   instance, each time omitting one row. The overlap between the complete and
   reduced two-dimensional component subspaces is measured as the mean squared
   cosine of their principal angles. It lies between zero and one and is
   invariant to arbitrary PCA sign changes and rotations within the 2D space.

The leave-one-out table also reports the 2D explained variance for every
re-fit. These diagnostics reveal dependence on individual observations, but
they do not overcome the current sample-size limitation or turn the analysis
into supervised ISA.
