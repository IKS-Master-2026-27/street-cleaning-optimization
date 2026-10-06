# Requested real OSM city instances

10 of 10 cities packaged and validated. See catalog.json for status and provenance.

Each city folder contains district-XXXX.txt (CLIPP input), district-XXXX.solution.txt (feasible baseline), district-XXXX.json (mapping and validation), roads.geojson (OSM road geometry), geography.json (boundary, coordinates and exclusions), manifest.json (sources, checksums and scenario settings), and validation.json (fresh local and official C++ validation). Keep all districts for a city together.

These are real road networks with generated cleaning demands, fleet and baseline routes. The main directed depot-return component is retained; disconnected or inaccessible roads are reported in geography.json. roads.geojson also retains excluded geometry for audit: use the exclusion list when displaying the service network. Administrative boundary scope is recorded per city; it is not an invented bounding box. Sydney means Australia.

| City | Country | District instances | Folder |
| --- | --- | ---: | --- |
| Prishtina | XK | 1 | Prishtina/ |
| Tirana | AL | 4 | Tirana/ |
| Ulqini | ME | 1 | Ulqini/ |
| Shkupi | MK | 2 | Shkupi/ |
| Presheva | RS | 1 | Presheva/ |
| Ljubljana | SI | 4 | Ljubljana/ |
| Vienna | AT | 8 | Vienna/ |
| New-York | US | 31 | New-York/ |
| Sydney | AU | 54 | Sydney/ |
| Johannesburg | ZA | 32 | Johannesburg/ |

© OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright
