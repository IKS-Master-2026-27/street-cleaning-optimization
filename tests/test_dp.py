"""Tests for the dynamic-programming solvers (clipp/dp).

Each DP is compared with exhaustive enumeration on small random instances, and
the end-to-end solvers are checked with both validators.
"""

import itertools
import math
import random
import tempfile
import unittest
from pathlib import Path

from clipp.dp.advanced import solve_advanced
from clipp.dp.assignment import assign_cleaning
from clipp.dp.bounds import upper_bound
from clipp.dp.distances import INF, Oracle
from clipp.dp.io import problem_from_instance, read_problem
from clipp.dp.knapsack import knapsack
from clipp.dp.local_search import Dense, held_karp_window, select_within
from clipp.dp.objective import (Route, additive_score, evaluate, read_solution, save_if_better,
                                 to_repo_solution)
from clipp.dp.simple import solve_simple
from clipp.dp.split import NEG, SplitData, split_heterogeneous, split_ordered
from clipp.dp.tour import make_tour, orientations, select_streets, servable
from clipp.parser import parse_instance
from clipp.scoring import calculate_score
from clipp.search import ScoreModel
from clipp.solver import depot_return_times
from clipp.validator import validate_solution

PODUJEVA = """6 10 300 3 0 0.5
0 1 2 30 200 M 10
1 3 2 25 150 O 10
1 2 2 35 300 M 20
0 3 1 20 0 C 0
3 5 2 15 100 O 10
2 4 2 30 250 M 30
3 4 2 40 350 O 20
4 5 2 20 0 C 0
5 2 2 45 400 O 30
5 0 2 25 0 C 0
S M L
"""


