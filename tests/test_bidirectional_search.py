"""Tests for Bidirectional Search (clipp/bidirectional_search.py).

BDS-Exact is compared with an independent brute force that enumerates every
closed walk of every vehicle on tiny random instances (junction level, no
task model), and every returned plan is checked with the repository's
validator and scored with the repository's scoring function.
"""

import itertools
import random
import unittest
from pathlib import Path

from clipp import bidirectional_search as bds
from clipp.parser import Instance, Street, parse_instance
from clipp.scoring import calculate_score
from clipp.solver import VEHICLE_CAPACITIES, Solution, VehicleRoute
from clipp.validator import validate_solution

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "data/input/syntetic_generated"


def make(n, streets, T, types, alpha=1.0, depot=0):
    rows = [Street(i, a, b, d, t, length, cat, req)
            for i, (a, b, d, t, length, cat, req) in enumerate(streets)]
    return Instance(n, len(rows), T, len(types), depot, alpha, rows, list(types))


def random_micro(rng):
    n = rng.randint(3, 4)
    streets = []
    for _ in range(rng.randint(3, 5)):
        a, b = rng.sample(range(n), 2)
        streets.append((a, b, rng.choice((1, 2, 2)), rng.randint(1, 3), rng.randint(1, 9) * 100,
                        rng.choice("MOOC"), rng.choice((10, 20, 30))))
    types = [rng.choice("SML") for _ in range(rng.randint(1, 3))]
    return make(n, streets, rng.randint(4, 7), types, rng.choice((1.0, 0.5, 0.7)))


# ------------------------------------------------------------ brute force
def closed_walks(inst, T):
    """Every depot->depot walk within T, keyed by its set of traversed streets."""
    out = {frozenset(): ([inst.depot], [])}
    stack = [(inst.depot, 0, [inst.depot], [])]
    while stack:
        node, t, junctions, streets = stack.pop()
        for s in inst.streets:
            for x, y in ((s.a, s.b), (s.b, s.a)) if s.direction == 2 else ((s.a, s.b),):
                if x != node or t + s.time > T:
                    continue
                j2, s2 = junctions + [y], streets + [s.id]
                if y == inst.depot:
                    out.setdefault(frozenset(s2), (j2, s2))
                stack.append((y, t + s.time, j2, s2))
    return list(out.values())


def brute_force(inst):
    """Best score over all walk combinations (None if no feasible plan).

    For fixed walks the best cleaning assignment is chosen street by street
    (the score is additive over cleaned streets); the best plan is then
    re-scored with clipp.scoring.calculate_score.
    """
    eligible = [s for s in inst.streets if s.category in "MO"]
    l_max = sum(s.length for s in eligible)
    w_max = sum((30 - s.requirement) * s.length / 1000 for s in eligible)
    a = inst.water_waste_penalty

    def delta(s, cap):
        waste = (cap - s.requirement) * s.length / 1000
        return a * s.length / l_max - ((1 - a) * waste / w_max if w_max else 0)

    walks = [closed_walks(inst, inst.max_time) for _ in inst.vehicle_types]
    caps = [VEHICLE_CAPACITIES[t] for t in inst.vehicle_types]
    best, best_plan = None, None
    for combo in itertools.product(*walks):
        total, cleaned, ok = 0.0, [[] for _ in caps], True
        for s in eligible:
            options = [(delta(s, caps[v]), v) for v, (_, st) in enumerate(combo)
                       if s.id in st and caps[v] >= s.requirement]
            if not options:
                if s.category == "M":
                    ok = False
                    break
                continue
            d, v = max(options)
            if s.category == "M" or d > 0:
                total += d
                cleaned[v].append(s.id)
        if ok and (best is None or total > best + 1e-12):
            best, best_plan = total, (combo, cleaned)
    if best_plan is None:
        return None
    combo, cleaned = best_plan
    routes = [VehicleRoute(v, t, caps[v], inst.depot, list(j), sum(inst.streets[x].time for x in s),
                           list(s), cleaned[v]) for v, (t, (j, s)) in enumerate(zip(inst.vehicle_types, combo))]
    sol = Solution(routes)
    assert validate_solution(inst, sol) == [], validate_solution(inst, sol)
    return calculate_score(inst, sol).score


def solution_of(model, result):
    by_id = {r.vehicle_id: r for r in result.routes}
    return Solution([by_id[v] for v in range(model.instance.num_vehicles)])


