"""Solution B: memetic route-first / cluster-second search with several DPs.

Chromosome: a permutation of every useful task (all mandatory streets and all
optional streets with a positive contribution), without route delimiters.

Decoder (all exact DPs for their sub-problem):
  1. exact heterogeneous-fleet Split DP on the mandatory subsequence, which also
     picks the vehicle type of every route (split.split_heterogeneous);
  2. optional tasks follow the route of the preceding mandatory task, and the
     in-route selection DP keeps the best subset that fits in T
     (local_search.select_within);
  3. Held-Karp DP over sliding windows re-orders/re-orients services;
  4. unserved optional streets are inserted at their best value/time ratio.

The memetic loop (order crossover + mutation + replacement of the worst
individual) explores giant tours; the best individual is polished by repeating
assignment (Lemma 1) -> normalisation -> Held-Karp -> insertion until no gain.
Solution A is part of the initial population, so B is never worse than A.

No randomness: starting tours, parent pairs, crossover blocks, mutations and
ruin-and-recreate moves are all enumerated systematically in a fixed order, and
every phase stops after a fixed number of iterations (never on wall-clock time).
The same instance therefore always gives exactly the same solution.
"""

import time

from ..solver import Solution
from .assignment import assign_cleaning, fill_idle_vehicles, route_from_tasks
from .bounds import upper_bound
from .distances import Oracle
from .io import Problem, problem_from_instance
from .local_search import (Dense, held_karp_sweep, insert_unserved, normalize,
                           select_within, value_of)
from .objective import Route, evaluate, to_repo_solution
from .simple import DENSE_LIMIT, Result, solve_simple
from .split import NEG, SplitData, split_heterogeneous, split_ordered, vehicles_for
from .tour import (class_of, make_tour, nearest_neighbor, orientations, select_streets,
                   servable)


# Fixed iteration budgets (they replace the old wall-clock limits).
GENERATIONS = 4000      # crossover children in the memetic loop
STAGNATION = 1500       # stop early after this many generations without a new best
LNS_ITERATIONS = 3000   # ruin-and-recreate moves on the best plan


