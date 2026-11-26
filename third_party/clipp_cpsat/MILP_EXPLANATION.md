# CLIPP Solver — MILP Formulation & Algorithms Deep Dive

## Table of Contents

1. [Problem at a Glance](#1-problem-at-a-glance)
2. [Why a MILP?](#2-why-a-milp)
3. [Arc-Flow Formulation](#3-arc-flow-formulation)
   - 3.1 [Graph Construction](#31-graph-construction)
   - 3.2 [Decision Variables](#32-decision-variables)
   - 3.3 [Objective Function](#33-objective-function)
4. [Constraints Explained](#4-constraints-explained)
   - 4.1 [Flow Conservation (Closed Walk)](#41-flow-conservation-closed-walk)
   - 4.2 [Time Budget](#42-time-budget)
   - 4.3 [Traversal Before Cleaning](#43-traversal-before-cleaning)
   - 4.4 [Cleaned-Indicator Linkage](#44-cleaned-indicator-linkage)
   - 4.5 [Single-Vehicle Cleaning](#45-single-vehicle-cleaning)
   - 4.6 [Mandatory Coverage](#46-mandatory-coverage)
   - 4.7 [Depot Inclusion (Big-M)](#47-depot-inclusion-big-m)
5. [Why Subtour Elimination?](#5-why-subtour-elimination)
   - 5.1 [What Is a Subtour?](#51-what-is-a-subtour)
   - 5.2 [Why Flow Conservation Isn't Enough](#52-why-flow-conservation-isnt-enough)
   - 5.3 [Our Lazy Cutting-Plane Approach](#53-our-lazy-cutting-plane-approach)
   - 5.4 [The Subtour Cut](#54-the-subtour-cut)
   - 5.5 [Why Lazy Instead of Upfront?](#55-why-lazy-instead-of-upfront)
6. [Route Reconstruction: Hierholzer's Algorithm](#6-route-reconstruction-hierholzers-algorithm)
   - 6.1 [Why Eulerian Circuits?](#61-why-eulerian-circuits)
   - 6.2 [How Hierholzer's Algorithm Works](#62-how-hierholzers-algorithm-works)
   - 6.3 [Step-by-Step Example](#63-step-by-step-example)
   - 6.4 [Connectivity Repair (Bridge Insertion)](#64-connectivity-repair-bridge-insertion)
7. [Feasibility Pre-Check (Dijkstra)](#7-feasibility-pre-check-dijkstra)
8. [Solver Pipeline Summary](#8-solver-pipeline-summary)

---

## 1. Problem at a Glance

The **Climate-Integrated Street Cleaning Routing Problem (CLIPP)** asks:

> Given a city's street network, a fleet of heterogeneous cleaning vehicles, and a time budget, plan routes for all vehicles to **maximise the total length of streets cleaned** while **minimising water waste**, ensuring all mandatory streets are cleaned and every vehicle returns to the depot.

Key challenges:

- **Multiple vehicles** with different water capacities (S/M/L).
- **Three street categories**: Mandatory (must clean), Optional (reward for cleaning), Connector (traversal-only, no cleaning).
- **Capacity matching**: A small vehicle can't clean a heavy-requirement street.
- **Coverage vs efficiency trade-off**: α controls how strongly coverage is prioritized vs low waste.
- **Shared time budget**: Every vehicle must complete its route within T seconds.

---

## 2. Why a MILP?

This is a variant of the **Capacitated Arc Routing Problem (CARP)** — NP-hard in general. We choose a **Mixed-Integer Linear Programming** formulation because:

1. **Exactness**: MILP solvers (we use Google OR-Tools CP-SAT) can prove optimality or give bounded gaps, unlike pure heuristics.
2. **Expressiveness**: All constraints (flow conservation, time budget, capacity matching, mandatory coverage) are naturally linear.
3. **Arc-flow modelling**: Instead of enumerating exponentially many route sequences, we count how many times each arc is traversed. This keeps the variable count polynomial in the network size.
4. **Solver technology**: Modern CP-SAT is extremely efficient at branch-and-bound with clause learning, making it practical for instances with thousands of streets.

---

## 3. Arc-Flow Formulation

### 3.1 Graph Construction

The city is a mixed graph (some streets are one-way, some two-way). We convert it to a **pure directed graph**:

- **One-way street** j (A→B): creates **one arc** (A, B, j).
- **Two-way street** j (A↔B): creates **two arcs** (A, B, j) and (B, A, j).

This is implemented in `clipp/graph.py :: build_arcs()`. The result is a list of directed arcs, plus lookup dictionaries for outgoing arcs, incoming arcs, and street-to-arc mappings.

### 3.2 Decision Variables


| Variable  | Type         | Meaning                                   |
| --------- | ------------ | ----------------------------------------- |
| `f[a, k]` | Integer ≥ 0 | Number of times vehicle k traverses arc a |
| `x[j, k]` | Binary       | 1 if vehicle k cleans street j            |
| `y[j]`    | Binary       | 1 if street j is cleaned by*any* vehicle  |

**Why integer flow variables instead of binary?** Because a vehicle may need to traverse the same arc multiple times (e.g., traversing a street to reach another and then coming back). The flow variable naturally captures this multiplicity.

**Variable fixing**: If vehicle k cannot clean street j (capacity too low, or j is a connector), `x[j,k]` is fixed to 0 at model construction time. This eliminates useless variables and significantly tightens the formulation.

### 3.3 Objective Function

```
Maximise: α × Coverage + (1 − α) × Efficiency

Coverage   = (Σ_j ℓ_j · y_j) / L_max
Efficiency = 1 − (Σ_j Σ_k [(q_k − r_j) · ℓ_j / 1000] · x[j,k]) / W_max

L_max = Σ_j ℓ_j                       (all mandatory + optional streets)
W_max = Σ_j [(30 − r_j) · ℓ_j / 1000] (all mandatory + optional streets)
```

- **Coverage** rewards cleaning a larger share of cleanable streets.
- **Efficiency** rewards lower water waste relative to the worst-case Large-vehicle baseline.

The waste for one cleaning event: vehicle k cleans street j → it uses `q_k` L/km but only `r_j` L/km was needed → excess is `(q_k − r_j)` L/km × `ℓ_j / 1000` km = wasted litres.

**Implementation detail**: Since α can be fractional and CP-SAT requires integer coefficients, the objective coefficients are scaled by a large integer constant. This doesn't change the optimal solution, only the internal numeric scale.

---

## 4. Constraints Explained

### Running Example

We'll use this tiny city throughout all constraint examples:

```
Junctions:  0 (depot), 1, 2, 3, 4
Time budget: T = 100 seconds
Weight: alpha = 0.5

Streets:
  Street 0: 0 ↔ 1  (two-way, Mandatory,  length=200m, cost=10s, requirement=5 L/km)
  Street 1: 1 → 2   (one-way,  Optional,   length=300m, cost=15s, requirement=3 L/km)
  Street 2: 2 ↔ 3   (two-way, Mandatory,  length=150m, cost=8s,  requirement=8 L/km)
  Street 3: 3 → 0   (one-way,  Connector,  length=100m, cost=5s,  requirement=—)
  Street 4: 1 ↔ 4   (two-way, Optional,   length=250m, cost=12s, requirement=4 L/km)
  Street 5: 4 → 2   (one-way,  Optional,   length=180m, cost=9s,  requirement=6 L/km)

Vehicles:
  k0: Large  (capacity L, water rate q=10 L/km)
  k1: Small  (capacity S, water rate q=4  L/km)

Directed arcs (after build_arcs):
  a0: 0→1 (street 0)    a1: 1→0 (street 0)    ← two-way
  a2: 1→2 (street 1)                            ← one-way
  a3: 2→3 (street 2)    a4: 3→2 (street 2)    ← two-way
  a5: 3→0 (street 3)                            ← one-way
  a6: 1→4 (street 4)    a7: 4→1 (street 4)    ← two-way
  a8: 4→2 (street 5)                            ← one-way
```

---

### 4.1 Flow Conservation (Closed Walk)

```
For every junction u and vehicle k:
    Σ (flow leaving u by k) = Σ (flow entering u by k)
```

**Why**: This is the fundamental constraint that makes every vehicle's traversal form a **closed walk** (a walk that starts and ends at the same node). Since flow-in equals flow-out at every junction, the vehicle can never "get stuck" — it always has a way to continue and eventually return.

**Analogy**: Think of it like water flowing through pipes. If 3 units of water flow into a junction, exactly 3 must flow out. No water accumulates or vanishes.

**Without this**: Vehicles could teleport — visiting disconnected parts of the city without actually traversing the connecting streets.

#### How (Example)

Suppose vehicle k0 takes the route: **0 → 1 → 2 → 3 → 0**.

The flow values are: `f[a0,k0]=1` (0→1), `f[a2,k0]=1` (1→2), `f[a3,k0]=1` (2→3), `f[a5,k0]=1` (3→0).

Check flow conservation at every junction for k0:

| Junction | Flow out | Flow in | Balanced? |
|----------|----------|---------|-----------|
| 0 | f[a0]=1 (→1) | f[a5]=1 (←3) | 1 = 1 ✓ |
| 1 | f[a2]=1 (→2) | f[a0]=1 (←0) | 1 = 1 ✓ |
| 2 | f[a3]=1 (→3) | f[a2]=1 (←1) | 1 = 1 ✓ |
| 3 | f[a5]=1 (→0) | f[a3]=1 (←2) | 1 = 1 ✓ |
| 4 | 0 | 0 | 0 = 0 ✓ |

Now consider an **invalid** assignment: k0 goes 0 → 1 → 2 but stops (doesn't return).

Flows: `f[a0,k0]=1`, `f[a2,k0]=1`.

| Junction | Flow out | Flow in | Balanced? |
|----------|----------|---------|-----------|
| 0 | 1 | 0 | 1 ≠ 0 **✗** |
| 2 | 0 | 1 | 0 ≠ 1 **✗** |

The constraint catches this — the vehicle must complete a closed walk.

### 4.2 Time Budget

```
For every vehicle k:
    Σ_a (cost_a × f[a,k]) ≤ T
```

**Why**: Every arc traversal takes time. The total traversal time for a vehicle must fit within the shared budget T. This is a hard constraint — violating it makes the solution invalid.

#### How (Example)

Vehicle k0 takes route 0 → 1 → 2 → 3 → 0.

```
Total time = cost(a0) + cost(a2) + cost(a3) + cost(a5)
           = 10      + 15      + 8       + 5
           = 38 seconds
```

Since 38 ≤ 100 (= T), this is **feasible** ✓.

Now suppose k1 wants: 0 → 1 → 4 → 1 → 2 → 3 → 2 → 3 → 0 (a longer, looping route).

```
Total time = 10 + 12 + 12 + 15 + 8 + 8 + 8 + 5 = 78 seconds
```

Still feasible (78 ≤ 100) ✓. But if T were 60, this route would be **rejected** (78 > 60) ✗.

### 4.3 Traversal Before Cleaning

```
For every non-connector street j and vehicle k:
    Σ (traversals of street j's arcs by k) ≥ x[j,k]
```

**Why**: A vehicle cannot clean a street it has never visited. If `x[j,k] = 1` (vehicle k cleans street j), then it must have traversed at least one of street j's arcs at least once. If `x[j,k] = 0`, the constraint is trivially satisfied (≥ 0).

#### How (Example)

Street 2 (2 ↔ 3) has arcs a3 (2→3) and a4 (3→2). Can k0 claim to clean street 2?

**Case A** — k0's route passes through 2→3 (`f[a3,k0]=1`):

```
Σ traversals of street 2 by k0  =  f[a3,k0] + f[a4,k0]  =  1 + 0  =  1
x[2, k0] = 1  →  need ≥ 1  →  1 ≥ 1 ✓  (can clean)
```

**Case B** — k0's route never touches junctions 2 or 3:

```
Σ traversals of street 2 by k0  =  0 + 0  =  0
x[2, k0] = 1  →  need ≥ 1  →  0 ≥ 1 ✗  (BLOCKED — can't claim cleaning)
x[2, k0] = 0  →  need ≥ 0  →  0 ≥ 0 ✓  (fine, not cleaning)
```

**Note**: Street 3 (3 → 0) is a Connector — it has no `x` variable at all, so this constraint doesn't apply to it.

### 4.4 Cleaned-Indicator Linkage

```
(a) x[j,k] = 1  →  y[j] = 1       for all j, k
(b) y[j] = 1    →  at least one x[j,k] = 1    for all j
```

**Why**: We need `y[j]` to faithfully reflect whether *any* vehicle cleans street j:

- **(a)** prevents the model from "forgetting" to score a street that was cleaned.
- **(b)** prevents the model from claiming a street is cleaned when no vehicle actually did it (which would inflate the objective dishonestly).

Together: `y[j] = 1 ⟺ ∃k : x[j,k] = 1`.

**Implementation**: In OR-Tools, (a) is `add_implication(x[j,k], y[j])` and (b) is `add_bool_or([x[j,0], x[j,1], ..., NOT y[j]])`.

#### How (Example)

Street 1 (1 → 2, Optional). Suppose k0 cleans it: `x[1,k0] = 1`, `x[1,k1] = 0`.

**Rule (a)**: x[1,k0] = 1 → y[1] must be 1 ✓ (the objective will count street 1's 300m length).

**Rule (b)**: y[1] = 1 → at least one of {x[1,k0], x[1,k1]} must be 1 → x[1,k0] = 1 ✓.

Now suppose **neither vehicle cleans** street 1: x[1,k0] = 0, x[1,k1] = 0.

**Without rule (b)**, the solver could set y[1] = 1 anyway — claiming 300m of free coverage in the objective without any vehicle actually doing the work. Rule (b) prevents this:

```
y[1] = 1 → at least one of {x[1,k0], x[1,k1]} = 1
         → at least one of {0, 0} = 1
         → FALSE  ✗  (constraint violated, so y[1] is forced to 0)
```

### 4.5 Single-Vehicle Cleaning

```
For every non-connector street j:
    Σ_k x[j,k] ≤ 1
```

**Why**: The problem allows redundant cleaning (two vehicles cleaning the same street), but the length is scored only once while water waste accumulates for both. It's *always* suboptimal to have two vehicles clean the same street. This constraint eliminates a large portion of the search space the solver would otherwise waste time on.

#### How (Example)

Street 4 (1 ↔ 4, Optional, 250m, requirement 4 L/km). What if both vehicles clean it?

```
x[4, k0] = 1  (Large,  q=10 L/km)
x[4, k1] = 1  (Small,  q=4  L/km)
Σ_k x[4,k] = 2 > 1  ✗  constraint violated!
```

**Why this is always bad** — even without the constraint, the objective penalises it:

```
Coverage reward:  250m  (counted once via y[4], regardless of how many vehicles clean it)
Waste from k0:    (10 − 4) × 250/1000 = 1.50 L
Waste from k1:    (4 − 4)  × 250/1000 = 0.00 L
Total waste:      1.50 L  (efficiency decreases accordingly)
```

If only k1 cleans it:
```
Coverage: 250m (same)    Waste: 0.00 L    Better efficiency
```

Duplicate cleaning adds waste with no extra coverage. The constraint saves the solver from exploring these dominated solutions.

### 4.6 Mandatory Coverage

```
For every mandatory street j:
    y[j] = 1
```

**Why**: This is the hard requirement — all mandatory streets must be cleaned. A solution missing any mandatory street is invalid.

**Relaxation mechanism**: Before solving, we run a Dijkstra-based reachability check. If a mandatory street is provably unreachable within the time budget (e.g., too far from the depot for any vehicle to reach, clean, and return), its hard constraint is relaxed. This prevents the solver from declaring the entire problem infeasible when it's just a few remote streets that are physically impossible.

#### How (Example)

Streets 0 and 2 are Mandatory in our example:

```
Street 0 (0 ↔ 1, M):  y[0] = 1  →  some vehicle must clean it
Street 2 (2 ↔ 3, M):  y[2] = 1  →  some vehicle must clean it
```

Streets 1, 4, 5 are Optional — no hard constraint. The solver cleans them only if it improves the objective.

**Relaxation scenario**: Imagine T = 20 (very tight budget). To clean street 2 (2↔3, cost 8s), a vehicle must also reach junction 2 and return to depot. The cheapest round-trip:

```
Depot(0) → 1 → 2 → 3 → 0:  cost = 10 + 15 + 8 + 5 = 38s > 20 = T
```

No route can reach street 2 and return within 20 seconds. The Dijkstra pre-check detects this and relaxes `y[2] = 1` so the solver doesn't declare the whole problem infeasible. Instead, it still cleans street 0 (reachable: 0→1→0 costs 10+10=20 ≤ 20) and does its best.

### 4.7 Depot Inclusion (Big-M)

```
For every vehicle k:
    Σ_a f[a,k] ≤ M · Σ (arcs leaving depot by k)
```

Where M is a very large constant (sum of all arc upper bounds + 1).

**Why**: Flow conservation guarantees a closed walk, but doesn't say *where* the walk starts. In theory, a vehicle could form a closed walk that loops around some part of the city without ever touching the depot. This constraint forces depot inclusion:

- **If vehicle k uses any arcs** (LHS > 0): it must have at least one outgoing arc from the depot (RHS > 0 because the sum is multiplied by huge M).
- **If vehicle k is unused** (depot outgoing = 0): RHS = 0, so LHS must be 0 — no arcs at all. The vehicle simply stays parked.

Combined with flow conservation (flow-in = flow-out at every node including the depot), this guarantees the closed walk passes through the depot.

#### How (Example)

Depot = junction 0. Arcs leaving the depot: a0 (0→1). Suppose M = 50.

**Case 1 — k1 uses some arcs but includes the depot:**

```
k1's route: 0 → 1 → 0  (f[a0,k1]=1, f[a1,k1]=1)

LHS = f[a0,k1] + f[a1,k1] + ... = 1 + 1 = 2
RHS = M × Σ(depot outgoing by k1) = 50 × f[a0,k1] = 50 × 1 = 50

2 ≤ 50 ✓
```

**Case 2 — k1 forms a loop away from depot (1 → 4 → 1):**

Flows: f[a6,k1]=1 (1→4), f[a7,k1]=1 (4→1). Flow conservation is satisfied at junctions 1 and 4.

```
LHS = 0 + 0 + 0 + 0 + 0 + 0 + 1 + 1 + 0 = 2
RHS = M × f[a0,k1] = 50 × 0 = 0     (no arcs leave depot)

2 ≤ 0 ✗  VIOLATED — this loop is banned!
```

**Case 3 — k0 is unused (stays parked):**

```
LHS = 0  (no arcs at all)
RHS = 50 × 0 = 0

0 ≤ 0 ✓  (vehicle sits idle, perfectly fine)
```

The Big-M value only needs to be large enough to never be the binding constraint when the depot *is* included. In practice we set `M = Σ upper_bounds + 1` to guarantee this.

---

## 5. Why Subtour Elimination?

### 5.1 What Is a Subtour?

A **subtour** is a closed walk that is **disconnected from the depot**. For example, vehicle k might have:

- A main loop: depot → A → B → depot
- A separate loop: C → D → E → C (never touches the depot)

Both satisfy flow conservation (flow-in = flow-out at every node). The depot constraint only checks that *if any arcs are used, the depot is visited* — it doesn't check that *all* arcs are part of one connected route.

### 5.2 Why Flow Conservation Isn't Enough

Flow conservation says: "at every junction, what goes in comes out." This allows **multiple disconnected cycles**:

```
Depot ← → A ← → B      (connected to depot ✓)
C ← → D ← → E          (disconnected subtour ✗)
```

Both cycles independently satisfy flow conservation. The depot constraint forces the depot to have flow, but doesn't prevent the separate C-D-E cycle from existing alongside it.

In a real solution, the vehicle can only follow one connected path. The C-D-E cycle is physically impossible — the vehicle would need to teleport there.

### 5.3 Our Lazy Cutting-Plane Approach

Instead of adding an exponential number of subtour constraints upfront (one for every possible subset of nodes), we use an **iterative lazy approach**:

1. **Solve** the model without subtour constraints.
2. **Inspect** the solution: for each vehicle, build the multigraph of its used arcs and find weakly-connected components.
3. **For each component not containing the depot**: add a constraint that cuts it off.
4. **Re-solve** with the new constraints (warm-started from the previous solution).
5. **Repeat** until no subtours exist or the time budget runs out.

**Why iterative?** In practice, most solutions have zero or very few subtours. Adding all possible constraints upfront would bloat the model with millions of constraints for large instances. The lazy approach only adds the few that are actually violated.

### 5.4 The Subtour Cut

For a disconnected component C (not containing the depot):

```
Σ (flow on arcs internal to C by vehicle k)
    ≤
(1 + Σ upper_bounds_internal) × Σ (flow on arcs entering C from outside by vehicle k)
```

**Intuition**: The internal flow in C can be positive **only if** there's positive flow entering C from outside. If no arcs enter C, the flow inside must be zero — killing the subtour.

**Special case**: If no entering arcs physically exist (the component is unreachable), we directly set all internal flow variables to 0.

### 5.5 Why Lazy Instead of Upfront?


| Approach              | Number of constraints         | Practical?                                         |
| --------------------- | ----------------------------- | -------------------------------------------------- |
| Upfront (all subsets) | 2^N (exponential)             | No — impossible for N > 30                        |
| Lazy (violated only)  | Typically 0–10 per iteration | Yes — very fast convergence                       |
| MTZ-style             | O(N²)                        | Possible but weakens LP relaxation for arc routing |

Our lazy approach converges in 1–5 iterations on all tested instances. Each iteration typically finds 0–3 subtours.

---

## 6. Route Reconstruction: Hierholzer's Algorithm

### 6.1 Why Eulerian Circuits?

The MILP gives us **flow values** — how many times each arc is traversed by each vehicle — but not the actual **sequence of junctions**. We need to convert flows into a concrete route.

A set of arc flows that satisfies flow conservation (flow-in = flow-out at every node) defines an **Eulerian multigraph**: a directed graph where each arc appears as many times as its flow value. A fundamental theorem of graph theory states:

> **A connected directed multigraph has an Eulerian circuit (a closed walk that uses every arc exactly once) if and only if every node has equal in-degree and out-degree.**

Our flow conservation constraint guarantees exactly this! So the flow solution defines a multigraph that has an Eulerian circuit, and that circuit is the vehicle's route.

### 6.2 How Hierholzer's Algorithm Works

Hierholzer's algorithm finds an Eulerian circuit in **O(E)** time (linear in the number of edges). It works as follows:

```
Input:  A connected directed multigraph, a start node.
Output: An Eulerian circuit (node sequence).

1. Initialise:
   - stack = [start]
   - circuit = []

2. While stack is not empty:
   a. Let u = top of stack (peek, don't pop).
   b. If u has unused outgoing edges:
      - Pick any unused edge u → v.
      - Remove edge u → v from the graph.
      - Push v onto the stack.
   c. Else (u has no more edges):
      - Pop u from the stack.
      - Append u to circuit.

3. Reverse circuit. Done.
```

**Why this works**: The algorithm builds partial circuits and splices them together. When it reaches a dead end (no more outgoing edges), it backtracks, recording nodes into the circuit. The magic is that it naturally handles the "splicing" — when it backtracks to a node that still has unused edges, it extends from there before continuing the backtrack.

### 6.3 Step-by-Step Example

Consider vehicle k with flows creating this multigraph (depot = 0):

```
0 → 1 → 2 → 0      (main loop)
1 → 3 → 1           (side loop from node 1)
```

Arcs: 0→1, 1→2, 2→0, 1→3, 3→1

**Execution**:


| Step | Stack        | Action                             | Circuit            |
| ---- | ------------ | ---------------------------------- | ------------------ |
| 1    | [0]          | 0 has edge to 1 → push 1          | []                 |
| 2    | [0, 1]       | 1 has edge to 2 → push 2          | []                 |
| 3    | [0, 1, 2]    | 2 has edge to 0 → push 0          | []                 |
| 4    | [0, 1, 2, 0] | 0 has no more edges → pop, record | [0]                |
| 5    | [0, 1, 2]    | 2 has no more edges → pop, record | [0, 2]             |
| 6    | [0, 1]       | 1 has edge to 3 → push 3          | [0, 2]             |
| 7    | [0, 1, 3]    | 3 has edge to 1 → push 1          | [0, 2]             |
| 8    | [0, 1, 3, 1] | 1 has no more edges → pop, record | [0, 2, 1]          |
| 9    | [0, 1, 3]    | 3 has no more edges → pop, record | [0, 2, 1, 3]       |
| 10   | [0, 1]       | 1 has no more edges → pop, record | [0, 2, 1, 3, 1]    |
| 11   | [0]          | 0 has no more edges → pop, record | [0, 2, 1, 3, 1, 0] |

**Reverse**: 0 → 1 → 3 → 1 → 2 → 0

This is a valid Eulerian circuit that uses all 5 arcs exactly once!

### 6.4 Connectivity Repair (Bridge Insertion)

Even after subtour elimination, the final flow solution might have small disconnected components (due to time budget exhaustion during the iterative process). Before running Hierholzer, we check connectivity:

1. **Build** the multigraph for vehicle k from its flow values.
2. **Find** weakly-connected components.
3. **For each component C not containing the depot**:
   - Run Dijkstra from the depot to find the cheapest node in C to bridge to.
   - If adding a round-trip (depot → node → depot) fits within the time budget:
     - Insert the bridge arcs into the multigraph, making it connected.
   - Otherwise: drop the component's arcs entirely (those streets won't be in the route).

This ensures Hierholzer always runs on a connected multigraph.

---

## 7. Feasibility Pre-Check (Dijkstra)

Before calling the solver, we verify that all mandatory streets are reachable:

1. **Forward Dijkstra**: from depot S, compute shortest time to every junction.
2. **Reverse Dijkstra**: reverse all arcs, run Dijkstra from S again → gives shortest time from every junction *back to* the depot.
3. **For each mandatory street j** (A→B):
   - Check: `dist_from_depot[A] + traversal_time[j] + dist_to_depot[B] ≤ T`
   - If two-way, also check the reverse direction.
   - If neither direction fits: the street is **provably unreachable**.

Unreachable mandatory streets have their hard constraint relaxed. The solver can still clean them opportunistically, but won't be forced into infeasibility.

**Algorithm**: Standard Dijkstra with a binary heap, O((V + E) log V) per run. We run it twice (forward + reverse), so O((V + E) log V) total.

---

## 8. Solver Pipeline Summary

```
┌─────────────┐
│ Parse input │  Read instance file → streets, vehicles, parameters
└──────┬──────┘
       ▼
┌─────────────┐
│ Build graph │  Streets → directed arcs, adjacency structures
└──────┬──────┘
       ▼
┌─────────────┐
│ Reachability│  Dijkstra pre-check → identify unreachable mandatory streets
│   check     │
└──────┬──────┘
       ▼
┌─────────────┐
│ Build MILP  │  Variables, constraints, objective → CP-SAT model
└──────┬──────┘
       ▼
┌──────────────────────────────┐
│ Iterative solve              │◄──┐
│  1. Solve model              │   │
│  2. Check for subtours       │   │  (repeat until
│  3. Add subtour cuts         │───┘   no subtours)
└──────┬───────────────────────┘
       ▼
┌─────────────┐
│ Reconstruct │  Flow values → Eulerian circuit per vehicle (Hierholzer)
│   routes    │  + connectivity repair if needed
└──────┬──────┘
       ▼
┌─────────────┐
│ Validate    │  Check all rules: depot start/end, time, capacity, mandatory
└──────┬──────┘
       ▼
┌─────────────┐
│ Score &     │  Compute objective, write solution file
│  output     │
└─────────────┘
```

Each stage is implemented in its own module:


| Module                    | Responsibility                              |
| ------------------------- | ------------------------------------------- |
| `clipp/parser.py`         | Instance file parsing                       |
| `clipp/graph.py`          | Arc construction, Dijkstra, graph utilities |
| `clipp/model.py`          | MILP formulation, subtour elimination       |
| `clipp/reconstruction.py` | Hierholzer, connectivity repair             |
| `clipp/validator.py`      | Solution feasibility checking               |
| `clipp/scoring.py`        | Objective function evaluation               |
| `clipp/io.py`             | Solution file output                        |
| `clipp_solver.py`         | Entry point wiring everything together      |
