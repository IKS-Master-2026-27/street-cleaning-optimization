from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from instancelab.clipp import InstanceParseError, parse_instance, read_instance


REPOSITORY_LAYOUT = """3 3 100 2 0 0.5
0 1 2 10 100 M 10
1 2 1 20 200 O 20
2 0 1 5 0 C 0
S L
"""


class ClippReaderTests(unittest.TestCase):
    def test_parses_repository_layout(self):
        instance = parse_instance(REPOSITORY_LAYOUT, source="tiny.txt")

        self.assertEqual(instance.num_junctions, 3)
        self.assertEqual(instance.num_streets, 3)
        self.assertEqual(instance.vehicle_types, ("S", "L"))
        self.assertIsNone(instance.coordinates)
        self.assertEqual(instance.streets[1].category, "O")
        self.assertEqual(instance.streets[1].travel_time, 20)
        self.assertEqual(instance.source, "tiny.txt")

    def test_parses_official_coordinate_layout(self):
        lines = REPOSITORY_LAYOUT.splitlines()
        coordinates = ["42.0 21.0", "42.1 21.1", "42.2 21.2"]
        instance = parse_instance("\n".join([lines[0], *coordinates, *lines[1:]]))

        self.assertEqual(instance.coordinates, (
            (42.0, 21.0),
            (42.1, 21.1),
            (42.2, 21.2),
        ))
        self.assertEqual(len(instance.streets), 3)

    def test_reads_utf8_file(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "instance.txt"
            path.write_text(REPOSITORY_LAYOUT, encoding="utf-8")
            instance = read_instance(path)

        self.assertEqual(instance.source, str(path))
        self.assertEqual(instance.depot, 0)

    def test_rejects_wrong_header_width(self):
        with self.assertRaisesRegex(InstanceParseError, "expected header"):
            parse_instance("3 2 100\n")

    def test_rejects_missing_street_record(self):
        text = "3 2 100 1 0 0.5\n0 1 2 10 100 M 10\nS\n"
        with self.assertRaisesRegex(InstanceParseError, "expected 7 street fields"):
            parse_instance(text)

    def test_rejects_wrong_fleet_size(self):
        text = REPOSITORY_LAYOUT.replace("S L\n", "S\n")
        with self.assertRaisesRegex(InstanceParseError, "expected 2 vehicle types"):
            parse_instance(text)


if __name__ == "__main__":
    unittest.main()
