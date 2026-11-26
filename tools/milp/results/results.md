# CLIPP competition model (OR-Tools CP-SAT): cold start vs warm start

Time limit 3600 s per run, 4 CP-SAT workers per run, random seed 0, same computer for all runs. Warm start = `dp_simple` solution as hint (AddHint). Objective = official score (maximise): lower bound = best valid solution, upper bound = CP-SAT bound, gap = (UB − LB) / LB.

| Instance | Variant | Result | Variables | Time (s) | 1st valid (s) | Objective (LB) | Upper bound | Gap | Seed | Δ vs seed | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| instance_A | cold | feasible | 451 | 3600.04 | 132.660 | 0.906369 | 0.933186 | 2.96% |  |  | stopped: time_limit |
| instance_A | warm | feasible | 451 | 3600.03 | 0.011 | 0.909645 | 0.933186 | 2.59% | 0.544801 | 0.3648438 | stopped: time_limit |
| instance_B | cold | feasible | 1,213 | 3600.03 | 2429.68 | 0.997650 | 1.000000 | 0.24% |  |  | stopped: time_limit |
| instance_B | warm | feasible | 1,213 | 3600.03 | 0.026 | 0.903862 | 1.000000 | 10.64% | 0.743171 | 0.1606909 | stopped: time_limit |
| instance_C | cold | no valid solution | 3,319 | 3600.03 |  |  | 0.999999 |  |  |  | no connected solution found (time_limit) |
| instance_C | warm | feasible | 3,319 | 3600.03 | 0.086 | 0.843261 | 0.999999 | 18.59% | 0.761040 | 0.0822202 | stopped: time_limit |
| instance_D | cold | no valid solution | 11,856 | 3600.09 |  |  | 1.000000 |  |  |  | no connected solution found (time_limit) |
| instance_D | warm | no improvement | 11,856 | 3600.10 | 0.838 | 0.749403 | 1.000000 | 33.44% | 0.749403 | 0.0000000 | solver found no valid solution better than the seed (time_limit); the seed is kept |
| instance_E | cold | no valid solution | 30,585 | 3600.21 |  |  |  |  |  |  | no connected solution found (time_limit) |
| instance_E | warm | no improvement | 30,585 | 3600.12 | 1.941 | 0.630505 | 0.999999 | 58.60% | 0.630505 | 0.0000000 | stopped: time_limit |
| Presheva | cold | no valid solution | 13,850 | 3600.07 |  |  | 0.999999 |  |  |  | no connected solution found (time_limit) |
| Presheva | warm | no improvement (seed optimal) | 13,850 | 0.328 |  | 0.999999 | 0.999999 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| Johannesburg | warm | model not built | 190,903,396 | 3603.5 |  |  |  |  |  |  | model not built within the build limit |
| Ljubljana | warm | no improvement (seed optimal) | 8,054,842 | 1300.34 |  | 1.000000 | 1.000000 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| New-York | warm | model not built | 163,924,392 | 3602.0 |  |  |  |  |  |  | model not built within the build limit |
| Prishtina | warm | no improvement (seed optimal) | 1,579,838 | 37.200 |  | 1.000000 | 1.000000 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| Shkupi | warm | no improvement (seed optimal) | 3,609,329 | 87.327 |  | 0.999999 | 0.999999 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| Sydney | warm | model not built | 528,551,534 | 3602.9 |  |  |  |  |  |  | model not built within the build limit |
| Tirana | warm | no improvement (seed optimal) | 3,522,878 | 80.512 |  | 0.999999 | 0.999999 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| Ulqini | warm | no improvement (seed optimal) | 1,234,583 | 26.246 |  | 0.999999 | 0.999999 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
| Vienna | warm | no improvement (seed optimal) | 8,822,423 | 263.535 |  | 0.999999 | 0.999999 | 0.00% | 1.000000 | 0.0000000 | the model's upper bound equals the seed score: the seed is proven optimal |