class ExactVersusBruteForce(unittest.TestCase):
    def test_exact_matches_brute_force(self):
        rng = random.Random(7)
        checked = infeasible = 0
        for _ in range(60):
            inst = random_micro(rng)
            ref = brute_force(inst)
            model = bds.Model(inst)
            res = bds.bds_exact(model, time_limit=30)
            if ref is None:
                self.assertEqual(res.status, "NO_SOLUTION")
                self.assertTrue(res.optimal_proven)
                infeasible += 1
                continue
            self.assertEqual(res.status, "OPTIMAL")
            sol = solution_of(model, res)
            self.assertEqual(validate_solution(inst, sol), [])
            score = calculate_score(inst, sol).score
            self.assertAlmostEqual(score, ref, places=9)
            self.assertAlmostEqual(res.predicted_score, score, places=9)
            checked += 1
        self.assertGreater(checked, 20)
        self.assertGreater(infeasible, 0)

    def test_dominance_and_bound_do_not_change_the_optimum(self):
        rng = random.Random(11)
        for _ in range(25):
            inst = random_micro(rng)
            values = set()
            for dom, bound in ((True, True), (False, True), (True, False), (False, False)):
                r = bds.bds_exact(bds.Model(inst), time_limit=30, use_dominance=dom, use_bound=bound)
                values.add((r.status, r.value))
            self.assertEqual(len(values), 1, values)

    def test_seeded_exact_through_instance_interface(self):
        rng = random.Random(3)
        for _ in range(15):
            inst = random_micro(rng)
            ref = brute_force(inst)
            rep = bds.solve_detailed(inst, "exact", exact_time_limit=30)
            if ref is None:
                self.assertEqual(rep.status, "NO_SOLUTION")
            else:
                self.assertEqual(rep.status, "OPTIMAL")
                self.assertTrue(rep.valid and rep.optimal_proven)
                self.assertAlmostEqual(rep.score, ref, places=9)


class HalfwayRule(unittest.TestCase):
    def test_halfway_limit_is_needed(self):
        """Negative control: with H = 0 only the roots are expanded and some
        optimal plans are missed; with H = ceil(C*T/2) none are."""
        rng = random.Random(5)
        missed = 0
        for _ in range(40):
            inst = random_micro(rng)
            full = bds.bds_exact(bds.Model(inst), time_limit=30)
            tiny = bds.bds_exact(bds.Model(inst), time_limit=30, halfway=0)
            if full.status == "OPTIMAL" and (tiny.value is None or tiny.value < full.value):
                missed += 1
        self.assertGreater(missed, 0)

    def test_every_cut_of_a_plan_satisfies_the_meeting_rule(self):
        """For random task sequences of one vehicle, the forward prefix and the
        backward suffix at EVERY cut join, and both sides agree on the time
        (reverse moves are the inverse of forward moves)."""
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        model = bds.Model(inst)
        rng = random.Random(1)
        tested = 0
        for _ in range(200):
            k = model.C - 1
            seq = rng.sample(model.allowed[k], rng.randint(1, 4))
            moves = [(j, *rng.choice(model.tasks[j].orientations)) for j in seq]
            f, b = bds.roots(model)
            f = bds.Label(0, k, model.depot, 0, 0, 0, 0, 0, 0, None, None)
            prefixes = [f]
            for j, a, bb in moves:
                f = bds.task_child(model, f, j, a, bb, model.dist(f.node, a))
                if f is None:
                    break
                prefixes.append(f)
            if f is None:
                continue
            suffixes = [b]
            for j, a, bb in reversed(moves):
                b = bds.task_child(model, b, j, a, bb, model.dist(bb, b.node))
                self.assertIsNotNone(b, "backward rejected a move the forward search accepted")
                suffixes.append(b)
            suffixes.reverse()               # suffixes[c] = steps c.. of the plan
            total = prefixes[-1].time + model.to_depot[prefixes[-1].node]
            self.assertEqual(total, suffixes[0].time + model.from_depot[suffixes[0].node])
            for c in range(len(prefixes)):
                F, B = prefixes[c], suffixes[c]
                self.assertEqual(F.time + model.dist(F.node, B.node) + B.time, total)
                if (F.S | B.S) & model.mmask == model.mmask:
                    self.assertIsNotNone(bds.joinable(model, F, B))
                self.assertIsNotNone(bds.joinable(model, F, B, require_cover=False))
            tested += 1
        self.assertGreater(tested, 30)


