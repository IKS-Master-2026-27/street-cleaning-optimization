"""Check the 3D viewer's data pipeline on the smallest real city (Presheva)."""

from array import array
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visualization" / "pipeline"))

import convert  # noqa: E402
from formats import parse_instance, parse_solution  # noqa: E402
from projection import Projector  # noqa: E402
from timeline import CLEANS, REVERSE, build_timeline, score  # noqa: E402

CITY = ROOT / "data" / "input" / "real_instances" / "Presheva"


def read_view(path: Path, spec: dict) -> array:
    kind = {"uint8": "B", "uint32": "I", "int32": "i", "float32": "f"}[spec["type"]]
    values = array(kind)
    with open(path, "rb") as source:
        source.seek(spec["offset"])
        values.frombytes(source.read(spec["length"] * values.itemsize))
    return values


class ProjectionTests(unittest.TestCase):
    def test_known_utm_points(self):
        east, north = Projector(31, False).utm(3, 45)
        self.assertAlmostEqual(east, 500000.0, places=3)
        self.assertAlmostEqual(north, 4982950.400, places=2)
        east, north = Projector(56, True).utm(151.2093, -33.8688)  # Sydney, southern hemisphere
        self.assertAlmostEqual(east, 334368.6, delta=1)
        self.assertAlmostEqual(north, 6250948.3, delta=1)


class BuildingsTests(unittest.TestCase):
    def test_tile_and_boundary(self):
        import buildings
        # Presheva's centre lies in zoom-9 tile 120233312 of Microsoft's dataset
        self.assertEqual(buildings.quadkey(*buildings.tile(21.6586, 42.3060)), "120233312")
        square = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
                                                      [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1], [0.5, 0.5]]]}
        self.assertTrue(buildings.inside(1.5, 1.5, square))
        self.assertFalse(buildings.inside(0.75, 0.75, square))  # in the hole
        self.assertFalse(buildings.inside(3, 1, square))

    def test_estimated_heights_grow_with_footprint(self):
        import buildings
        small = buildings.estimated_height(40, 10, 20)
        large = buildings.estimated_height(2000, 10, 20)
        self.assertLess(small, large)
        self.assertEqual(small, buildings.estimated_height(40, 10, 20))  # stable


class SumoTests(unittest.TestCase):
    """The parts of the realistic mode that do not need SUMO installed."""

    def test_speeds_lanes_and_edge_names(self):
        import sumo_run
        self.assertAlmostEqual(sumo_run.speed_limit("primary", "50"), 50 / 3.6)
        self.assertAlmostEqual(sumo_run.speed_limit("primary", "30 mph"), 30 * 1.609 / 3.6)
        # never slower than the trucks' 20 km/h, so the plan is not slowed by the map
        self.assertGreater(sumo_run.speed_limit("living_street", "10"), 20 / 3.6)
        self.assertEqual(sumo_run.lane_count("4", two_way=True), 2)
        self.assertEqual(sumo_run.lane_count("2;3", two_way=False), 2)
        self.assertEqual(sumo_run.lane_count(None, two_way=True), 1)
        self.assertEqual(sumo_run.edge_id(7, True), "s7_r")
        self.assertEqual(sumo_run.parse_edge("s7_r"), (7, REVERSE))
        self.assertIsNone(sumo_run.parse_edge(":j3_0"))  # SUMO's internal junction edge

    def test_missing_turns_keep_all_existing_turns(self):
        import sumo_run
        needed = sumo_run.route_turns([[(1, False), (1, True)], [(1, False), (2, False)]])
        self.assertEqual(needed, {("s1_f", "s1_r"), ("s1_f", "s2_f")})
        # netconvert built s1_f -> s2_f and s1_f -> s3_f but not the U-turn s1_f -> s1_r
        built = {"s1_f": {("s2_f", 0, 0), ("s3_f", 0, 0)}}
        lanes = {"s1_f": 1, "s1_r": 1, "s2_f": 1, "s3_f": 1}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "net.con.xml"
            added = sumo_run.write_missing_turns(needed, built, lanes, path)
            text = path.read_text()
        self.assertEqual(added, 1)
        # the U-turn is added, and the edge's other turns are listed again so none is lost
        for to in ("s1_r", "s2_f", "s3_f"):
            self.assertIn(f'from="s1_f" to="{to}" fromLane="0" toLane="0"', text)


