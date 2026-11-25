# Instance characteristic catalog

InstanceLab extracts a fixed, ordered vector of characteristics only after an
instance passes structural and semantic validation. The catalog is intentionally
small: every value has a clear interpretation for the street-cleaning problem
and can be computed for the largest class instances in `O((N + M) log N + C)`
time; only the depot shortest paths need the logarithmic factor.

## Size and budget

| Feature | Definition | Interpretation |
|---|---|---|
| `num_junctions` | `N` | Network size by junction count. |
| `num_streets` | `M` | Network size by street-record count. |
| `num_vehicles` | `C` | Available fleet size. |
| `time_limit` | `T` | Route time budget in the instance. |
| `alpha` | Header value `alpha` | Objective trade-off configured by the instance. |

## Graph structure

| Feature | Definition | Interpretation |
|---|---|---|
| `street_to_junction_ratio` | `M / N` | Sparse-network complexity without calling mixed graphs “dense”. |
| `directed_arc_to_junction_ratio` | `(one-way + 2 × two-way) / N` | Traversable connectivity after respecting direction. |
| `out_degree_cv` | `population_std(out_degree) / mean(out_degree)` | Heterogeneity of outgoing connectivity. |
| `bidirectional_street_fraction` | `two-way streets / M` | Directional flexibility of the network. |
| `mean_travel_time` | Mean over all streets | Typical traversal cost. |
| `travel_time_cv` | `population_std(time) / mean(time)` | Scale-independent travel-time heterogeneity. |

## Service demand

| Feature | Definition | Interpretation |
|---|---|---|
| `connector_street_fraction` | Connector streets `/ M` | Portion of records used only for connectivity. |
| `mandatory_service_fraction` | Mandatory `/ (mandatory + optional)` | How much service is compulsory by street count. |
| `mandatory_length_fraction` | Mandatory service length `/` all service length | How much service is compulsory by length. |
| `mean_service_length` | Mean over mandatory and optional streets | Typical service-segment size. |
| `service_length_cv` | `population_std(length) / mean(length)` | Scale-independent service-length heterogeneity. |
| `mean_service_requirement` | Mean capability requirement over service streets | Typical vehicle capability demanded. |
| `high_requirement_fraction` | Requirement-30 service streets `/` all service streets | Concentration of the hardest capability level. |

## Fleet compatibility and workload

| Feature | Definition | Interpretation |
|---|---|---|
| `mean_vehicle_capacity` | Mean of `S=10`, `M=20`, `L=30` | Typical cleaning capability in the fleet. |
| `large_vehicle_fraction` | Type-`L` vehicles `/ C` | Concentration of highest-capability vehicles. |
| `mandatory_length_per_vehicle` | Mandatory service length `/ C` | A routing-independent workload proxy. |
| `mean_mandatory_fleet_coverage` | For every mandatory street, fraction of capable vehicles; then mean | How interchangeable the fleet is across mandatory work. |

## Time pressure

`round_trip(s)` is the fastest depot -> traverse `s` -> depot time, computed
with Dijkstra from and to the depot (two-way streets use their better
orientation). These are the only features that are not a single linear pass;
they cost `O((N + M) log N)`.

| Feature | Definition | Interpretation |
|---|---|---|
| `mandatory_time_pressure` | `sum(travel_time of M) / (C * T)` | Share of the whole fleet time budget needed just to drive the mandatory streets once. |
| `service_time_pressure` | `sum(travel_time of M and O) / (C * T)` | Same for all serviceable streets; values above one mean not everything can be cleaned. |
| `mean_mandatory_round_trip_ratio` | `mean(round_trip(s) / T for M)` | How far compulsory work lies from the depot relative to one route. |
| `max_mandatory_round_trip_ratio` | `max(round_trip(s) / T for M)` | The tightest mandatory street; validation guarantees it is at most one. |

## Interpretation rules

- Validation rejects an instance whose mandatory street cannot be reached,
  cleaned and left within `T` (`mandatory_time_infeasible`). This is a
  necessary feasibility condition, not a proof that all mandatory work fits.
- Coefficients of variation use population standard deviation because the
  instance contains the complete street population, not a sample.
- A ratio or coefficient with a zero denominator is reported as `0.0`. This
  keeps the vector finite for later numerical analysis; the associated raw
  counts show why it is zero.
- Raw scale features and normalized structural features are both retained.
  Before PCA, scale features will be reviewed for log transformation and all
  selected columns will be standardized.
- These characteristics describe instances only. They do not establish
  algorithm superiority, performance prediction, or algorithm footprints.
