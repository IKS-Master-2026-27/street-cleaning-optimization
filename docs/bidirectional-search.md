# Bidirectional Search (BDS) for Street-Cleaning Optimization

**Implementation:** `clipp/bidirectional_search.py`  
**Tests:** `tests/test_bidirectional_search.py`  
**Benchmark runner:** `scripts/benchmark_bidirectional_search.py`  
**Sequential runner:** `scripts/run_bidirectional_sequential.py`  
**Results:** `data/output/bidirectional_search/`

## 1. Overview

Bidirectional Search (BDS) searches the **street-cleaning plan state space**. The forward search grows plan prefixes from "vehicle 0 leaves the depot"; the backward search grows plan suffixes from "the last vehicle returns to the depot". A solution is formed when a forward prefix and backward suffix meet to form a complete feasible plan.

This is not a shortest-path search between junctions. Shortest-path algorithms (Dijkstra trees and point-to-point bidirectional Dijkstra) are used only to calculate connection times between cleaning tasks. The optimization itself is performed over street-cleaning tasks and vehicle-plan states.

Commands:

```bash
python -m clipp.bidirectional_search data/input/syntetic_generated/instance_B.txt
python -m clipp.bidirectional_search data/input/syntetic_generated/instance_A.txt --mode exact --time-limit 300 --memory-limit-mb 4000
python -m clipp.bidirectional_search data/input/real_instances/Presheva/instance.txt --class-reduction
python -m unittest tests.test_bidirectional_search
python scripts/benchmark_bidirectional_search.py --workers 6 --city-limit 300 --exact-limit 300
python scripts/benchmark_bidirectional_search.py --groups scaling --workers 4 --scaling-limit 60
python scripts/run_bidirectional_sequential.py --plan all --min-free-mb 3000 --memory-limit-mb 4500
```

Requirements: Python 3.10+; standard library only. Valid solutions are written in the repository format under `data/output/bidirectional_search/<bounded|exact>[_classred]/`. The public interface `clipp.bidirectional_search.solve(instance) -> Solution` follows the same interface as the other algorithms. `main.py` and the shared scoring, validation, and objective functions are unchanged.

## 2. Problem model

The implementation follows `clipp/parser.py`, `clipp/validator.py`, and `clipp/scoring.py` without modifying them.

- Every vehicle route starts and ends at the depot, follows streets in a legal direction (`dir = 2` permits both directions), and has total route time at most $T$.
- A vehicle may clean a street it traverses if its capacity is at least the street requirement and the street is not a connector.
- Every mandatory street must be cleaned.
- Coverage counts a street once. Water waste is charged for every cleaning entry, so cleaning the same street more than once cannot improve the score.
- With each street cleaned at most once, the objective is additive.

The score is:

$$
\text{Score} = \alpha \cdot \text{coverage} + (1-\alpha)\cdot\text{efficiency}.
$$

For a cleaning task $j$ assigned to vehicle type $q$, the additive contribution is:

$$
\Delta(j,q) = \alpha\frac{L_j}{L_{\max}} - (1-\alpha)\frac{(q-R_j)L_j}{1000\,W_{\max}}.
$$

The implementation stores these values as exact integers over a common denominator (`Model.value`, `Model.score_of`). Dominance and bound comparisons therefore do not rely on floating-point rounding. The reported score is calculated by the repository's unchanged `calculate_score`; tests check agreement with the additive value to $10^{-9}$.

### 2.1 Task reduction

A task is "clean eligible street $j$ in a legal orientation $a_j \rightarrow b_j$".

In any feasible plan, replace each walk between consecutive cleanings with a shortest path. This preserves the cleaned set and cannot increase route time. Therefore, an optimal plan exists in which each vehicle follows a sequence of cleaning tasks connected by shortest paths.

Optional streets whose contribution is non-positive for every vehicle type are not useful tasks: removing such a cleaning cannot lower the score. A vehicle may clean an optional task only when its own $\Delta(j,q) > 0$.

### 2.2 Search labels

