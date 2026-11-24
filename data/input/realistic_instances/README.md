# Realistic instances: whole cities with workload-scaled fleet and time (scaling-policy-v3)

One whole-city CLIPP instance per requested city, with fleet and time from scaling-policy-v3:

- Time limit T = 2.995 x (N/1000)^0.685 hours (N = junctions), rounded up to the whole second.
- Fleet C = ceil(sqrt(W)), W = constructive workload in vehicle-hours, minimum 2, split over S/M/L by class workload.

Roads, directions, lengths, categories, requirements and depots are unchanged from the earlier export.
These are scenario budgets, not feasibility guarantees. No solutions are included. The Status column
says whether a constructive baseline fit the new budget when the instance was built.

Per folder: `instance.txt` (CLIPP instance), `instance.json` (node/road mapping and the `scaling`
provenance: N, W, raw values, adjustments, feasibility), `manifest.json`, `validation.json`,
`roads.geojson` (instance roads with OSM geometry) and `geography.json` (boundary, node coordinates,
excluded roads). The two geometry files are stored with Git LFS.

Compared with `../real_instances/`, these are the same ten whole-city road networks (same streets,
directions, lengths, categories, requirements and depots), but the fleet and time limit follow the
city's size and workload instead of a fixed or witness-derived budget, which makes them harder and
more realistic to plan. No baseline solutions are included.

| City | Junctions | Streets | Vehicles | Time limit | W (veh-h) | Status |
|---|---:|---:|---|---|---:|---|
| Johannesburg | 157,587 | 204,280 | 80 (27S 27M 26L) | 345,145 s (95.87 h) | 6387.0 | witness valid |
| Ljubljana | 30,278 | 34,104 | 20 (7S 7M 6L) | 111,500 s (30.97 h) | 377.3 | witness valid |
| New-York | 132,300 | 182,700 | 101 (34S 34M 33L) | 306,174 s (85.05 h) | 10028.7 | feasibility not established |
| Presheva | 744 | 838 | 4 (1S 2M 1L) | 8,805 s (2.45 h) | 9.8 | feasibility not established |
| Prishtina | 7,400 | 8,729 | 12 (4S 4M 4L) | 42,474 s (11.80 h) | 130.2 | witness valid |
| Shkupi | 13,771 | 16,658 | 16 (6S 5M 5L) | 64,997 s (18.05 h) | 253.4 | witness valid |
| Sydney | 255,428 | 316,886 | 107 (36S 36M 35L) | 480,484 s (133.47 h) | 11436.7 | witness valid |
| Tirana | 16,951 | 19,175 | 16 (5S 6M 5L) | 74,938 s (20.82 h) | 243.5 | witness valid |
| Ulqini | 4,610 | 5,074 | 9 (3S 3M 3L) | 30,714 s (8.53 h) | 77.8 | feasibility not established |
| Vienna | 45,049 | 56,787 | 36 (12S 12M 12L) | 146,378 s (40.66 h) | 1277.9 | witness valid |

© OpenStreetMap contributors, ODbL 1.0
