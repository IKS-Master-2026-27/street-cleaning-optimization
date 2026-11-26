"""Local improvement of DP routes: Or-opt / 2-opt / flips + cheapest insertion.

A route is a service sequence of tasks (oriented streets, see tour.py):

    depot -> task 0 -> ... -> task n-1 -> depot   (shortest paths between tasks)

    time = sum t(task) + sum d(end(task h), start(task h+1)) + depot legs.

The Split DP fixes which tasks a vehicle serves; the order inside a route comes
from the giant tour and contains avoidable deadheading. Here every route is

  1. shortened by local search (first improvement until no move helps):
       * Or-opt  : move a chain of 1-3 consecutive tasks elsewhere (optionally reversed)
       * 2-opt   : reverse a block of two-way tasks (each task flips orientation)
       * flip    : serve a two-way street in the other direction
  2. extended by cheapest insertion: unserved streets with delta > 0 are inserted
     where they add least time, best delta / added-time first, while the route
     stays within T. Then step 1 runs again.
  3. relocated between vehicles: a task moves to the route where it costs least
     (only if that saves total time and loses no score); the freed time goes back
     to step 2. The best evaluated state is kept.

Distance rows come from the memoized oracle, so every d(u, v) is a list lookup.
"""

from .distances import INF, Oracle
from .io import Problem
from .tour import end, orientations, start