Let $S$ be the bit-set of cleaned tasks and $V$ the exact accumulated value.

| Field | Forward label | Backward label |
|---|---|---|
| State | $(k,u,t,S,V)$ | $(k,a,\tau,S,V)$ |
| Meaning | Vehicle $k$ is at junction $u$, after time $t$; vehicles before $k$ are finished | Vehicle $k$ still has a suffix beginning at $a$, requiring $\tau$ time to return to the depot; vehicles after $k$ are finished |
| Fleet time | $g_f = kT + t$ | $g_b = (C-1-k)T + \tau$ |
| Root | $(0, \text{depot}, 0, \varnothing, 0)$ | $(C-1, \text{depot}, 0, \varnothing, 0)$ |

Both searches have explicit root states. Reversing street directions alone is insufficient: the backward search maintains its own state, remaining time-to-depot, cleaned suffix set, vehicle index, and feasibility checks.

### 2.3 Moves and inverse property

Let $d(x,y)$ be the shortest-path travel time.

**Forward task move.** For task $j=(a,b)$, with $j \notin S$, the vehicle must be able to clean it and:

$$
t + d(u,a) + t_j + d(b,\text{depot}) \leq T.
$$

The successor is:

$$
(k,\ b,\ t + d(u,a) + t_j,\ S \cup \{j\},\ V + \Delta(j,q_k)).
$$

**Backward task move.** For the same task, the backward search adds its service time and the connection to the next suffix task:

$$
\tau' = t_j + d(b, a_{\text{next}}) + \tau,
$$

with feasibility condition:

$$
d(\text{depot}, a) + \tau' \leq T.
$$

The predecessor-side label stores the task's start junction and the updated suffix.

**Vehicle switches.** The forward search closes vehicle $k$, returns it to the depot, and continues with $k+1$. The backward search closes vehicle $k$ and continues with $k-1$.

For a route $(j_1, \dots, j_m)$, its total time is:

$$
d(\text{depot}, a_1) + \sum_i t_{j_i} + \sum_{i=1}^{m-1} d(b_i, a_{i+1}) + d(b_m, \text{depot}).
$$

The forward search accumulates this route from the left and the backward search from the right. At every cut, the forward elapsed time, connecting path, and backward remaining time sum to the route time. Every backward feasibility test is the corresponding forward inequality rearranged.

### 2.4 Meeting condition

A forward label $F=(k,u,t,S_f,V_f)$ and backward label $B=(k,a,\tau,S_b,V_b)$ meet if and only if:

1. They refer to the same vehicle $k$.
2. $S_f \cap S_b = \varnothing$, so no task is cleaned twice.
3. $S_f \cup S_b \supseteq M$, where $M$ is the set of mandatory tasks.
4. $t + d(u,a) + \tau \leq T$ (reconstructed; see the note below).

> **⚠️ Text missing in the source file.** In the uploaded file, the end of condition 4 and the start of Section 3 (including the heading and the first part of 3.1, the halfway theorem) are lost. The line was cut at `(t+d(u,a)+\tau  H)`. The condition above is reconstructed from context (the later text mentions the "within-vehicle time condition"). Please verify it against the original.

## 3. Correctness and exact search

### 3.1 Halfway rule

> **⚠️ The first part of this section is missing in the source file.** Only the end of the proof survives. $H$ is the halfway limit, $H = \lceil CT/2 \rceil$ per Section 3.1 and the test `test_halfway_limit_is_needed`.

… $> H$. Every earlier prefix was expanded, so $x_{c^*}$ was generated. For all later suffixes:

$$
g_b(y_c) \leq CT - g_f(x_c) \leq CT - g_f(x_{c^*}) < CT - H \leq H.
$$

Thus the corresponding backward label was generated, and the two labels satisfy the meeting rule. If no such $c^*$ exists, the complete forward plan meets the backward root. Therefore, the halfway rule does not exclude every meeting for any feasible plan.

The test `test_halfway_limit_is_needed` uses $H=0$ as a negative control: optimal plans can be missed. With $H=\lceil CT/2 \rceil$, the tested plans are not missed.

### 3.2 Dominance

In exact mode, labels on the same side, vehicle, and junction can be compared when they have the same mandatory set. Label $L_1$ dominates $L_2$ when:

- $L_1$'s optional set is a subset of $L_2$'s optional set;
- $L_1$'s time is no greater;
- $L_1$'s value is no lower.

Any meeting possible with $L_2$ is also possible with $L_1$, with no worse value. The mandatory sets must be equal, not merely nested, because changing mandatory coverage would invalidate the coverage argument.

### 3.3 Admissible bound pruning

A label is dropped when:

$$
V + \text{completion\_bound} \leq \text{best known value}.
$$

The admissible completion bound assigns every uncleaned mandatory task its best value over the fleet and adds a fractional-knapsack upper bound (rounded up) for optional tasks over the remaining fleet time. It ignores travel between tasks, so it can be loose on tight instances.

A label is also pruned if an uncleaned mandatory street cannot be served by any remaining vehicle because of capacity, or if remaining mandatory service time exceeds remaining fleet time. A BDS-Bounded plan may seed the incumbent value; this only tightens the bound.

Tests compare all four combinations of dominance and bound pruning and require identical optima on the tested instances.

### 3.4 Termination and practical limits

Every task move consumes at least one time unit and increases the cleaned-task set; vehicle switches also advance the vehicle index. The reachable label set is finite. Both sides are processed in increasing fleet-time order, expanding the side with the smaller next fleet time.

Exact mode requires the all-pairs table and refuses instances with more than 1,500 junctions. Its practical limit is approximately 12–16 tasks with two vehicles, depending on the instance.

### 3.5 Exact status meanings

| Status | Meaning |
|---|---|
| `OPTIMAL` | Exact search completed; optimality is proven by the search |
| `FEASIBLE` | A valid plan is returned after a time or memory limit; optimality is not proven |
| `TIMEOUT` | Time limit reached without a known plan |
| `MEMOUT` | Memory limit reached without a known plan |
| `NO_SOLUTION` | Exact search completed without a meeting; infeasibility is proven for the modeled instance |
| `ERROR` | The run could not be performed, for example because the instance exceeds the exact-mode junction limit |

### 3.6 Brute-force verification

`test_exact_matches_brute_force` generates 60 random tiny instances (3–4 junctions, 3–5 streets, random directions, categories, requirements, 1–3 vehicles, and a random $\alpha$; the set of $\alpha$ values was lost in the source, which reads "α ∈ 0.5"). An independent brute-force enumerator explores depot-to-depot walks at junction level, chooses the best feasible cleaning for each combination, and scores plans using `calculate_score`.

BDS-Exact must return the same optimum or report `NO_SOLUTION` exactly when brute force finds no feasible plan. The tests also compare dominance/bound enabled and disabled.

### 3.7 Exact experimental results

The scaling experiment used generated instances with two vehicles, tight $T$, a 60-second limit, and 3,000 MB memory limit. The BDS-Bounded seed was used to tighten the exact bound.

| Tasks | Seed 0 | Seed 1 |
|---|---|---|
| 4–10 | OPTIMAL, at most 0.4 s and 6.4k labels | OPTIMAL, at most 0.4 s |
| 12 | OPTIMAL, score 0.9057, 3.9 s, 103k generated | OPTIMAL, score 1.0000, 1.8 s |
| 14 | OPTIMAL, score 1.0000, 13.6 s, 271k generated, 46 MiB | OPTIMAL, score 1.0000, 0.3 s |
| 16 | FEASIBLE, score 0.9759, time limit, 61 s, 903k generated, 102 MiB | OPTIMAL, score 1.0000, 0.4 s |
| 20 | TIMEOUT, no plan, 61 s, 602k generated | OPTIMAL, score 1.0000, 0.7 s |

Where the seed already scores 1.0, the upper bound proves optimality without expansion. Otherwise, the practical limit is about 12–16 tasks for two vehicles.

