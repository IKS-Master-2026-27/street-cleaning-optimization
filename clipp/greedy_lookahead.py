"""Greedy with look-ahead for street selection. See docs/greedy-lookahead.md.

Plain greedy commits the nearest feasible street. This variant is still greedy
(one street is committed per step, never undone), but before committing it
*looks ahead*: each of the best ``width`` candidate streets is extended by a
short greedy rollout of ``depth - 1`` further streets, and the candidate whose
rollout gives the best value per second wins. Only the first street of the
winning rollout is committed; the rollout itself is thrown away and recomputed
at the next step (rolling horizon).

Unlike ``recursive_enum`` there is no recursion, no rollback and no
enumeration of ``width**depth`` branches: the rollout is a single greedy line,
so one decision costs ``width * depth`` probes.
"""

from .parser import Instance
from .scoring import calculate_score
from .search import SearchSpace
from .solver import GreedyAssignmentError, Solution
from .validator import validate_solution


class _LevelSpace(SearchSpace):
    """SearchSpace restricted to mandatory streets of one requirement level.

    Like the baseline greedy, streets are served hardest class first (30, 20,
    10) so that large vehicles are not used up on streets a small one can clean.
    """

    level = 0
    optional_phase = False

    def set_level(self, level: int) -> None:
        self.optional_phase = False
        self.level = level
        self._exhausted.clear()
        self.level_pending = sum(
            1 for sid in self.mandatory_pending
            if self.streets_by_id[sid].requirement == level)

    def set_optional_phase(self) -> None:
        """Final phase: optional streets that raise the score, by gain/time."""
        self.optional_phase = True
        self.level = 10
        self._exhausted.clear()
        self.level_pending = sum(
            1 for street in self.instance.streets
            if street.category == "O" and street.id not in self.cleaned)

    def _accept(self, street, capacity, exclude) -> bool:
        if self.optional_phase:
            return (street.category == "O" and capacity >= street.requirement
                    and street.id not in self.cleaned
                    and street.id not in exclude
                    and self.model.gain(street, capacity) > 0.0)
        return (street.requirement == self.level
                and super()._accept(street, capacity, exclude))

    def _value(self, street, capacity):
        gain, value = super()._value(street, capacity)
        return (gain, gain) if self.optional_phase else (gain, value)

    def _clean(self, route, street, cleaned):
        if self.optional_phase:
            if street.category == "O":
                self.level_pending -= 1
        elif street.category == "M" and street.requirement == self.level:
            self.level_pending -= 1
        return super()._clean(route, street, cleaned)

    def probe(self, junction, capacity, elapsed, width=1, exclude=frozenset()):
        if self.level_pending <= 0 or capacity < self.level:
            return []
        return super().probe(junction, capacity, elapsed, width, exclude)


def _settings(instance: Instance) -> list:
    """(width, depth, return_weight) tried, cheapest first, by instance size.

    return_weight is the share of the trip home from the end of a look-ahead
    line that is charged to the line, so lines that strand a vehicle far from
    the depot rank lower.
    """
    streets = instance.num_streets
    if streets <= 1_500:
        return [(w, d, rw) for rw in (0.0, 0.5)
                for w, d in ((1, 1), (3, 2), (4, 3), (6, 4))]
    if streets <= 60_000:
        return [(1, 1, 0.0), (3, 2, 0.0)]
    return [(1, 1, 0.0)]


def _evaluate(space: SearchSpace, route, width: int, depth: int,
              return_weight: float = 0.0):
    """Best (key, move, rollout_street_ids) for ``route`` or None."""
    moves = space.find_moves(route, width=width)
    if not moves:
        return None
    best = None
    capacity = route.capacity
    for move in moves:
        value, spent = move.value, move.time
        position = move.exit
        elapsed = route.total_time + spent
        used = {move.street.id}
        for _ in range(depth - 1):
            nxt = space.probe(position, capacity, elapsed, 1, used)
            if not nxt:
                break
            step = nxt[0]
            value += step.value
            spent += step.time
            elapsed += step.time
            position = step.exit
            used.add(step.street.id)
        # Value per second of the whole look-ahead line; ties go to the
        # nearest first street, then lowest street id (deterministic).
        home = space.dist_depot.get(position, 0)
        total = spent + return_weight * home
        key = (-(value / total if total else 0.0), move.order_key())
        if best is None or key < best[0]:
            best = (key, move, used)
    return best


def _build(instance: Instance, width: int, depth: int,
           return_weight: float = 0.0) -> Solution:
    space = _LevelSpace(instance)
    routes = space.new_routes()
    levels = sorted({space.streets_by_id[sid].requirement
                     for sid in space.mandatory_pending}, reverse=True)

    phases = [(level, False) for level in levels] + [(10, True)]
    for level, optional in phases:
        if optional:
            space.set_optional_phase()
        else:
            space.set_level(level)
        eligible = [r for r in routes if r.capacity >= level]
        plan = {r.vehicle_id: _evaluate(space, r, width, depth, return_weight)
                for r in eligible}
        while space.level_pending > 0:
            winner = None
            for route in eligible:
                entry = plan[route.vehicle_id]
                if entry is not None and (winner is None
                                          or entry[0] < winner[0][0]):
                    winner = (entry, route)
            if winner is None:
                break
            (_, move, _), route = winner
            space.commit(route, move)
            # Re-plan only the vehicle that moved and vehicles whose
            # look-ahead line used the street that was just cleaned.
            for other in eligible:
                entry = plan[other.vehicle_id]
                if (other is route or entry is None
                        or move.street.id in entry[2]):
                    plan[other.vehicle_id] = _evaluate(space, other, width,
                                                       depth, return_weight)

    space.optional_phase = False
    if space.mandatory_pending:
        space.set_level(0)
        space.level_pending = 1  # repair probes target explicit street ids
        space._accept = lambda street, capacity, exclude: (
            SearchSpace._accept(space, street, capacity, exclude))
        failures = space.repair_mandatory(routes)
        if failures:
            raise GreedyAssignmentError(
                failures[0], Solution(routes),
                [f"{len(failures)} mandatory streets could not be assigned: "
                 f"{failures[:20]}"])
    for route in routes:
        space.close(route)
    space.sweep_traversed(routes)
    return Solution(routes)


def solve(instance: Instance, width: int | None = None,
          depth: int | None = None, return_weight: float | None = None,
          **_ignored) -> Solution:
    """Run the look-ahead ladder and keep the best valid solution."""
    if width is not None or depth is not None:
        settings = [(max(1, width or 1), max(1, depth or 1),
                     return_weight or 0.0)]
    else:
        settings = _settings(instance)
    best, failure = None, None
    for w, d, rw in settings:
        try:
            solution = _build(instance, w, d, rw)
        except ValueError as exc:
            failure = exc
            continue
        if validate_solution(instance, solution):
            continue
        score = calculate_score(instance, solution).score
        if best is None or score > best[0]:
            best = (score, solution)
    if best is None:
        if isinstance(failure, GreedyAssignmentError):
            raise failure
        raise ValueError("greedy look-ahead produced no valid solution"
                         + (f": {failure}" if failure else ""))
    return best[1]