class Sequencer:
    def __init__(self, problem: Problem, oracle: Oracle) -> None:
        self.problem = problem
        self.oracle = oracle
        self.depot = problem.depot
        self.rows: dict[int, list[int]] = {}

    def row(self, u: int) -> list[int]:
        r = self.rows.get(u)
        if r is None:
            r = self.rows[u] = (self.oracle.from_depot[0] if u == self.depot
                                else self.oracle.dist_row(u))
        return r

    # -- helpers ----------------------------------------------------------
    def nodes(self, seq: list[int]) -> tuple[list[int], list[int]]:
        p = self.problem
        return [start(p, o) for o in seq], [end(p, o) for o in seq]

    def duration(self, seq: list[int]) -> int:
        p, depot = self.problem, self.depot
        total, cur = 0, depot
        for o in seq:
            total += self.row(cur)[start(p, o)] + p.time[o >> 1]
            cur = end(p, o)
        return total + self.row(cur)[depot]

    def chain_cost(self, chain: list[int]) -> int:
        """Service + internal legs of a chain (without its two outer legs)."""
        p = self.problem
        total = 0
        for h, o in enumerate(chain):
            total += p.time[o >> 1]
            if h:
                total += self.row(end(p, chain[h - 1]))[start(p, o)]
        return total

    def two_way(self, o: int) -> bool:
        return self.problem.direction[o >> 1] == 2

    # -- local search -----------------------------------------------------
    def improve(self, seq: list[int], max_block: int = 40) -> list[int]:
        seq = list(seq)
        improved = True
        while improved:
            improved = (self._flip(seq) or self._or_opt(seq)
                        or self._two_opt(seq, max_block))
        return seq

    def _ends(self, seq):
        """prev_end(h) and next_start(h) helpers with the depot at both ends."""
        s_nodes, e_nodes = self.nodes(seq)
        depot = self.depot
        return ([depot] + e_nodes), (s_nodes + [depot])  # E[h] = end before h, S[h] = start at h

    def _flip(self, seq: list[int]) -> bool:
        p, changed = self.problem, False
        E, S = self._ends(seq)
        for h, o in enumerate(seq):
            if not self.two_way(o):
                continue
            a, b = E[h], S[h + 1]
            old = self.row(a)[start(p, o)] + self.row(end(p, o))[b]
            f = o ^ 1
            new = self.row(a)[start(p, f)] + self.row(end(p, f))[b]
            if new < old:
                seq[h] = f
                E[h + 1], S[h] = end(p, f), start(p, f)
                changed = True
        return changed

    def _or_opt(self, seq: list[int]) -> bool:
        p = self.problem
        n = len(seq)
        for length in (1, 2, 3):
            for i in range(0, n - length + 1):
                E, S = self._ends(seq)
                chain = seq[i:i + length]
                before, after = E[i], S[i + length]
                c_start, c_end = start(p, chain[0]), end(p, chain[-1])
                gain = (self.row(before)[c_start] + self.row(c_end)[after]
                        - self.row(before)[after])
                if gain <= 0:
                    continue
                variants = [(chain, c_start, c_end, 0)]
                if all(self.two_way(o) for o in chain):
                    rev = [o ^ 1 for o in reversed(chain)]
                    variants.append((rev, start(p, rev[0]), end(p, rev[-1]),
                                     self.chain_cost(rev) - self.chain_cost(chain)))
                rest = seq[:i] + seq[i + length:]
                rE = [self.depot] + [end(p, o) for o in rest]
                rS = [start(p, o) for o in rest] + [self.depot]
                best = None
                for j in range(len(rest) + 1):
                    if j == i:
                        continue  # original position
                    a, b = rE[j], rS[j]
                    base = self.row(a)[b]
                    for var, vs, ve, extra in variants:
                        cost = self.row(a)[vs] + self.row(ve)[b] - base + extra
                        if cost < gain and (best is None or cost < best[0]):
                            best = (cost, j, var)
                if best is not None:
                    _, j, var = best
                    seq[:] = rest[:j] + var + rest[j:]
                    return True
        return False

    def _two_opt(self, seq: list[int], max_block: int) -> bool:
        p = self.problem
        n = len(seq)
        E, S = self._ends(seq)
        for i in range(n):
            if not self.two_way(seq[i]):
                continue
            for k in range(i + 1, min(n, i + max_block)):
                if not self.two_way(seq[k]):
                    break
                block = seq[i:k + 1]
                rev = [o ^ 1 for o in reversed(block)]
                a, b = E[i], S[k + 1]
                old = (self.row(a)[start(p, block[0])] + self.chain_cost(block)
                       + self.row(end(p, block[-1]))[b])
                new = (self.row(a)[start(p, rev[0])] + self.chain_cost(rev)
                       + self.row(end(p, rev[-1]))[b])
                if new < old:
                    seq[i:k + 1] = rev
                    return True
        return False

    # -- moves between routes ---------------------------------------------
    def relocate(self, seqs: list[list[int]], capacities: list[int]) -> int:
        """Move single tasks to another vehicle when it saves total time.

        A task leaves route A (saving `gain` seconds) and is inserted where it
        costs least in route B (`cost` seconds, B must stay within T and be able
        to clean it without losing score). Accepted when cost < gain; the time
        freed in A is later used by cheapest insertion. Returns number of moves.
        """
        p = self.problem
        T = p.time_limit
        durations = [self.duration(s) for s in seqs]
        moves = 0
        for a in range(len(seqs)):
            h = 0
            while h < len(seqs[a]):
                seq_a = seqs[a]
                o = seq_a[h]
                j = o >> 1
                prev_end = self.depot if h == 0 else end(p, seq_a[h - 1])
                next_start = self.depot if h == len(seq_a) - 1 else start(p, seq_a[h + 1])
                gain = (self.row(prev_end)[start(p, o)] + p.time[j]
                        + self.row(end(p, o))[next_start] - self.row(prev_end)[next_start])
                d_a = p.delta(j, capacities[a])
                best = None
                for b in range(len(seqs)):
                    if b == a:
                        continue
                    d_b = p.delta(j, capacities[b])
                    if d_b is None or (d_a is not None and d_b < d_a - 1e-15):
                        continue
                    slack = T - durations[b]
                    if p.time[j] > slack:
                        continue
                    E, S = self._ends(seqs[b])
                    for oo in orientations(p, j):
                        so, eo = start(p, oo), end(p, oo)
                        row_e = self.row(eo)
                        for k in range(len(seqs[b]) + 1):
                            ra = self.row(E[k])
                            cost = ra[so] + p.time[j] + row_e[S[k]] - ra[S[k]]
                            if cost <= slack and cost < gain and (best is None or cost < best[0]):
                                best = (cost, b, k, oo)
                if best is None:
                    h += 1
                    continue
                cost, b, k, oo = best
                del seq_a[h]
                seqs[b].insert(k, oo)
                durations[a] -= gain
                durations[b] += cost
                moves += 1
        return moves

    # -- cheapest insertion -----------------------------------------------
    def insert(self, seq: list[int], capacity: int, candidates: set[int]) -> list[int]:
        """Insert streets from `candidates` (removed when used) while time allows."""
        p = self.problem
        T = p.time_limit
        seq = list(seq)
        duration = self.duration(seq)
        options = {j: [o for o in orientations(p, j)] for j in candidates
                   if (d := p.delta(j, capacity)) is not None and d > 0}
        while options:
            slack = T - duration
            if slack <= 0:
                break
            E, S = self._ends(seq)
            best = None
            for j, oids in options.items():
                value = p.delta(j, capacity)
                t = p.time[j]
                if t > slack:
                    continue
                for o in oids:
                    so, eo = start(p, o), end(p, o)
                    row_e = self.row(eo)
                    for h in range(len(seq) + 1):
                        a, b = E[h], S[h]
                        ra = self.row(a)
                        to_s = ra[so]
                        if to_s >= INF:
                            continue
                        added = to_s + t + row_e[b] - ra[b]
                        if added <= slack:
                            ratio = value / max(1, added)
                            if best is None or ratio > best[0]:
                                best = (ratio, added, j, o, h)
            if best is None:
                break
            _, added, j, o, h = best
            seq.insert(h, o)
            duration += added
            del options[j]
            candidates.discard(j)
        return seq