On `instance_A` (31 tasks, 4 vehicles), Exact was run for 300 seconds with a 4,000 MB limit. It returned `FEASIBLE_TIMEOUT`, not proven optimal. It expanded 117,500 labels, generated 3.15 million, removed 2.05 million by dominance, stored 1.33 million, and used 671 MiB peak memory. No meeting better than the BDS-Bounded seed score of 0.684622 was found before the time limit. The completion bound did not prune because it ignores travel and is loose on this tight instance.

## 4. BDS-Bounded

BDS-Bounded uses the same label definitions, moves, meeting rule, and reconstruction as Exact, but limits the frontier to keep the search practical. It is approximate: it never reports search-proven `OPTIMAL`, and `optimal_proven` remains false.

### 4.1 Buckets, width, candidates, and diversity

- **Time buckets:** labels are grouped by fleet time $g$, using width `bucket_fraction * T`. Buckets are processed in increasing order, alternating sides according to the next bucket time.
- **Width ($W$):** at most $W$ labels per bucket and side are expanded in a round. Labels landing in the same bucket can be selected again, up to the width limit.
- **Diversity quotas:** labels are grouped into niches based on vehicle, mandatory-coverage band, and depot-distance region. Round-robin selection across niches avoids retaining only the globally highest-ranked labels.
- **Candidates ($K$):** each expansion offers the $K$ best ranked moves plus the $K$ nearest mandatory moves and a vehicle switch.
- **Duplicate states:** identical `(vehicle, junction, cleaned set)` states retain the earliest/best label.
- **Priority:** the base priority is accumulated value plus `mandatory_weight * mandatory_value`. In free-meeting mode, front-to-front guidance penalizes mandatory tasks frequent in the opposite frontier.
- **Large networks:** when there are more than 1,500 junctions, candidates are obtained by a local Dijkstra search (forward graph for forward labels, reversed graph for backward labels); connection streets are stored in the label.

### 4.2 Meeting strategies

**Partitioned (default).** Mandatory tasks are divided into forward and backward shares, separately for each requirement class, using a cut in service time. A side may clean only its own share and a label can meet only after completing its mandatory share. This makes the share-coverage checks local, but restricts the plan space.

**Free.** Neither side is restricted to a preassigned share. A meeting must satisfy the full complementary mandatory-set rule. It rarely meets on the tested synthetic instances because pruned frontiers seldom produce complementary mandatory sets.

### 4.3 Overlap and bounded pruning

Bounded mode may expand to $H + \text{overlap} \cdot T$, giving the frontiers a window of shared vehicles. The overlap parameter is not used by Exact mode because Exact relies on the halfway theorem.

Partitioned Bounded mode also prunes labels whose remaining mandatory share requires more time than $H + T - g$. This is a heuristic restriction, not an exact completeness guarantee.

### 4.4 Vehicle-class reduction

For city instances, `--class-reduction` is available when every requirement class present on an eligible street (10, 20, 30) has at least one vehicle with exactly that capacity.

Under this restriction, a street may only be cleaned by a vehicle whose capacity equals its requirement. The three requirement classes then share no cleaning tasks and can be solved as three independent BDS runs on the full road network; their routes are combined.

This is a restriction of the original problem. A score below 1.0 does not prove anything about the unrestricted optimum because useful plans may require larger vehicles. However, any valid plan with score 1.0 has full coverage and zero water waste. Since coverage and efficiency are each at most 1, score 1.0 is the global objective maximum, even for the unrestricted problem. Such a result is an objective-bound certificate, not a proof that the restricted search was exhaustive.

Class reduction is not applied to the synthetic instances: their objective coefficients and tight time limits do not justify the restriction.

### 4.5 Bounded parameters

