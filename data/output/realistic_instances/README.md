# Results on the realistic instances

Solutions of the DP algorithms on `data/input/realistic_instances/` (whole cities, workload-scaled fleet and time limit).
They are kept in this separate folder because the file names are the same as for `data/input/real_instances/`.

Every solution was checked by both validators (`clipp/validator.py` and `clipp/dp/objective.py`):

```powershell
python scripts/run_realistic.py --algorithm dp-memo          # run + validate + write
python scripts/validate_solution.py --algorithm dp_memo --realistic   # re-check saved files
```

Score (time in seconds). All 30 solutions are valid; all mandatory streets are cleaned in every solution.

| City | Vehicles | T (s) | dp-simple | dp-memo | dp-memo-ls |
|---|---:|---:|---:|---:|---:|
| Johannesburg | 80 | 345145 | 1.000000 (13.9) | 1.000000 (14.8) | 1.000000 (16.1) |
| Ljubljana | 20 | 111500 | 1.000000 (2.2) | 1.000000 (2.4) | 1.000000 (3.4) |
| New-York | 101 | 306174 | 1.000000 (14.3) | 1.000000 (16.7) | 1.000000 (22.4) |
| Presheva | 4 | 8805 | 0.839525 (1.2) | 0.859616 (29.8) | 0.901122 (119.8) |
| Prishtina | 12 | 42474 | 1.000000 (0.3) | 1.000000 (0.4) | 1.000000 (0.4) |
| Shkupi | 16 | 64997 | 1.000000 (0.7) | 1.000000 (0.8) | 1.000000 (0.9) |
| Sydney | 107 | 480484 | 1.000000 (29.7) | 1.000000 (32.1) | 1.000000 (29.9) |
| Tirana | 16 | 74938 | 1.000000 (1.0) | 1.000000 (1.1) | 1.000000 (1.1) |
| Ulqini | 9 | 30714 | 0.788890 (0.3) | 0.788890 (0.4) | 0.788890 (0.3) |
| Vienna | 36 | 146378 | 1.000000 (3.7) | 1.000000 (3.9) | 1.000000 (3.8) |

Raw data (one line per run): `results.csv`.
Presheva and Ulqini (`dp-memo-ls`) were run in a different environment; run times there are not directly comparable.