class Transitions(unittest.TestCase):
    def setUp(self):
        # 0 -> 1 one-way (M, req 30), 1 - 2 two-way (O, req 10), 2 -> 0 one-way connector
        self.inst = make(3, [(0, 1, 1, 2, 1000, "M", 30), (1, 2, 2, 3, 500, "O", 10),
                             (2, 0, 1, 1, 100, "C", 10)], 10, "SL", alpha=0.5)
        self.model = bds.Model(self.inst)

    def test_task_model_and_directions(self):
        m = self.model
        self.assertEqual(len(m.tasks), 2)            # connector is not a task
        by_street = {t.street: t for t in m.tasks}
        self.assertEqual(by_street[0].orientations, ((0, 1),))
        self.assertEqual(set(by_street[1].orientations), {(1, 2), (2, 1)})

    def test_capacity_and_duplicate_cleaning(self):
        m = self.model
        f, _ = bds.roots(m)
        j = next(i for i, t in enumerate(m.tasks) if t.street == 0)
        self.assertIsNone(bds.task_child(m, f, j, 0, 1, 0))       # vehicle 0 is S: 10 < 30
        L = bds.switch_child(m, f)                                  # vehicle 1 is L
        c = bds.task_child(m, L, j, 0, 1, 0)
        self.assertIsNotNone(c)
        self.assertIsNone(bds.task_child(m, c, j, 0, 1, m.dist(c.node, 0)))  # already cleaned

    def test_time_limit(self):
        m = self.model
        f, b = bds.roots(m)
        L = bds.switch_child(m, f)
        j = next(i for i, t in enumerate(m.tasks) if t.street == 0)
        tight = bds.Label(0, 1, 0, 9, 0, 0, 0, 0, 0, None, None)
        self.assertIsNone(bds.task_child(m, tight, j, 0, 1, 0))     # 9 + 2 + back > 10
        self.assertIsNotNone(bds.task_child(m, L, j, 0, 1, 0))

    def test_vehicle_switch(self):
        m = self.model
        f, b = bds.roots(m)
        s = bds.switch_child(m, f)
        self.assertEqual((s.k, s.node, s.time, s.g), (1, m.depot, 0, m.T))
        self.assertIsNone(bds.switch_child(m, s))                   # no vehicle 2
        bs = bds.switch_child(m, b)
        self.assertEqual((bs.k, bs.g), (0, m.T))
        self.assertIsNone(bds.switch_child(m, bs))                  # no vehicle -1

    def test_meeting_conditions(self):
        m = self.model
        f, b = bds.roots(m)
        j = next(i for i, t in enumerate(m.tasks) if t.street == 0)
        F = bds.task_child(m, bds.switch_child(m, f), j, 0, 1, 0)
        self.assertIsNotNone(bds.joinable(m, F, b))                 # covers M, same vehicle
        self.assertIsNone(bds.joinable(m, f, b))                    # different vehicles
        self.assertIsNone(bds.joinable(m, bds.switch_child(m, f), b))  # mandatory uncovered
        B = bds.task_child(m, b, j, 0, 1, m.dist(1, b.node))
        self.assertIsNone(bds.joinable(m, F, B))                    # both clean street 0
        late = bds.Label(0, 1, 1, 10, F.S, 1, 0, 0, 0, None, None)
        self.assertIsNone(bds.joinable(m, late, b))                 # 10 + d(1,0) > T

    def test_exact_reconstruction_is_valid(self):
        res = bds.bds_exact(self.model)
        self.assertEqual(res.status, "OPTIMAL")
        sol = solution_of(self.model, res)
        self.assertEqual(validate_solution(self.inst, sol), [])
        self.assertAlmostEqual(calculate_score(self.inst, sol).score, res.predicted_score)


class RoutesAndFleet(unittest.TestCase):
    def test_empty_routes_and_identical_vehicles(self):
        inst = make(2, [(0, 1, 2, 2, 1000, "M", 10)], 10, "SSS")
        for policy in ("loop", "stay"):
            model = bds.Model(inst)
            res = bds.bds_exact(model)
            res.routes = None
            r = bds._Bounded(model, bds.BoundedParams(empty_routes=policy)).run()
            sol = solution_of(model, r)
            self.assertEqual(validate_solution(inst, sol), [])
            self.assertEqual([x.vehicle_id for x in sol.routes], [0, 1, 2])
            empties = [x for x in sol.routes if not x.cleaned_street_ids]
            self.assertEqual(len(empties), 2)
            for x in empties:
                self.assertEqual(len(x.street_ids) > 0, policy == "loop")
        rep = bds.solve_detailed(inst, "exact")
        self.assertEqual(rep.status, "OPTIMAL")
        self.assertEqual(rep.score, 1.0)

    def test_input_vehicle_order_is_preserved(self):
        inst = parse_instance(SYNTHETIC / "instance_B.txt")
        rep = bds.solve_detailed(inst, "bounded")
        self.assertTrue(rep.valid)
        sol = rep.solution
        self.assertEqual([r.vehicle_type for r in sol.routes], inst.vehicle_types)
        cleaned = [s for r in sol.routes for s in r.cleaned_street_ids]
        self.assertEqual(len(cleaned), len(set(cleaned)))           # never cleaned twice