def write(text: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


def random_instance(rng: random.Random, n: int = 7, extra: int = 6, vehicles: int = 3,
                    time_limit: int = 400, alpha: float = 0.5, with_large: bool = False) -> str:
    """Strongly connected random instance (a two-way ring plus random chords)."""
    edges = set()
    lines = []
    for i in range(n):
        edges.add(frozenset((i, (i + 1) % n)))
        lines.append((i, (i + 1) % n, 2))
    while len(lines) < n + extra:
        u, v = rng.sample(range(n), 2)
        if frozenset((u, v)) in edges:
            continue
        edges.add(frozenset((u, v)))
        lines.append((u, v, rng.choice((1, 2))))
    rows = []
    for u, v, d in lines:
        cat = rng.choice("MOOC")
        req = rng.choice((10, 20, 30)) if cat != "C" else 0
        length = rng.randint(50, 500) if cat != "C" else 0
        rows.append(f"{u} {v} {d} {rng.randint(5, 60)} {length} {cat} {req}")
    fleet = [rng.choice("SML") for _ in range(vehicles)]
    if with_large:
        fleet[0] = "L"
    fleet = " ".join(fleet)
    return f"{n} {len(rows)} {time_limit} {vehicles} 0 {alpha}\n" + "\n".join(rows) + f"\n{fleet}\n"


class ObjectiveTests(unittest.TestCase):
    def test_official_example_scores_0_9(self):
        problem = read_problem(write(PODUJEVA))
        routes = [Route(0, 10, [0, 1, 3, 5, 0], [0, 1, 4, 9], [0, 1, 4]),
                  Route(1, 20, [0, 1, 2, 4, 5, 0], [0, 2, 5, 7, 9], [2]),
                  Route(2, 30, [0, 1, 2, 4, 5, 2, 4, 5, 0], [0, 2, 5, 7, 8, 5, 7, 9], [5, 8])]
        evaluation = evaluate(problem, routes)
        self.assertTrue(evaluation.valid, evaluation.errors)
        self.assertAlmostEqual(evaluation.score, 0.9, places=12)
        self.assertAlmostEqual(additive_score(problem, routes), 0.9, places=12)
        self.assertEqual(problem.l_max, 1750)
        self.assertAlmostEqual(problem.w_max, 15.5)

    def test_reader_accepts_coordinate_lines(self):
        lines = PODUJEVA.split("\n")
        coords = [f"{42 + i / 100:.4f} {21 + i / 100:.4f}" for i in range(6)]
        problem = read_problem(write("\n".join([lines[0]] + coords + lines[1:])))
        self.assertEqual(len(problem.coords), 6)
        self.assertEqual(problem.num_streets, 10)
        self.assertEqual(problem.fleet, ["S", "M", "L"])


class KnapsackTests(unittest.TestCase):
    def test_matches_enumeration(self):
        rng = random.Random(3)
        for _ in range(200):
            n = rng.randint(1, 10)
            w = [rng.randint(1, 20) for _ in range(n)]
            p = [rng.random() for _ in range(n)]
            cap = rng.randint(0, 60)
            best = max(sum(p[i] for i in s) for k in range(n + 1)
                       for s in itertools.combinations(range(n), k)
                       if sum(w[i] for i in s) <= cap)
            chosen = knapsack(w, p, cap)
            self.assertLessEqual(sum(w[i] for i in chosen), cap)
            self.assertAlmostEqual(sum(p[i] for i in chosen), best, places=12)


def brute_ordered(data: SplitData, caps: list[int]) -> float:
    """Exhaustive recursion over skip / unused vehicle / segment choices."""
    n, T = data.n, data.problem.time_limit

    def rec(i: int, k: int) -> float:
        if i == n:
            return 0.0
        best = NEG
        if not data.mandatory[i]:
            best = max(best, rec(i + 1, k))
        if k < len(caps):
            best = max(best, rec(i, k + 1))
            q = caps[k]
            for e in range(i, n):
                if data.time(i, e) > T:
                    break
                vals = [data.task_value(h, q) for h in range(i, e + 1)]
                if any(v is None for v in vals):
                    break
                tail = rec(e + 1, k + 1)
                if tail > NEG:
                    best = max(best, sum(vals) + tail)
        return best
    return rec(0, 0)


def brute_heterogeneous(data: SplitData, counts: dict[int, int]) -> float:
    n, T = data.n, data.problem.time_limit

    def rec(i: int, left: tuple) -> float:
        if i == n:
            return 0.0
        best = NEG
        if not data.mandatory[i]:
            best = max(best, rec(i + 1, left))
        for x, (q, c) in enumerate(left):
            if c == 0:
                continue
            rest = left[:x] + ((q, c - 1),) + left[x + 1:]
            for e in range(i, n):
                if data.time(i, e) > T:
                    break
                vals = [data.task_value(h, q) for h in range(i, e + 1)]
                if any(v is None for v in vals):
                    break
                tail = rec(e + 1, rest)
                if tail > NEG:
                    best = max(best, sum(vals) + tail)
        return best
    return rec(0, tuple(sorted(counts.items())))


class SplitTests(unittest.TestCase):
    def test_split_dps_match_enumeration(self):
        rng = random.Random(11)
        checked = 0
        for _ in range(60):
            problem = read_problem(write(random_instance(rng, time_limit=rng.choice((150, 250, 400)))))
            oracle = Oracle(problem)
            tasks = []
            for j in range(problem.num_streets):
                if problem.category[j] != "C":
                    oids = [o for o in orientations(problem, j) if servable(problem, oracle, o)]
                    if oids:
                        tasks.append(rng.choice(oids))
            rng.shuffle(tasks)
            tasks = tasks[:8]
            if not tasks:
                continue
            data = SplitData(problem, oracle, make_tour(problem, oracle, tasks))
            caps = sorted(problem.capacities, reverse=True)
            value, segments = split_ordered(data, caps)
            self.assertAlmostEqual(value, brute_ordered(data, caps), places=12)
            counts: dict[int, int] = {}
            for q in problem.capacities:
                counts[q] = counts.get(q, 0) + 1
            hvalue, hsegments = split_heterogeneous(data, counts)
            self.assertAlmostEqual(hvalue, brute_heterogeneous(data, counts), places=12)
            self.assertGreaterEqual(hvalue, value - 1e-12)  # free type choice never hurts
            for seg in segments + hsegments:  # reconstructed segments are feasible
                self.assertLessEqual(data.time(seg.first, seg.last), problem.time_limit)
            checked += 1
        self.assertGreater(checked, 40)


class RouteDPTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(5)

    def _setup(self, time_limit=2000):
        problem = read_problem(write(random_instance(self.rng, n=8, extra=8, time_limit=time_limit)))
        oracle = Oracle(problem)
        return problem, oracle, Dense(problem, oracle)

    def test_held_karp_window_is_optimal(self):
        for _ in range(25):
            problem, oracle, dense = self._setup()
            streets = [j for j in range(problem.num_streets) if problem.category[j] != "C"]
            self.rng.shuffle(streets)
            seq = [self.rng.choice(orientations(problem, j)) for j in streets[:6]]
            if len(seq) < 3:
                continue
            best = math.inf
            for perm in itertools.permutations(seq):
                for combo in itertools.product(*[orientations(problem, o >> 1) for o in perm]):
                    best = min(best, dense.time(list(combo)))
            work = list(seq)
            held_karp_window(dense, work, 0, len(work))
            self.assertEqual(dense.time(work), min(best, dense.time(seq)))
            self.assertEqual(sorted(o >> 1 for o in work), sorted(o >> 1 for o in seq))

    def test_select_within_is_optimal(self):
        for _ in range(40):
            problem, oracle, dense = self._setup(time_limit=self.rng.choice((150, 250, 400)))
            streets = [j for j in range(problem.num_streets) if problem.category[j] != "C"]
            self.rng.shuffle(streets)
            seq = [self.rng.choice(orientations(problem, j)) for j in streets[:8]]
            q = self.rng.choice((10, 20, 30))
            got = select_within(dense, seq, q, max_labels=10 ** 6)
            best = None
            for k in range(len(seq) + 1):
                for idx in itertools.combinations(range(len(seq)), k):
                    sub = [seq[i] for i in idx]
                    kept = set(idx)
                    if any(problem.category[seq[i] >> 1] == "M" and i not in kept for i in range(len(seq))):
                        continue
                    if any(problem.delta(o >> 1, q) is None for o in sub):
                        continue
                    if dense.time(sub) > problem.time_limit:
                        continue
                    value = sum(problem.delta(o >> 1, q) for o in sub)
                    best = value if best is None else max(best, value)
            if best is None:
                self.assertIsNone(got)
            else:
                self.assertIsNotNone(got)
                self.assertLessEqual(dense.time(got), problem.time_limit)
                value = sum(problem.delta(o >> 1, q) for o in got)
                self.assertAlmostEqual(value, max(best, 0.0) if not any(
                    problem.category[o >> 1] == "M" for o in seq) else best, places=12)


class EndToEndTests(unittest.TestCase):
    def check(self, path: str, routes) -> float:
        problem = read_problem(path)
        evaluation = evaluate(problem, routes)
        self.assertTrue(evaluation.valid, evaluation.errors)
        solution = to_repo_solution(problem, routes)
        instance = parse_instance(path)
        self.assertEqual(validate_solution(instance, solution), [])
        repo = calculate_score(instance, solution).score
        self.assertAlmostEqual(repo, evaluation.score, places=10)
        self.assertAlmostEqual(additive_score(problem, routes), evaluation.score, places=10)
        oracle = Oracle(problem)
        self.assertLessEqual(evaluation.score, upper_bound(problem, oracle) + 1e-9)
        for route in routes:  # official format: every route has at least one move
            self.assertGreaterEqual(len(route.streets), 1)
        return evaluation.score

    def test_podujeva_reaches_perfect_score(self):
        path = write(PODUJEVA)
        result = solve_simple(read_problem(path))
        self.assertAlmostEqual(self.check(path, result.routes), 1.0, places=12)

    def test_random_instances_valid_and_b_not_worse(self):
        rng = random.Random(21)
        searched = 0
        for _ in range(12):
            path = write(random_instance(rng, n=12, extra=16, vehicles=3, alpha=1.0,
                                         time_limit=rng.choice((150, 200, 260)), with_large=True))
            problem = read_problem(path)
            try:
                a = solve_simple(problem)
            except ValueError:
                continue  # mandatory streets genuinely out of reach within T
            score_a = self.check(path, a.routes)
            b = solve_advanced(read_problem(path), seed=1, time_limit=1.0)
            score_b = self.check(path, b.routes)
            self.assertGreaterEqual(score_b, score_a - 1e-12)
            searched += "search skipped" not in b.log[-1]
        self.assertGreater(searched, 0, "the advanced search was never exercised")

    def test_save_if_better_never_overwrites_a_better_solution(self):
        path = write(PODUJEVA)
        problem = read_problem(path)
        best = solve_simple(problem).routes          # score 1.0
        worse = [Route(0, 10, [0, 1, 3, 5, 0], [0, 1, 4, 9], [0, 1, 4]),
                 Route(1, 20, [0, 1, 2, 4, 5, 0], [0, 2, 5, 7, 9], [2]),
                 Route(2, 30, [0, 1, 2, 4, 5, 2, 4, 5, 0], [0, 2, 5, 7, 8, 5, 7, 9], [5, 8])]  # 0.9
        target = Path(tempfile.mkdtemp()) / "podujeva_solution.txt"
        self.assertEqual(save_if_better(problem, worse, target), (True, None))     # nothing stored yet
        self.assertEqual(save_if_better(problem, worse, target)[0], False)         # equal: kept
        self.assertTrue(save_if_better(problem, best, target)[0])                  # better: replaced
        self.assertFalse(save_if_better(problem, worse, target)[0])                # worse: kept
        self.assertAlmostEqual(evaluate(problem, read_solution(problem, target)).score, 1.0, places=12)

    def test_assignment_is_optimal_for_fixed_moves(self):
        """Lemma 1: no other cleaning choice for the same moves scores higher."""
        rng = random.Random(8)
        for _ in range(10):
            path = write(random_instance(rng, n=6, extra=4, vehicles=2, time_limit=600))
            problem = read_problem(path)
            try:
                routes = solve_simple(problem).routes
            except ValueError:
                continue
            assign_cleaning(problem, routes)
            best = evaluate(problem, routes).score
            traversed = sorted({(v, j) for v, r in enumerate(routes) for j in set(r.streets)
                                if problem.delta(j, r.capacity) is not None})
            if len(traversed) > 12:
                continue
            for mask in range(1 << len(traversed)):
                trial = [Route(r.vehicle, r.capacity, r.nodes, r.streets, []) for r in routes]
                for bit, (v, j) in enumerate(traversed):
                    if mask >> bit & 1:
                        trial[v].cleaned.append(j)
                ev = evaluate(problem, trial)
                if ev.valid:
                    self.assertLessEqual(ev.score, best + 1e-12)


class SharedCodeTests(unittest.TestCase):
    """The DP keeps its own fast versions of a few shared pieces; these tests
    check that they agree exactly with the repository's implementations."""

    ROOT = Path(__file__).resolve().parents[1]

    def instances(self):
        paths = [write(PODUJEVA)] + sorted(
            str(p) for p in (self.ROOT / "data/input/syntetic_generated").glob("instance_*.txt"))
        presheva = self.ROOT / "data/input/real_instances/Presheva/instance.txt"
        return paths + ([str(presheva)] if presheva.exists() else [])

    def test_delta_matches_search_score_model(self):
        for path in self.instances():
            instance = parse_instance(path)
            problem = read_problem(path)
            model = ScoreModel.from_instance(instance)
            self.assertEqual(model.l_max, problem.l_max)
            self.assertAlmostEqual(model.w_max, problem.w_max, places=9)
            for street in instance.streets:
                for q in (10, 20, 30):
                    delta = problem.delta(street.id, q)
                    if delta is not None:
                        self.assertAlmostEqual(delta, model.gain(street, q), places=15)

    def test_depot_distances_match_solver(self):
        for path in self.instances():
            instance = parse_instance(path)
            to_depot = Oracle(read_problem(path)).to_depot[0]
            expected = depot_return_times(instance)
            for node in range(instance.num_junctions):
                self.assertEqual(to_depot[node], expected.get(node, INF))

    def test_coordinate_layout_matches_repository_parser(self):
        """The official layout (N coordinate lines after the header) is read by our
        own parser; it must give exactly the model built from parse_instance."""
        for path in self.instances():
            lines = Path(path).read_text(encoding="utf-8").split("\n")
            n = int(lines[0].split()[0])
            coords = [f"{21 + i / 1000:.4f} {42 + i / 1000:.4f}" for i in range(n)]
            official = read_problem(write("\n".join([lines[0]] + coords + lines[1:])))
            self.assertEqual(len(official.coords), n)
            direct = problem_from_instance(parse_instance(path), official.name)
            via_parser = official
            for field in ("num_junctions", "num_streets", "time_limit", "num_vehicles", "depot",
                          "alpha", "a", "b", "direction", "time", "length", "category",
                          "requirement", "fleet", "l_max", "w_max"):
                self.assertEqual(getattr(direct, field), getattr(via_parser, field), field)


if __name__ == "__main__":
    unittest.main()
