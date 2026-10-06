# Requested real OSM cities: one whole-city instance per city

Each folder holds exactly one CLIPP instance covering the whole city road network (instance.txt), a feasible baseline solution (instance.solution.txt), the node/road mapping (instance.json), the instance roads as GeoJSON (roads.geojson), the city boundary, node coordinates and excluded roads (geography.json), provenance (manifest.json) and validation (validation.json).

Instances are generated with the same process as the validated district instances, without splitting into districts. Most exceed the official CLIPP validator limits (10,000 nodes, 100,000 streets, 100 vehicles, 1,000,000 s), as agreed with the course professor, so they are checked with the local validator with only those size bounds lifted. All other rules (moves, depot returns, time limit, capacities, mandatory streets) are checked.

| City | Country | Nodes | Streets | Vehicles | Time limit (s) | Within official limits | Folder |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Prishtina | XK | 7,400 | 8,729 | 72 | 28,800 | yes | Prishtina/ |
| Tirana | AL | 16,951 | 19,175 | 75 | 64,800 | no | Tirana/ |
| Ulqini | ME | 4,610 | 5,074 | 92 | 43,200 | yes | Ulqini/ |
| Shkupi | MK | 13,771 | 16,658 | 87 | 64,800 | no | Shkupi/ |
| Presheva | RS | 744 | 838 | 6 | 28,800 | yes | Presheva/ |
| Ljubljana | SI | 30,278 | 34,104 | 94 | 145,800 | no | Ljubljana/ |
| Vienna | AT | 45,049 | 56,787 | 68 | 492,075 | no | Vienna/ |
| New-York | US | 132,300 | 182,700 | 392 | 738,113 | no | New-York/ |
| Sydney | AU | 255,428 | 316,886 | 697 | 818,685 | no | Sydney/ |
| Johannesburg | ZA | 157,587 | 204,280 | 379 | 738,113 | no | Johannesburg/ |

© OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright
