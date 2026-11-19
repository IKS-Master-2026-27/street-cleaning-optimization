from dataclasses import replace
from math import isfinite, sqrt
import unittest

from instancelab.features import (
    FEATURE_NAMES,
    FeatureExtractionError,
    compare_instances,
    extract_features,
)
from instancelab.clipp import parse_instance

from tests.test_clipp_reader import REPOSITORY_LAYOUT


class FeatureExtractionTests(unittest.TestCase):
    def setUp(self):
        self.instance = parse_instance(REPOSITORY_LAYOUT, source="tiny.txt")

    def test_extracts_expected_characteristics(self):
        features = extract_features(self.instance)

        self.assertEqual(features.source, "tiny.txt")
        self.assertEqual(tuple(features.as_dict()), FEATURE_NAMES)
        self.assertEqual(features["num_junctions"], 3.0)
        self.assertEqual(features["num_streets"], 3.0)
        self.assertAlmostEqual(features["street_to_junction_ratio"], 1.0)
        self.assertAlmostEqual(features["directed_arc_to_junction_ratio"], 4 / 3)
        self.assertAlmostEqual(features["out_degree_cv"], sqrt(2) / 4)
        self.assertAlmostEqual(features["connector_street_fraction"], 1 / 3)
        self.assertAlmostEqual(features["mandatory_service_fraction"], 1 / 2)
        self.assertAlmostEqual(features["mandatory_length_fraction"], 1 / 3)
        self.assertAlmostEqual(features["bidirectional_street_fraction"], 1 / 3)
        self.assertAlmostEqual(features["mean_travel_time"], 35 / 3)
        self.assertAlmostEqual(features["mean_service_length"], 150.0)
        self.assertAlmostEqual(features["service_length_cv"], 1 / 3)
        self.assertAlmostEqual(features["mean_service_requirement"], 15.0)
        self.assertEqual(features["high_requirement_fraction"], 0.0)
        self.assertEqual(features["mean_vehicle_capacity"], 20.0)
        self.assertEqual(features["large_vehicle_fraction"], 0.5)
        self.assertEqual(features["mandatory_length_per_vehicle"], 50.0)
        self.assertEqual(features["mean_mandatory_fleet_coverage"], 1.0)
        # Mandatory street 0-1 takes 10 s; 10 s out, return 10 s: round trip 20 s.
        self.assertAlmostEqual(features["mandatory_time_pressure"], 10 / 200)
        self.assertAlmostEqual(features["service_time_pressure"], 30 / 200)
        self.assertAlmostEqual(features["mean_mandatory_round_trip_ratio"], 0.2)
        self.assertAlmostEqual(features["max_mandatory_round_trip_ratio"], 0.2)
        self.assertTrue(all(isfinite(value) for value in features.values))

    def test_round_trip_uses_shortest_depot_paths(self):
        text = (
            "4 4 100 1 0 1.0\n"
            "0 1 1 5 0 C 0\n"
            "1 2 1 10 100 M 10\n"
            "2 3 1 5 0 C 0\n"
            "3 0 1 5 0 C 0\n"
            "S\n"
        )
        features = extract_features(parse_instance(text))

        self.assertAlmostEqual(features["mean_mandatory_round_trip_ratio"], 0.25)
        self.assertAlmostEqual(features["mandatory_time_pressure"], 0.10)

    def test_builds_stable_comparison_table(self):
        second = replace(self.instance, source="second.txt")
        table = compare_instances((self.instance, second))

        self.assertEqual(len(table), 2)
        self.assertEqual(tuple(table[0]), ("source", *FEATURE_NAMES))
        self.assertEqual(table[0]["source"], "tiny.txt")
        self.assertEqual(table[1]["source"], "second.txt")
        self.assertEqual(table[0]["num_streets"], table[1]["num_streets"])

    def test_measures_partial_fleet_coverage(self):
        demanding_street = replace(self.instance.streets[0], requirement=30)
        demanding = replace(
            self.instance,
            streets=(demanding_street, *self.instance.streets[1:]),
        )

        features = extract_features(demanding)

        self.assertEqual(features["mean_mandatory_fleet_coverage"], 0.5)

    def test_keeps_zero_denominator_features_finite(self):
        empty = parse_instance("2 0 100 1 0 0.5\nS\n", source="empty.txt")

        features = extract_features(empty)

        self.assertEqual(features["street_to_junction_ratio"], 0.0)
        self.assertEqual(features["travel_time_cv"], 0.0)
        self.assertEqual(features["mandatory_service_fraction"], 0.0)
        self.assertTrue(all(isfinite(value) for value in features.values))

    def test_rejects_invalid_instance(self):
        invalid = replace(self.instance, depot=99)

        with self.assertRaisesRegex(FeatureExtractionError, "depot_range"):
            extract_features(invalid)


if __name__ == "__main__":
    unittest.main()
