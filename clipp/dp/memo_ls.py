"""Extension of Solution B: memoized DP (memo.py) + local search (improve.py).

NOT part of task 13 itself; it is kept separate so that the effect of
memoization (`dp-memo`) and the effect of local search (`dp-memo-ls`) can be
compared. Every distinct plan found by the memoized DP is post-optimised:

  * Or-opt / 2-opt / orientation flips remove deadheading inside each route;
  * cheapest insertion spends the freed time on further optional streets;
  * relocation moves tasks between vehicles when it saves total time.

The improved result of each plan is stored in a memo like everything else.
"""

from ..solver import Solution
from .assignment import route_from_tasks
from .improve import Sequencer
from .io import problem_from_instance
from .memo import Memo, MemoSolver, Result, solve_memo
from .objective import to_repo_solution
from .simple import finish
from .split import Segment, SplitData, vehicles_for


class MemoLocalSearchSolver(MemoSolver):
    def __init__(self, problem) -> None:
        super().__init__(problem)
        self.improvements = Memo("improved plans")
        self.sequencer = Sequencer(self.problem, self.oracle)
        self.improve_top: int | None = None   # None = improve every distinct DP plan
        self.relocate_rounds = 5

    def memos(self) -> list[Memo]:
        return super().memos() + [self.improvements]

    def after_dp(self, pool: dict[tuple, tuple], best: tuple) -> tuple:
        # Start from dp-memo's own result (route-level DPs), so the extension
        # can never return a worse plan than dp-memo itself.
        best = super().after_dp(pool, best)
        log = self.stats.log
        top = sorted(pool.values(), key=lambda x: -x[0])[:self.improve_top]
        for score, data, segments, label in top:
            if best[1].score >= 1.0 - 1e-12:
                break  # already the maximum possible score
            routes, evaluation = self.improved(data, segments)
            if evaluation.valid and evaluation.score > best[1].score + 1e-12:
                best = (routes, evaluation)
                log.append(f"new best {evaluation.score:.6f}: improved {label} (DP {score:.6f})")
        return best

    def improved(self, data: SplitData, segments: list[Segment]):
        """Local search + cheapest insertion + relocation on one DP plan (memoized)."""
        problem, oracle, seqr = self.problem, self.oracle, self.sequencer

        def compute():
            seqs: list[list[int]] = [[] for _ in range(problem.num_vehicles)]
            for vehicle, seg in vehicles_for(problem, segments):
                seqs[vehicle] = list(data.tour.tasks[seg.first:seg.last + 1])
            seqs = [seqr.improve(s) for s in seqs]
            order = sorted(range(problem.num_vehicles), key=lambda v: (problem.capacities[v], v))

            def fill() -> None:
                for _ in range(2):
                    routes = [route_from_tasks(problem, oracle, v, s) for v, s in enumerate(seqs)]
                    traversed = {j for r in routes for j in r.streets}
                    candidates = {j for j in range(problem.num_streets)
                                  if problem.category[j] != "C" and j not in traversed}
                    for v in order:
                        seqs[v] = seqr.improve(seqr.insert(seqs[v], problem.capacities[v], candidates))

            def evaluate_now():
                routes = [route_from_tasks(problem, oracle, v, s) for v, s in enumerate(seqs)]
                return routes, finish(problem, oracle, routes, self.dense, [])

            fill()
            best = evaluate_now()
            # Moves between vehicles: relocate tasks where they cost least, then
            # spend the freed time on new streets; keep the best evaluated state.
            for _ in range(self.relocate_rounds):
                if not seqr.relocate(seqs, problem.capacities):
                    break
                seqs[:] = [seqr.improve(s) for s in seqs]
                fill()
                current = evaluate_now()
                if current[1].valid and current[1].score > best[1].score + 1e-12:
                    best = current
            return best
        return self.improvements.get(self.signature(data, segments), compute)


last_result: Result | None = None


def solve(instance, **_ignored) -> Solution:
    """`main.py --algorithm dp-memo-ls`: memoized DP + local search."""
    global last_result
    problem = problem_from_instance(instance)
    last_result = solve_memo(problem, MemoLocalSearchSolver)
    return to_repo_solution(problem, last_result.routes)