class TimelineTests(unittest.TestCase):
    INSTANCE = "3 3 100 2 0 0.5\n0 1 2 10 100 M 10\n1 2 1 20 200 O 20\n2 0 1 5 50 C 0\nS L\n"

    def test_steps_direction_cleaning_and_score(self):
        inst = parse_instance(self.INSTANCE)
        routes = parse_solution("2\n2\n0 1 0\n0\n3\n0 1 2 0\n1\n")
        timeline, errors = build_timeline(inst, routes)
        self.assertEqual(errors, [])
        self.assertEqual(timeline.offsets, [0, 2, 5])
        self.assertEqual(timeline.street, [0, 0, 0, 1, 2])
        self.assertEqual(timeline.enter, [0, 10, 0, 10, 30])
        self.assertEqual(timeline.flags, [CLEANS, REVERSE, 0, CLEANS, 0])
        self.assertEqual(timeline.end, [20, 35])
        result = score(inst, routes)
        self.assertAlmostEqual(result["coverage"], 1.0)
        # waste: S on street 0 (10-10)*0.1 + L on street 1 (30-20)*0.2 = 2, max (20*0.1 + 10*0.2) = 4
        self.assertAlmostEqual(result["efficiency"], 0.5)

    def test_reports_capacity_and_missing_mandatory(self):
        inst = parse_instance(self.INSTANCE)
        # the S truck cleans street 1 (needs 20); mandatory street 0 is never cleaned
        _, errors = build_timeline(inst, parse_solution("2\n3\n0 1 2 0\n1\n0\n0\n\n"))
        self.assertTrue(any("needing more" in e for e in errors))
        self.assertTrue(any("mandatory streets are not cleaned" in e for e in errors))

    def test_reports_impossible_moves(self):
        inst = parse_instance(self.INSTANCE)
        _, errors = build_timeline(inst, parse_solution("2\n1\n0 2\n\n0\n0\n\n"))
        self.assertTrue(any("no street" in e for e in errors))


@unittest.skipUnless((CITY / "roads.geojson").exists(), "Presheva data not available")
class ConvertTests(unittest.TestCase):
    def test_baseline_timeline_matches_the_generator(self):
        # the dataset's own solution checks the timeline rules against known values
        inst = parse_instance((CITY / "instance.txt").read_text("utf-8"))
        routes = parse_solution((CITY / "instance.solution.txt").read_text("utf-8"))
        timeline, errors = build_timeline(inst, routes)
        self.assertEqual(errors, [])
        mapping = json.loads((CITY / "instance.json").read_text("utf-8"))
        self.assertEqual([int(e) for e in timeline.end], mapping["route_seconds"])
        validation = json.loads((CITY / "validation.json").read_text("utf-8"))
        self.assertAlmostEqual(score(inst, routes)["value"], validation["official"]["score"], places=9)

    def test_convert_presheva(self):
        # export the dataset's solution as if an algorithm called "greedy" had made it
        solution_file = CITY / "instance.solution.txt"
        original = convert.find_solutions
        convert.find_solutions = lambda name: [("greedy", "Greedy", solution_file)]
        try:
            with TemporaryDirectory() as folder:
                out = Path(folder)
                (out / "Presheva" / "solutions").mkdir(parents=True)
                (out / "Presheva" / "solutions" / "old.json").write_text("{}")  # stale export
                city = convert.convert(CITY, out)
                convert.write_index(out, CITY.parent)

                self.assertEqual(city["nodes"], 744)
                self.assertEqual(city["streets"]["count"], 838)
                self.assertEqual(city["projection"]["utm"], "34N")
                self.assertEqual(city["solutions"], [{"id": "greedy", "label": "Greedy"}])
                self.assertFalse((out / "Presheva" / "solutions" / "old.json").exists())
                solution = json.loads((out / "Presheva" / "solutions" / "greedy.json").read_text("utf-8"))

                streets = out / "Presheva" / "streets.bin"
                offsets = read_view(streets, city["streets"]["buffers"]["offsets"])
                points = read_view(streets, city["streets"]["buffers"]["points"])
                self.assertEqual(len(offsets), 839)
                self.assertEqual(offsets[-1] * 2, len(points))
                # the depot is a street end, so it must be one of the projected points
                depot = (city["depot"]["x"], city["depot"]["y"])
                self.assertTrue(any(abs(points[i] - depot[0]) < 0.01 and abs(points[i + 1] - depot[1]) < 0.01
                                    for i in range(0, len(points), 2)))

                steps = out / "Presheva" / "solutions" / "greedy.steps.bin"
                vehicle_offsets = read_view(steps, solution["buffers"]["offsets"])
                self.assertEqual(vehicle_offsets[-1], solution["steps"])

                index = json.loads((out / "index.json").read_text("utf-8"))
                available = [c["directory"] for c in index["cities"] if c["available"]]
                self.assertEqual(available, ["Presheva"])
        finally:
            convert.find_solutions = original


if __name__ == "__main__":
    unittest.main()