| Parameter | Default (up to 2,000 tasks) | City default | Meaning |
|---|---:|---:|---|
| `bucket_fraction` | 0.02 | 0.02 | Bucket width divided by $T$ |
| `width` ($W$) | 32 | 4 | Labels expanded per bucket and side |
| `candidates` ($K$) | 8 | 4 | Best ranked candidates plus nearest mandatory candidates |
| `diversity` | `quota` | `quota` | Niche quotas or plain top-$W$ |
| `coverage_bands` | 4 | 4 | Mandatory-coverage niche resolution |
| `regions` | 4 | 4 | Depot-distance niche resolution |
| `meeting` | `partitioned` | `partitioned` | Partitioned or free meeting |
| `share_split` | 0.5 | 0.5 | Forward share of each requirement class's service time |
| `guidance` | 0.5 | 0.5 | Front-to-front penalty in free-meeting mode |
| `mandatory_weight` | 64 | 64 | Priority weight for mandatory value |
| `rank` | `nearest` | `nearest` | `nearest` or `density` |
| `overlap` | 1.0 | 1.0 | Extra expansion beyond $H$, in units of $T$ |
| `mandatory_first` | false | false | Offer only mandatory moves until the share is complete |
| `join_attempts` | 32 | 32 | Partner checks per new label |
| `time_limit` | 300 s | 900 s | Wall-clock limit; split over classes with class reduction |
| `memory_limit_mb` | 6,000 | 6,000 | Resident-memory limit |
| `seed` | 0 | 0 | Tie-breaking only |

### 4.6 Bounded status meanings

| Status | Meaning |
|---|---|
| `FEASIBLE` | A valid plan was found; no optimality claim |
| `FEASIBLE_TIMEOUT` | A valid plan was found, but a time limit cut the search |
| `FEASIBLE_MEMOUT` | A valid plan was found, but a memory limit cut the search |
| `NO_MEETING` | Both bounded searches ended without a compatible pair; this does not prove infeasibility |
| `TIMEOUT` | Time limit reached without a plan |
| `MEMOUT` | Memory limit reached without a plan |
| `ERROR` | Invalid configuration, unsupported instance, or another execution error |

## 5. Consolidated BDS results

The table reports one final BDS score per instance: the numerical result from BDS-Bounded or BDS-Exact, whichever produced the valid scored plan. No instance is listed twice.

| Instance | BDS score |
|---|---:|
| `instance_A` | 0.6846 |
| `instance_B` | 0.8246 |
| `instance_C` | 0.8032 |
| `instance_D` | 0.7182 |
| `instance_E` | 0.6501 |
| Presheva | 1.0000 |
| Ulqini | 1.0000 |
| Prishtina | 1.0000 |
| Shkupi | 1.0000 |
| Tirana | 1.0000 |
| Ljubljana | 1.0000 |
| Vienna | 1.0000 |
| New-York | 1.0000 |
| Johannesburg | 1.0000 |
| Sydney | 1.0000 |

The scores for the cities are from BDS-Bounded with vehicle-class reduction. A score of 1.0000 is the maximum possible objective value.

For `instance_A`, the recorded BDS-Exact run timed out but retained the valid BDS-Bounded seed plan (0.684622); the table reports that score once. BDS-Exact did not produce a separate improved score on the tested instances.

### 5.1 BDS status and score notes

| Instance | Final BDS result | Interpretation |
|---|---:|---|
| `instance_A` | 0.684622 | BDS-Bounded feasible solution; not proven optimal |
| `instance_B` | 0.824557 | BDS-Bounded feasible solution; not proven optimal |
| `instance_C` | 0.8032 | Final numerical BDS result |
| `instance_D` | 0.718246 | BDS-Bounded feasible solution; not proven optimal |
| `instance_E` | 0.6501 | Final numerical BDS result |
| Presheva | 1.0000 | Class-reduced result; unrestricted run scored 0.991991 |
| Ulqini | 1.0000 | Global objective upper-bound certificate |
| Prishtina | 1.0000 | Global objective upper-bound certificate |
| Shkupi | 1.0000 | Global objective upper-bound certificate |
| Tirana | 1.0000 | Global objective upper-bound certificate |
| Ljubljana | 1.0000 | Global objective upper-bound certificate |
| Vienna | 1.0000 | Class-reduced result; global objective upper-bound certificate |
| New-York | 1.0000 | Class-reduced result; global objective upper-bound certificate |
| Johannesburg | 1.0000 | Class-reduced result; global objective upper-bound certificate |
| Sydney | 1.0000 | Class-reduced result; global objective upper-bound certificate |