class Memetic:
    def __init__(self, problem: Problem, oracle: Oracle) -> None:
        self.p = problem
        self.oracle = oracle
        # counters that drive the systematic (non-random) enumeration of moves
        self.mutations = 0
        self.crossovers = 0
        self.lns_moves = 0
        self.dense = Dense(problem, oracle)
        selection = select_streets(problem, oracle)
        self.mandatory = selection.mandatory
        self.optional = selection.optional
        self.universe = set(self.mandatory) | set(self.optional)
        self.counts: dict[int, int] = {}
        for q in problem.capacities:
            self.counts[q] = self.counts.get(q, 0) + 1
        self.is_m = {j: problem.category[j] == "M" for j in self.universe}
        self.ok_oids = {j: [o for o in orientations(problem, j) if servable(problem, oracle, o)]
                        for j in self.universe}

    # ------------------------------------------------------------ fitness
    def fitness(self, seqs: list[list[int]]) -> float:
        total = 1.0 - self.p.alpha
        for v, seq in enumerate(seqs):
            total += value_of(self.p, seq, self.p.capacities[v])
        return total

    # ------------------------------------------------------------ decoder
    def decode(self, chrom: list[int], light: bool = True) -> list[list[int]] | None:
        p = self.p
        m_seq = [oid for oid in chrom if self.is_m[oid >> 1]]
        # Education: Held-Karp windows shorten the giant tour before splitting.
        held_karp_sweep(self.dense, m_seq, 6)
        tour = make_tour(p, self.oracle, m_seq)
        data = SplitData(p, self.oracle, tour)
        result = split_heterogeneous(data, self.counts)
        if result is None:
            result = split_ordered(data, sorted(p.capacities, reverse=True))
        value, segments = result
        if value == NEG:
            return None
        seqs: list[list[int]] = [[] for _ in range(p.num_vehicles)]
        owner_of_m: dict[int, int] = {}
        oriented = {oid >> 1: oid for oid in m_seq}  # orientation chosen by Held-Karp
        for vehicle, seg in vehicles_for(p, segments):
            for oid in m_seq[seg.first:seg.last + 1]:
                owner_of_m[oid >> 1] = vehicle
        # follow the (possibly re-ordered) mandatory sequence, slotting each optional
        # task after the mandatory task that preceded it in the chromosome
        follows: dict[int, list[int]] = {}
        before_first: list[int] = []
        last_m = None
        for oid in chrom:
            if self.is_m[oid >> 1]:
                last_m = oid >> 1
            elif last_m is None:
                before_first.append(oid)
            else:
                follows.setdefault(last_m, []).append(oid)
        current = None
        pending_front = before_first
        for m_oid in m_seq:
            current = owner_of_m[m_oid >> 1]
            if pending_front:
                seqs[current].extend(o for o in pending_front
                                     if (d := p.delta(o >> 1, p.capacities[current])) is not None and d > 0)
                pending_front = []
            seqs[current].append(oriented[m_oid >> 1])
            for oid in follows.get(m_oid >> 1, []):
                d = p.delta(oid >> 1, p.capacities[current])
                if d is not None and d > 0:
                    seqs[current].append(oid)
        for v in range(p.num_vehicles):
            kept = select_within(self.dense, seqs[v], p.capacities[v])
            if kept is None:
                kept = [oid for oid in seqs[v] if self.is_m[oid >> 1]]
            seqs[v] = kept
        self.improve(seqs, light)
        return seqs

    def improve(self, seqs: list[list[int]], light: bool) -> None:
        w = 6 if light else 8
        for seq in seqs:
            held_karp_sweep(self.dense, seq, w)
        insert_unserved(self.dense, seqs, self.p.capacities)
        if not light:
            for seq in seqs:
                held_karp_sweep(self.dense, seq, w)
            insert_unserved(self.dense, seqs, self.p.capacities)

    # ------------------------------------------------- ruin and recreate
    def cheapest_slot(self, seqs: list[list[int]], j: int, exclude: int):
        """Cheapest (route, position, oid) to insert street j, ignoring the time
        limit (callers repair over-long routes with the selection DP)."""
        p, D, dn = self.p, self.dense.D, self.dense
        best = None
        for r, seq in enumerate(seqs):
            if r == exclude or p.capacities[r] < p.requirement[j]:
                continue
            prev = [dn.depot] + [dn.b[o] for o in seq]
            nxt = [dn.a[o] for o in seq] + [dn.depot]
            time_r = dn.time(seq)
            for oid in self.ok_oids[j]:
                a, row_b, t = dn.a[oid], D[dn.b[oid]], p.time[j]
                for pos in range(len(seq) + 1):
                    row_u = D[prev[pos]]
                    extra = row_u[a] + t + row_b[nxt[pos]] - row_u[nxt[pos]]
                    # prefer slots that keep the route within T
                    key = (time_r + extra > p.time_limit, extra)
                    if best is None or key < best[0]:
                        best = (key, r, pos, oid)
        return None if best is None else best[1:]

    def score(self, seqs: list[list[int]]) -> tuple[float, list[Route]]:
        """Exact score of a service plan, including streets cleaned while
        deadheading (optimal assignment, Lemma 1)."""
        routes = self.materialise(seqs)
        assign_cleaning(self.p, routes)
        evaluation = evaluate(self.p, routes)
        return (evaluation.score if evaluation.valid else float("-inf")), routes

    def ruin_recreate(self, seqs: list[list[int]]) -> list[list[int]]:
        """Remove a block of optional services (one route, or a neighbourhood
        across routes), then rebuild with Held-Karp + best-ratio insertion.

        Deterministic: the move type follows a fixed cycle of 40 slots (3 type
        swaps, 11 relocations, 13 route ruins, 13 neighbourhood ruins) and the
        move counter k selects which routes/services are touched."""
        p = self.p
        k = self.lns_moves
        self.lns_moves += 1
        slot = k % 40
        new = [list(s) for s in seqs]
        touched = set()
        if slot < 3 and p.alpha < 1.0:
            # type swap: exchange the plans of two vehicles of different capacity
            pairs = [(x, y) for x in range(len(new)) for y in range(x + 1, len(new))
                     if p.capacities[x] != p.capacities[y]]
            if pairs:
                x, y = pairs[(k // 40 * 3 + slot) % len(pairs)]
                ok = all(p.requirement[o >> 1] <= p.capacities[y] for o in new[x]
                         if self.is_m.get(o >> 1, False)) and \
                    all(p.requirement[o >> 1] <= p.capacities[x] for o in new[y]
                        if self.is_m.get(o >> 1, False))
                if ok:
                    new[x], new[y] = new[y], new[x]
                    for r in (x, y):
                        kept = select_within(self.dense, new[r], p.capacities[r])
                        if kept is None:
                            return [list(s) for s in seqs]
                        new[r] = kept
                    insert_unserved(self.dense, new, p.capacities)
            return new
        if slot < 14:
            # relocate 1-3 mandatory services to their cheapest feasible slot
            m_services = [(r, oid) for r, s in enumerate(new) for oid in s
                          if self.is_m.get(oid >> 1, False)]
            if not m_services:
                return new
            count = min(len(m_services), 1 + k % 3)
            step = max(1, len(m_services) // count)
            first = (k // 3) % len(m_services)
            picked = {m_services[(first + t * step) % len(m_services)] for t in range(count)}
            for r, oid in sorted(picked):
                new[r].remove(oid)
                touched.add(r)
            for r, oid in sorted(set(m_services) - {(r, o) for r, s in enumerate(new) for o in s}):
                slot = self.cheapest_slot(new, oid >> 1, exclude=r if k % 10 < 7 else -1)
                if slot is None:
                    slot = self.cheapest_slot(new, oid >> 1, exclude=-1)
                if slot is None:
                    return [list(s) for s in seqs]
                rr, pos, oo = slot
                new[rr].insert(pos, oo)
                touched.add(rr)
            for rr in touched:
                held_karp_sweep(self.dense, new[rr], 7)
            # routes that grew may now exceed T: drop optional services there
            for rr in touched:
                if self.dense.time(new[rr]) > p.time_limit:
                    kept = select_within(self.dense, new[rr], p.capacities[rr])
                    if kept is None:
                        return [list(s) for s in seqs]
                    new[rr] = kept
            insert_unserved(self.dense, new, p.capacities)
            return new
        if slot < 27:
            r = k % len(new)
            opt = [h for h, oid in enumerate(new[r]) if not self.is_m.get(oid >> 1, False)]
            if opt:
                h0 = (k // len(new)) % len(opt)
                drop = set(opt[h0:h0 + 2 + k % 9])
                new[r] = [oid for h, oid in enumerate(new[r]) if h not in drop]
                touched.add(r)
        else:
            services = [(r, oid) for r, s in enumerate(new) for oid in s]
            if services:
                _, centre = services[(k // 40) % len(services)]
                row = self.dense.D[self.dense.a[centre]]
                ranked = sorted(((row[self.dense.a[oid]], r, oid) for r, oid in services
                                 if not self.is_m.get(oid >> 1, False)))
                for _, r, oid in ranked[:3 + k % 10]:
                    new[r].remove(oid)
                    touched.add(r)
        for r in touched:
            held_karp_sweep(self.dense, new[r], 7)
        insert_unserved(self.dense, new, p.capacities)
        return new

    # ------------------------------------------------------- chromosomes
    def chromosome(self, seqs: list[list[int]]) -> list[int]:
        """Served tasks in route order (largest vehicles first), plus every unserved
        task inserted after the service closest to it."""
        order = sorted(range(len(seqs)), key=lambda v: (-self.p.capacities[v], v))
        chrom = [oid for v in order for oid in seqs[v] if (oid >> 1) in self.universe]
        served = {oid >> 1 for oid in chrom}
        D, b, a = self.dense.D, self.dense.b, self.dense.a
        inserts: dict[int, list[int]] = {}
        for j in sorted(self.universe - served):
            oid = self.ok_oids[j][0] if self.ok_oids[j] else 2 * j
            best_pos, best_d = -1, D[self.p.depot][a[oid]]
            for k, s in enumerate(chrom):
                d = D[b[s]][a[oid]]
                if d < best_d:
                    best_pos, best_d = k, d
            inserts.setdefault(best_pos, []).append(oid)
        out = list(inserts.get(-1, []))
        for k, s in enumerate(chrom):
            out.append(s)
            out.extend(inserts.get(k, []))
        return out

    def start_chromosome(self, second_every: int, mandatory_first: bool) -> list[int]:
        """Deterministic nearest-neighbour tour (every second_every-th step takes
        the second nearest task). With mandatory_first, the mandatory streets are
        ordered by class (largest requirement first) and the optional streets are
        slotted in next to their closest mandatory service."""
        if not mandatory_first:
            return nearest_neighbor(self.p, self.oracle, sorted(self.universe), second_every)
        groups: dict[int, list[int]] = {}
        for j in self.mandatory:
            groups.setdefault(class_of(self.p, j), []).append(j)
        order: list[int] = []
        for q in sorted(groups, reverse=True):
            origin = self.dense.b[order[-1]] if order else None
            order += nearest_neighbor(self.p, self.oracle, groups[q], second_every, origin)
        return self.chromosome_from_order(order)

    def chromosome_from_order(self, order: list[int]) -> list[int]:
        seqs = [order] + [[] for _ in range(self.p.num_vehicles - 1)]
        return self.chromosome(seqs)

    def crossover(self, x: list[int], y: list[int]) -> list[int]:
        """Order crossover (OX) on streets; orientations follow the donor.

        The copied block is chosen systematically: its start advances by a fixed
        stride and its length cycles through n/3 .. n/6 with every call."""
        n = len(x)
        c = self.crossovers
        self.crossovers += 1
        i = (c * 37) % n
        k = min(n - 1, i + max(1, n // (3 + c % 4)))
        middle = x[i:k + 1]
        taken = {oid >> 1 for oid in middle}
        rest = [oid for oid in y if (oid >> 1) not in taken]
        return rest[:i] + middle + rest[i:]

    def mutate(self, chrom: list[int]) -> None:
        """Systematic mutation: even calls reverse a segment (2-opt), odd calls
        move a block of up to 8 tasks; positions advance with a fixed stride."""
        n = len(chrom)
        if n < 4:
            return
        m = self.mutations
        self.mutations += 1
        i = (m * 53) % (n - 1)
        if m % 2 == 0:
            k = min(n - 1, i + 1 + (m // 2) % max(1, n // 4))
            chrom[i:k + 1] = reversed([self._flip(o) for o in chrom[i:k + 1]])
        else:
            block = chrom[i:i + 1 + (m // 2) % 8]
            del chrom[i:i + len(block)]
            pos = (i + len(chrom) // 2 + m) % (len(chrom) + 1)
            chrom[pos:pos] = block

    def _flip(self, oid: int) -> int:
        other = oid ^ 1
        return other if other in self.ok_oids.get(oid >> 1, []) else oid

    # -------------------------------------------------------- polishing
    def materialise(self, seqs: list[list[int]]) -> list[Route]:
        return [route_from_tasks(self.p, self.oracle, v, seqs[v]) for v in range(len(seqs))]

    def polish(self, seqs: list[list[int]]) -> tuple[list[Route], float]:
        best_routes, best_score = None, -1.0
        for _ in range(20):
            score, routes = self.score(seqs)
            if score <= best_score + 1e-12:
                break
            best_routes, best_score = routes, score
            seqs = [normalize(self.p, r) for r in routes]
            self.improve(seqs, light=False)
        return best_routes, best_score


def parent_pairs(size: int) -> list[tuple[int, int]]:
    """All pairs of population ranks, best pairs first (fixed order, no sampling)."""
    return sorted(((a, b) for a in range(size) for b in range(a + 1, size)),
                  key=lambda ab: (ab[0] + ab[1], ab[0]))


def solve_advanced(problem: Problem, oracle: Oracle | None = None, population: int = 24,
                   generations: int = GENERATIONS, stagnation: int = STAGNATION,
                   lns_iterations: int = LNS_ITERATIONS, progress=None) -> Result:
    """Deterministic Solution B. Every phase has a fixed iteration budget, so the
    result never depends on the machine's speed."""
    started = time.perf_counter()
    oracle = oracle or Oracle(problem)
    base = solve_simple(problem, oracle)
    log = [f"Solution A (start): {base.evaluation.score:.6f}"]
    bound = upper_bound(problem, oracle)
    if base.evaluation.score >= bound - 1e-12:
        log.append("Solution A reaches the upper bound: proven optimal, search skipped")
        return Result(base.routes, base.evaluation, base.services, log, time.perf_counter() - started)
    if problem.num_junctions > DENSE_LIMIT:
        log.append("network too large for the dense memetic search; returning Solution A")
        return Result(base.routes, base.evaluation, base.services, log, time.perf_counter() - started)

    mem = Memetic(problem, oracle)
    pop: list[tuple[float, list[int], list[list[int]]]] = []

    def add(seqs):
        if seqs is None:
            return
        fit = mem.fitness(seqs)
        pop.append((fit, mem.chromosome(seqs), seqs))

    start_seqs = [normalize(problem, r) for r in base.routes]
    mem.improve(start_seqs, light=False)
    add(start_seqs)
    start_chrom = pop[0][1]
    # Initial population, built deterministically: mutations of Solution A
    # alternate with nearest-neighbour tours of different second_every rules.
    variants = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    attempts = 0
    while len(pop) < population and attempts < 3 * population:
        attempts += 1
        if attempts % 2:
            chrom = list(start_chrom)
            for _ in range(1 + attempts % 5):
                mem.mutate(chrom)
        else:
            chrom = mem.start_chromosome(second_every=variants[(attempts // 2) % len(variants)],
                                         mandatory_first=attempts % 4 != 0)
        add(mem.decode(chrom))
    pop.sort(key=lambda x: -x[0])
    log.append(f"initial population {len(pop)}, best fitness {pop[0][0]:.6f}")

    # Memetic loop: parents follow a fixed schedule of rank pairs and every third
    # child is mutated; it stops after a fixed number of generations, or earlier
    # after a fixed number of generations without a new best.
    pairs = parent_pairs(len(pop)) if len(pop) > 1 else [(0, 0)]
    gen = improvements = last_gain = 0
    while gen < generations and gen - last_gain < stagnation:
        gen += 1
        a, b = pairs[(gen - 1) % len(pairs)]
        child = mem.crossover(pop[a][1], pop[b][1])
        if gen % 3 == 0:
            mem.mutate(child)
        seqs = mem.decode(child)
        if seqs is None:
            continue
        fit = mem.fitness(seqs)
        if any(abs(fit - f) < 1e-12 for f, _, _ in pop):
            continue
        if fit > pop[-1][0]:
            if fit > pop[0][0]:
                improvements += 1
                last_gain = gen
                if progress:
                    progress(f"  gen {gen}: best fitness {fit:.6f}")
            pop[-1] = (fit, mem.chromosome(seqs), seqs)
            pop.sort(key=lambda x: -x[0])
    log.append(f"memetic: {gen} generations, {improvements} improvements of the best")

    best_routes, best_score = None, -1.0
    for fit, _, seqs in pop[:3]:
        routes, score = mem.polish([list(s) for s in seqs])
        if routes is not None and score > best_score:
            best_routes, best_score = routes, score

    # Large-neighbourhood search on the best plan (accepts equal scores to drift
    # across plateaus); every candidate is scored exactly.
    if best_routes is not None:
        current = [normalize(problem, r) for r in best_routes]
        current_score = best_score
        lns_improvements = 0
        for it in range(1, lns_iterations + 1):
            candidate = mem.ruin_recreate(current)
            score, routes = mem.score(candidate)
            if score >= current_score - 1e-12:
                if score > best_score + 1e-12:
                    best_routes, best_score = routes, score
                    lns_improvements += 1
                    if progress:
                        progress(f"  lns {it}: best score {score:.6f}")
                current = [normalize(problem, r) for r in routes]
                current_score = score
        log.append(f"LNS: {lns_iterations} iterations, {lns_improvements} improvements")
    if best_routes is None or best_score <= base.evaluation.score:
        log.append("Solution A kept (no better individual)")
        return Result(base.routes, base.evaluation, base.services, log, time.perf_counter() - started)
    fill_idle_vehicles(problem, oracle, best_routes)
    evaluation = evaluate(problem, best_routes)
    log.append(f"polished best: {evaluation.score:.6f}")
    services = [normalize(problem, r) for r in best_routes]
    return Result(best_routes, evaluation, services, log, time.perf_counter() - started)


def solve(instance, **_ignored) -> Solution:
    """Solution B behind the shared `main.py --algorithm dp-advanced` interface."""
    problem = problem_from_instance(instance)
    result = solve_advanced(problem)
    return to_repo_solution(problem, result.routes)
