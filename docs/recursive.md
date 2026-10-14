# Recursive solvers

Two construction algorithms next to the greedy baseline, selected with
`--algorithm recursive` or `--algorithm recursive-enum`. Both reuse the
baseline's routes and graph and its rule that a candidate is only feasible while
a shortest return to the depot still fits in the time limit.

A move is a shortest approach path plus one street to clean, so every move
cleans something and the recursion ends after at most one level per eligible
street. Recursive commits the nearest feasible target and rolls back a branch
that pays nothing. Recursive with Enumeration evaluates the width nearest
targets, enumerates their continuations lookahead levels deep and commits the
best value per second; it also enumerates its own budget, so it cannot score
below the plain recursion.

Mandatory streets come before optional ones, vehicles are driven in increasing
capacity, and the depot return is appended last; a repair pass force-assigns
anything left. The cleaning rules are the baseline's unless enhanced=True, which
also cleans the streets a route drives over, prefers a requirement equal to the
capacity and spends leftover vehicle time on optional streets.

Score is alpha * coverage + (1-alpha) * efficiency and is linear in the cleaned
set, so candidates are ranked by value per second. Both algorithms are
deterministic. Recursive costs O(M) levels, the enumerating variant
O(M * width^lookahead) probes. For instance_E the scores are 0.5539006806 and
0.5735244898.