A score of 1.0000 is the maximum possible objective value and therefore certifies global objective optimality. For class-reduced city runs, this certificate comes from the objective upper bound, not from exhaustive search of the unrestricted state space. Scores below 1.0000 are feasible solutions and do not prove unrestricted optimality.

**Averages:** Do not calculate a single BDS average by treating failed or unavailable attempts as zero. The earlier reported mean of 0.9034 applies only to the eight instances with a BDS meeting in that particular experiment set; it is not an average across all 15 final results.

## 6. Baseline reproducibility and provenance

The six executable baseline algorithms were rerun locally on `instance_A`–`instance_E` and Presheva. Their output files were not modified. DP and Greedy Lookahead reproduced the reference table exactly. Several other local results differed from the historical reference table.

Observed explanations in the repository documentation:

- `docs/greedy-lookahead.md` reports Greedy scores of 0.7594 / 0.6835 / 0.6718 on B / C / D, matching the local reruns rather than the historical "Greedy" column (0.6859 / 0.6520 / 0.5928).
- The current `clipp/solver.solve` tries three strategies and adds optional detours on instances with at most 1,500 streets. The reference values appear to correspond to an earlier single-strategy greedy implementation.
- `docs/greedy-lookahead.md` lists recursive-enum values 0.5392 / 0.7238 / 0.6971 / 0.7362 / 0.5972 on A–E. These match the local recursive-enum reruns but appear under the Preprocessing column in the historical reference table.
- `docs/recursive.md` gives Recursive = 0.5539 on `instance_E`, matching the reference value; the current code gives 0.5938.
- The local preprocessing rerun equals the local greedy rerun on every tested instance.
- Evolutionary and Beam Search implementations were not present in the working copy and could not be rerun.

The historical reference table is retained as the non-BDS comparison baseline in Section 5. It must not be described as a fresh rerun of every algorithm against the current working copy.

## 7. BDS-Bounded parameter study

The following study was performed on `instance_A`, `instance_B`, and `instance_D`, one factor at a time, with other parameters at their defaults. `NM` means `NO_MEETING` for that setting. These entries are parameter-study results, not the final scores reported in Section 5. Mean time and mean peak memory are averages over the full set of runs in the study.

| Setting | A | B | D | Meetings | Mean score (met only) | Mean time (s) | Mean peak (MiB) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `width=8` | 0.6846 | NM | 0.6967 | 2/3 | 0.6906 | 1.8 | 23 |
| `width=32` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.8 | 26 |
| `width=128` | 0.7389 | 0.8150 | 0.7083 | 3/3 | 0.7541 | 29.2 | 40 |
| `candidates=4` | 0.6846 | NM | 0.7067 | 2/3 | 0.6956 | 5.8 | 25 |
| `candidates=8` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.8 | 26 |
| `candidates=16` | 0.6846 | 0.8246 | 0.7118 | 3/3 | 0.7403 | 9.2 | 30 |
| `bucket=0.005·T` | 0.7389 | NM | 0.7074 | 2/3 | 0.7232 | 21.5 | 34 |
| `bucket=0.02·T` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 7.0 | 27 |
| `bucket=0.08·T` | 0.6504 | NM | 0.6929 | 2/3 | 0.6716 | 4.8 | 25 |
| `overlap=0` | 0.6846 | 0.8232 | 0.7181 | 3/3 | 0.7420 | 6.7 | 26 |
| `overlap=0.5` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 7.0 | 26 |
| `overlap=1` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.7 | 27 |
| `overlap=2` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 7.2 | 27 |
| `diversity=quota` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.6 | 27 |
| `diversity=none` | NM | NM | 0.7184 | 1/3 | 0.7184 | 6.3 | 30 |
| `meeting=partitioned` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.7 | 27 |
| `meeting=free` | 0.6724 | NM | NM | 1/3 | 0.6724 | 26.0 | 99 |
| `rank=nearest` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 7.0 | 26 |
| `rank=density` | 0.7389 | 0.7850 | 0.6519 | 3/3 | 0.7253 | 6.8 | 26 |
| `mandatory_weight=4` | 0.7389 | 0.8146 | NM | 2/3 | 0.7768 | 6.4 | 26 |
| `mandatory_weight=64` | 0.6846 | 0.8246 | 0.7182 | 3/3 | 0.7425 | 6.8 | 27 |

