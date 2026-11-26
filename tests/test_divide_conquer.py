"""Tests for the divide-and-conquer zoning solver (clipp/divide_conquer.py)."""

from pathlib import Path
import unittest

from clipp import divide_conquer as dc
from clipp.parser import parse_instance
from clipp.solver import VEHICLE_CAPACITIES
from clipp.validator import validate_solution

ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "data/input/syntetic_generated"
NAMES = ("A", "B", "C", "D")


def load(name):
    return parse_instance(INSTANCES / f"instance_{name}.txt")


class PartitionTests(unittest.TestCase):
    def test_every_street_in_exactly_one_zone(self):
        for name in NAMES:
            instance = load(name)
            for depth in range(dc.full_depth(instance) + 1):
                zones = dc.partition(instance, depth)
                ids = [sid for zone in zones for sid in zone.street_ids]
                self.assertEqual(sorted(ids), list(range(instance.num_streets)),
                                 f"{name} depth {depth}")

    def test_every_vehicle_in_exactly_one_zone(self):
        for name in NAMES:
            instance = load(name)
            zones = dc.partition(instance)
            ids = sorted(vid for zone in zones for vid in zone.vehicle_ids)
            self.assertEqual(ids, list(range(instance.num_vehicles)), name)

    def test_full_depth_gives_one_vehicle_per_zone(self):
        for name in NAMES:
            instance = load(name)
            zones = dc.partition(instance)
            self.assertEqual(len(zones), instance.num_vehicles, name)
            self.assertTrue(all(len(z.vehicle_ids) == 1 for z in zones))
            self.assertLessEqual(max(z.depth for z in zones),
                                 dc.full_depth(instance))

    def test_depth_zero_is_whole_city(self):
        instance = load("B")
        zones = dc.partition(instance, 0)
        self.assertEqual(len(zones), 1)
        self.assertEqual(len(zones[0].vehicle_ids), instance.num_vehicles)

    def test_zone_vehicles_can_clean_their_mandatory_streets(self):
        for name in NAMES:
            instance = load(name)
            streets = {s.id: s for s in instance.streets}
            for zone in dc.partition(instance):
                capacity = max(VEHICLE_CAPACITIES[instance.vehicle_types[v]]
                               for v in zone.vehicle_ids)
                for sid in zone.street_ids:
                    if streets[sid].category == "M":
                        self.assertLessEqual(streets[sid].requirement, capacity)

    def test_water_fill_levels_loads(self):
        received = dc._water_fill({0: 0.0, 1: 4.0, 2: 10.0}, 8.0)
        self.assertAlmostEqual(sum(received.values()), 8.0)
        self.assertAlmostEqual(received[0], 6.0)
        self.assertAlmostEqual(received[1], 2.0)
        self.assertAlmostEqual(received[2], 0.0)


class SolveTests(unittest.TestCase):
    def test_valid_on_synthetic_instances(self):
        for name in NAMES:
            instance = load(name)
            solution = dc.solve(instance)
            self.assertEqual(validate_solution(instance, solution), [], name)

    def test_deterministic(self):
        instance = load("B")
        first = dc.solve(instance)
        second = dc.solve(instance)
        self.assertEqual([r.junctions for r in first.routes],
                         [r.junctions for r in second.routes])


if __name__ == "__main__":
    unittest.main()