class BoundedMode(unittest.TestCase):
    def test_valid_scored_and_never_optimal(self):
        for name in ("A", "B"):
            inst = parse_instance(SYNTHETIC / f"instance_{name}.txt")
            rep = bds.solve_detailed(inst, "bounded")
            self.assertEqual(rep.status, "FEASIBLE", name)
            self.assertFalse(rep.optimal_proven)
            self.assertEqual(validate_solution(inst, rep.solution), [])
            self.assertAlmostEqual(calculate_score(inst, rep.solution).score, rep.score)
            self.assertAlmostEqual(rep.predicted_score, rep.score, places=9)

    def test_deterministic(self):
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        a = bds.solve_detailed(inst, "bounded").solution
        b = bds.solve_detailed(inst, "bounded").solution
        self.assertEqual([r.junctions for r in a.routes], [r.junctions for r in b.routes])

    def test_no_meeting_is_reported_not_substituted(self):
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        rep = bds.solve_detailed(inst, "bounded", bds.BoundedParams(candidates=0))
        self.assertEqual(rep.status, "NO_MEETING")
        self.assertFalse(rep.valid)
        old = bds.default_params
        bds.default_params = lambda i: bds.BoundedParams(candidates=0)
        try:
            with self.assertRaises(bds.NoMeetingError):
                bds.solve(inst)
        finally:
            bds.default_params = old

    def test_overlap_parameter_is_bounded_only(self):
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        m = bds.Model(inst)
        H = -(-m.C * m.T // 2)
        self.assertEqual(bds._Bounded(m, bds.BoundedParams(overlap=0.0)).H, H)
        self.assertEqual(bds._Bounded(m, bds.BoundedParams(overlap=1.0)).H, H + m.T)
        self.assertEqual(bds.bds_exact(bds.Model(make(2, [(0, 1, 2, 1, 1, "M", 10)], 4, "S")))
                         .stats["halfway"], 2)


class Limits(unittest.TestCase):
    def test_exact_timeout_never_claims_optimality(self):
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        res = bds.bds_exact(bds.Model(inst), time_limit=0.0)
        self.assertIn(res.status, ("TIMEOUT", "FEASIBLE"))
        self.assertFalse(res.optimal_proven)

    def test_exact_memout(self):
        inst = parse_instance(SYNTHETIC / "instance_A.txt")
        res = bds.bds_exact(bds.Model(inst), max_labels=100)
        self.assertIn(res.status, ("MEMOUT", "FEASIBLE"))
        self.assertFalse(res.optimal_proven)

    def test_bounded_timeout(self):
        inst = parse_instance(SYNTHETIC / "instance_C.txt")
        rep = bds.solve_detailed(inst, "bounded", bds.BoundedParams(time_limit=0.0))
        self.assertIn(rep.status, ("TIMEOUT", "FEASIBLE"))
        self.assertFalse(rep.optimal_proven)

    def test_memory_reading(self):
        peak, current = bds.memory_mb()
        self.assertTrue(peak is None or peak > 0)


class ClassReduction(unittest.TestCase):
    def test_score_one_certificate(self):
        inst = make(3, [(0, 1, 2, 2, 1000, "M", 10), (0, 2, 2, 2, 1000, "O", 30)], 4, "SL", 0.5)
        rep = bds.solve_detailed(inst, "bounded", class_reduction=True)
        self.assertTrue(rep.valid)
        self.assertEqual(rep.score, 1.0)
        self.assertTrue(rep.score_certificate)
        self.assertFalse(rep.optimal_proven)        # the search proved nothing itself
        self.assertEqual(rep.status, "FEASIBLE")

    def test_restriction_can_lose_feasibility(self):
        """Two requirement-10 streets, each needs a whole vehicle; only one S
        truck. Restricted: no plan. Unrestricted: the L truck cleans one."""
        inst = make(3, [(0, 1, 2, 2, 1000, "M", 10), (0, 2, 2, 2, 1000, "M", 10)], 4, "SL", 0.5)
        restricted = bds.solve_detailed(inst, "exact", class_reduction=True)
        self.assertEqual(restricted.status, "NO_SOLUTION")
        full = bds.solve_detailed(inst, "exact")
        self.assertEqual(full.status, "OPTIMAL")
        self.assertLess(full.score, 1.0)
        self.assertEqual(full.score, brute_force(inst))

    def test_not_applicable_without_matching_capacity(self):
        inst = make(2, [(0, 1, 2, 2, 1000, "M", 10)], 4, "L")
        self.assertIsNone(bds.class_reduction_groups(inst))


def _original_partition(model):
    """The pre-``share_split`` rule, copied verbatim: cut each requirement
    class at half of its service time (``2 * acc < total``)."""
    n = model.net.n
    children = [[] for _ in range(n)]
    for v in range(n):
        if model.from_par[v] >= 0:
            children[model.from_par[v]].append(v)
    order, stack, counter = [n] * n, [model.depot], 0
    while stack:
        u = stack.pop()
        order[u] = counter
        counter += 1
        stack.extend(reversed(children[u]))
    share_f, classes = 0, {}
    for j, task in enumerate(model.tasks):
        classes.setdefault(task.requirement, []).append(j)
    for js in classes.values():
        js.sort(key=lambda j: (min(order[a] for a, _ in model.tasks[j].orientations),
                               model.tasks[j].street))
        total, acc = sum(model.tasks[j].time for j in js), 0
        for j in js:
            if 2 * acc < total:
                share_f |= 1 << j
            acc += model.tasks[j].time
    return share_f, ((1 << model.n) - 1) & ~share_f


class ShareSplit(unittest.TestCase):
    """Configurable forward/backward share split of the partitioned meeting."""

    @classmethod
    def setUpClass(cls):
        paths = [SYNTHETIC / f"instance_{x}.txt" for x in "ABCDE"]
        paths.append(ROOT / "data/input/real_instances/Presheva/instance.txt")
        cls.models = {}
        for p in paths:
            inst = parse_instance(p)
            cls.models[p.stem if p.stem != "instance" else p.parent.name] = bds.Model(
                inst, bds._interleaved_order(inst, list(range(inst.num_vehicles))))

    def test_default_is_the_original_half_split(self):
        self.assertEqual(bds.BoundedParams().share_split, 0.5)
        for name, m in self.models.items():
            old = _original_partition(m)
            self.assertEqual(bds._partition(m), old, name)
            self.assertEqual(bds._partition(m, 0.5), old, name)
            for meeting_params in (bds.BoundedParams(), bds.BoundedParams(share_split=0.5)):
                self.assertEqual(tuple(bds._Bounded(m, meeting_params).share), old, name)

    def test_partition_is_complete_disjoint_and_cut_at_the_fraction(self):
        for name, m in self.models.items():
            full = (1 << m.n) - 1
            for split in (0.0, 0.25, 0.4, 0.6, 0.75, 1.0):
                f, b = bds._partition(m, split)
                self.assertEqual(f & b, 0)                    # no task in both shares
                self.assertEqual(f | b, full)                 # no task lost
                self.assertEqual((f | b) & m.mmask, m.mmask)  # every mandatory task placed
                for req in {t.requirement for t in m.tasks}:
                    js = [j for j, t in enumerate(m.tasks) if t.requirement == req]
                    total = sum(m.tasks[j].time for j in js)
                    fwd = sum(m.tasks[j].time for j in js if f >> j & 1)
                    last = max((m.tasks[j].time for j in js if f >> j & 1), default=0)
                    # forward reaches the cut, and stops at the first task that crosses it
                    self.assertGreaterEqual(fwd, split * total - 1e-9, (name, split, req))
                    self.assertLess(fwd - last, split * total + 1e-9, (name, split, req))
            self.assertEqual(bds._partition(m, 0.0)[0], 0)
            self.assertEqual(bds._partition(m, 1.0)[1], 0)

    def test_split_moves_mandatory_work_monotonically(self):
        m = self.models["instance_C"]
        sizes = [(bds._partition(m, s)[0] & m.mmask).bit_count() for s in (0.3, 0.4, 0.5, 0.6, 0.7)]
        self.assertEqual(sizes, sorted(sizes))
        self.assertLess(sizes[0], sizes[-1])

    def test_invalid_split_is_rejected(self):
        with self.assertRaises(ValueError):
            bds._partition(self.models["instance_A"], 1.5)

    def test_share_completion_and_candidates_respect_the_split(self):
        m = self.models["instance_C"]
        bd = bds._Bounded(m, bds.BoundedParams(share_split=0.35))
        f, b = bds.roots(m)
        for side, root in ((0, f), (1, b)):
            need = bd.mshare[side]
            done = bds.Label(side, root.k, root.node, 0, need, need.bit_count(), 0, 0, 0, None, None)
            self.assertTrue(bd.complete(done))
            if need:
                low = need & -need
                missing = bds.Label(side, root.k, root.node, 0, need ^ low, 0, 0, 0, 0, None, None)
                self.assertFalse(bd.complete(missing))
            for j, *_ in bd.candidates(root):
                self.assertTrue(bd.share[side] >> j & 1)   # each side only cleans its share

    def test_asymmetric_split_meets_and_reconstructs_valid_plans(self):
        rng = random.Random(21)
        feasible = 0
        for _ in range(40):
            inst = random_micro(rng)
            for split in (0.3, 0.7):
                rep = bds.solve_detailed(inst, "bounded", bds.BoundedParams(share_split=split))
                self.assertIn(rep.status, ("FEASIBLE", "NO_MEETING"))
                self.assertFalse(rep.optimal_proven)
                self.assertEqual(rep.params["share_split"], split)
                if rep.valid:
                    feasible += 1
                    self.assertEqual(validate_solution(inst, rep.solution), [])
                    self.assertAlmostEqual(calculate_score(inst, rep.solution).score, rep.score)
                    cleaned = [s for r in rep.solution.routes for s in r.cleaned_street_ids]
                    self.assertEqual(len(cleaned), len(set(cleaned)))
                    ref = brute_force(inst)
                    self.assertLessEqual(rep.score, ref + 1e-9)   # never above the optimum
        self.assertGreater(feasible, 10)

    def test_default_and_explicit_half_give_identical_runs(self):
        rng = random.Random(8)
        for _ in range(20):
            inst = random_micro(rng)
            a = bds.solve_detailed(inst, "bounded")
            b = bds.solve_detailed(inst, "bounded", bds.BoundedParams(share_split=0.5))
            self.assertEqual((a.status, a.score), (b.status, b.score))
            if a.valid:
                self.assertEqual([r.junctions for r in a.solution.routes],
                                 [r.junctions for r in b.solution.routes])

    def test_cli_accepts_share_split(self):
        import io
        from contextlib import redirect_stdout
        tiny = ROOT / "data/output/bidirectional_search/exact_scaling/instances/scale_n04_s0.txt"
        if not tiny.exists():
            self.skipTest("generated scaling instance not present")
        out = io.StringIO()
        with redirect_stdout(out):
            bds.main([str(tiny), "--share-split", "0.4", "--json", "--no-write"])
        line = [l for l in out.getvalue().splitlines() if l.startswith("{")][-1]
        import json
        self.assertEqual(json.loads(line)["params"]["share_split"], 0.4)


class BidirectionalDijkstraSupport(unittest.TestCase):
    def test_matches_dijkstra_and_keeps_street_ids(self):
        inst = parse_instance(SYNTHETIC / "instance_C.txt")
        net = bds.Network(inst)
        rng = random.Random(2)
        for _ in range(100):
            s, t = rng.randrange(inst.num_junctions), rng.randrange(inst.num_junctions)
            d, streets = bds.bidirectional_dijkstra(net, s, t)
            self.assertEqual(d, net.tree(s)[0][t])
            node = s
            for sid in streets:
                st = inst.streets[sid]
                node = st.b if st.a == node else st.a
            self.assertEqual(node, t)
            self.assertEqual(sum(inst.streets[x].time for x in streets), d)


if __name__ == "__main__":
    unittest.main()