Findings:

- Diversity quotas were important: quota selection met on 3/3 instances, while plain top-$W$ met on only 1/3.
- Partitioned meeting outperformed free meeting in this study (3/3 versus 1/3).
- Increasing overlap beyond the default had little effect after mandatory candidate slots were added.
- Larger $W$ improved A in some settings but increased runtime and memory.
- `mandatory_first=true` was tested during development and performed worse: A 0.5633 and B 0.7648, with no meeting on D; it was therefore left disabled.

## 8. Large-city experiments

City instances were solved with BDS-Bounded and vehicle-class reduction (Section 4.4), so the three requirement classes were solved as independent runs and their routes combined. Ljubljana used a 1,500-second limit in total (approximately 500 seconds per class). Vienna, New-York, Johannesburg, and Sydney were run sequentially with a 4,800-second per-class limit (up to four hours across the three classes) and a 4,500 MB memory limit.

### 8.1 Final city results

| City | Status | Score | Search runtime (s) | Peak (MiB) | Expanded | Generated | Share-complete labels | Classes meeting | Validation |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Ljubljana | `OPTIMAL_BY_OBJECTIVE_UPPER_BOUND` | 1.0000 | 816.0 | 122 | 1,060,553 | 5,298,935 | 1,042 | 3/3 | Repository and independent validators passed |
| Vienna | `OPTIMAL_BY_OBJECTIVE_UPPER_BOUND` | 1.0000 | 719.7 | 186 | 924,816 | 4,624,080 | 1,106 | 3/3 | Repository and independent validators passed |
| New-York | `OPTIMAL_BY_OBJECTIVE_UPPER_BOUND` | 1.0000 | 8,533.3 | 1,413 | 18,800,778 | 93,986,367 | 18,452 | 3/3 | Repository and independent validators passed |
| Johannesburg | `OPTIMAL_BY_OBJECTIVE_UPPER_BOUND` | 1.0000 | 7,045.8 | 1,548 | 17,769,382 | 88,828,412 | 6,956 | 3/3 | Repository and independent validators passed |
| Sydney | `OPTIMAL_BY_OBJECTIVE_UPPER_BOUND` | 1.0000 | 14,400.0 | 4,403 | 31,284,600 | 156,423,000 | 12,840 | 3/3 | Repository and independent validators passed |

For New-York, the saved solution is `data/output/bidirectional_search/bounded_classred/New-York_instance_solution.txt`. Its saved plan was re-read, accepted by both validators, and rescored to 1.0000.

For Johannesburg, the saved solution is `data/output/bidirectional_search/bounded_classred/Johannesburg_instance_solution.txt`. Its saved plan was re-read, accepted by both validators, and rescored to 1.0000.

### 8.2 Interpretation of city certificates

A valid score of 1.0000 means full coverage and zero water waste. Since the objective cannot exceed 1.0000, this is a global objective upper-bound certificate, including for the unrestricted problem. It does not mean that the class-reduced BDS search exhaustively explored the unrestricted state space.

## 9. Development history and measured findings

The first bounded version used partitioned meeting, overlap 0, $W=16$, $K=8$, density ranking, and mandatory weight 1. It returned `NO_MEETING` on A–E.

On A, the forward side completed its mandatory share only on vehicle 2, while the backward side completed its share only on vehicle 1. The following changes were retained during development:

- overlap to provide a shared-vehicle meeting window;
- $K$ nearest mandatory moves in every expansion;
- mandatory priority weight 64;
- nearest-connection ranking.

The reconstruction bug involving the missing depot-to-first-task connection for vehicles planned entirely backward was found by validation and fixed before the reported valid solutions.

