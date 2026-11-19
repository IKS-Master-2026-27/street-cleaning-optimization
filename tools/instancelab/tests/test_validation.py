from dataclasses import replace
import unittest

from instancelab.clipp import parse_instance
from instancelab.model import Street
from instancelab.validation import validate_instance

from tests.test_clipp_reader import REPOSITORY_LAYOUT


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.instance = parse_instance(REPOSITORY_LAYOUT)

    def codes(self, instance=None):
        return {issue.code for issue in validate_instance(instance or self.instance)}

    def test_accepts_valid_instance(self):
        self.assertEqual(validate_instance(self.instance), ())

    def test_reports_header_and_fleet_errors(self):
        invalid = replace(
            self.instance,
            num_streets=4,
            num_vehicles=3,
            depot=9,
            alpha=1.5,
            vehicle_types=("S", "X"),
        )
        self.assertTrue({
            "street_count_mismatch",
            "vehicle_count_mismatch",
            "depot_range",
            "alpha_range",
            "vehicle_type",
        }.issubset(self.codes(invalid)))

    def test_reports_invalid_street_semantics(self):
        bad_street = Street(0, -1, 8, 3, 0, -1, "X", 17)
        invalid = replace(self.instance, streets=(bad_street, *self.instance.streets[1:]))
        self.assertTrue({
            "street_start_range",
            "street_end_range",
            "street_direction",
            "street_time",
            "street_length",
            "street_category",
        }.issubset(self.codes(invalid)))

    def test_reports_connector_and_capacity_errors(self):
        connector = replace(self.instance.streets[2], length=10, requirement=10)
        mandatory = replace(self.instance.streets[0], requirement=30)
        invalid = replace(
            self.instance,
            streets=(mandatory, self.instance.streets[1], connector),
            vehicle_types=("S", "M"),
        )
        self.assertTrue({"connector_values", "mandatory_capacity"}.issubset(self.codes(invalid)))

    def test_reports_mandatory_street_without_round_trip(self):
        text = "3 2 100 1 0 1.0\n0 1 1 10 100 M 10\n1 2 1 10 0 C 0\nS\n"
        invalid = parse_instance(text)
        self.assertIn("mandatory_unreachable", self.codes(invalid))

    def test_reports_mandatory_street_that_does_not_fit_in_time_limit(self):
        # Round trip 0 -> 1 -> 0 takes 30 + 30 = 60 seconds, above T = 50.
        text = "2 1 50 1 0 1.0\n0 1 2 30 100 M 10\nS\n"
        codes = self.codes(parse_instance(text))
        self.assertIn("mandatory_time_infeasible", codes)
        self.assertNotIn("mandatory_unreachable", codes)

    def test_accepts_mandatory_street_exactly_at_time_limit(self):
        text = "2 1 60 1 0 1.0\n0 1 2 30 100 M 10\nS\n"
        self.assertEqual(self.codes(parse_instance(text)), set())


if __name__ == "__main__":
    unittest.main()