The configurable `share_split` parameter (`--share-split`) was added later; its default of 0.5 preserves the original partition rule.

## 10. Complexity

Let $n$ be the number of tasks and $C$ the number of vehicles.

**BDS-Exact.** The number of labels can grow with the number of reachable cleaned-task subsets, the vehicle count, junction positions, and Pareto width. Each expansion can generate $O(n)$ task children, with constant-time connection lookups after preprocessing. Meeting lookup uses hash-indexed buckets. Bit-set storage is proportional to the number of labels times $n/64$ machine words. The number of possible cleaned sets is the main bottleneck.

**BDS-Bounded.** The frontier is restricted by time buckets, width $W$, and candidate count $K$. A rough worst-case expansion bound is proportional to:

$$
O\left(\frac{CT}{\Delta} \cdot W \cdot K\right),
$$

where $\Delta$ is the bucket width. With an all-pairs table, candidate evaluation is $O(n)$ per expansion; on large networks, a local Dijkstra is used instead. Meeting checks are capped by `join_attempts` per stored label. Live frontier memory depends on the retained labels and their bit-sets, plus parent records.

**Preprocessing.** All-pairs Dijkstra is used for networks with at most 1,500 junctions, with approximate complexity $O(N \cdot M \log N)$. Larger networks use depot trees and local searches.

## 11. Limitations and failure cases

1. **Exact scalability.** Exact search is practical only on small instances (roughly 12–16 tasks with two vehicles in the measured scaling tests). It did not complete on `instance_A` within 300 seconds.
2. **Partition restriction.** Partitioned meeting restricts the plans that can be found because each search side cleans only its assigned share.
3. **Vehicle-class restriction.** Class reduction can exclude useful plans. Only a score of 1.0000 provides a global objective certificate; lower scores do not prove unrestricted optimality.
4. **Loose exact bound.** The exact completion bound ignores travel between tasks and can be weak on tight instances.
5. **Symmetry.** Exact mode does not break symmetry between identical vehicles. This is correct but can cause redundant search.
6. **Large-network runtime.** Local Dijkstra per expansion makes Python execution speed a bottleneck on very large road networks.
7. **Unobservable intermediate state.** In the current implementation, search statistics and meeting details are emitted when a run exits. During a long-running process, labels and incumbent state are held in process memory and are not available through the existing logs. A live progress report would require explicit instrumentation in a future change.

## 12. Visualization

The shared visualization registry `visualization/pipeline/algorithms.py` was intentionally not modified. To register BDS for visualization, add:

```python
"bidirectional_search": Algorithm(
    "Bidirectional Search",
    "clipp.bidirectional_search",
    "solve",
),
```

Then run:

```bash
python visualization/pipeline/build.py Presheva --algorithm bidirectional_search
```

`solve()` uses BDS-Bounded without class reduction. For cities, already generated class-reduced solution files are in validator format and can be copied to the expected visualization output location if visualization of those saved results is required. Do not rerun the search solely to visualize an existing validated solution.

## 13. Test and verification summary

The BDS test suite was reported as 33/33 passing after the configurable `share_split` addition. The wider existing project test suite was reported as 26/26 passing. Earlier solution files were re-read and passed the repository validator and independent validator.

The tests cover, among other things:

- forward/backward inverse construction and meeting feasibility;
- every cut of 200 random task sequences satisfying the meeting rule;
- exact-mode agreement with brute force on 60 tiny random instances;
- dominance and bound pruning preserving the optimum;
- halfway-rule behavior;
- reconstruction and validator acceptance;
- class-reduction behavior and score-certificate conditions;
- `share_split` default equivalence, partition coverage, and CLI validation.

These test counts describe the recorded test runs; this documentation update does not rerun tests or benchmarks.

## 14. Reproducibility and result-record policy

A result is considered a verified score only when:

1. a solution file was saved;
2. the repository validator accepted it;
3. the independent validator accepted it, where that check was performed; and
4. the unchanged repository objective function rescored it.