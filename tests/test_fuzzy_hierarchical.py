from __future__ import annotations

import unittest

import numpy as np

from app.data import load_problem_b_data
from app.fuzzy import FUZZY_INDEX_SPECS, PIPELINE_RULE_DIR, build_fuzzy_system, trapmf, trimf
from app.hierarchical_index import HIERARCHICAL_FUZZY_SPECS


class FuzzyAndHierarchicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_problem_b_data()

    def test_membership_boundaries(self) -> None:
        self.assertEqual(trimf(0, 0, 5, 10), 0.0)
        self.assertEqual(trimf(5, 0, 5, 10), 1.0)
        self.assertEqual(trimf(10, 0, 5, 10), 0.0)
        self.assertEqual(trapmf(5, 0, 3, 7, 10), 1.0)

    def test_all_colab_rule_tables_are_complete(self) -> None:
        self.assertEqual(len(FUZZY_INDEX_SPECS), 8)
        self.assertEqual(sum(len(build_fuzzy_system(spec).rules) for spec in FUZZY_INDEX_SPECS), 1176)
        self.assertTrue(all((PIPELINE_RULE_DIR / spec.rule_filename).is_file() for spec in FUZZY_INDEX_SPECS))

    def test_hierarchical_weights_and_contributions(self) -> None:
        self.assertEqual([spec.weight for spec in HIERARCHICAL_FUZZY_SPECS], [0.6, 0.6, 0.7, 0.2, 0.5, 0.7, 0.9, 0.4])
        contributions = self.bundle.hierarchical_contributions
        expected = contributions.drop(columns="hierarchical_fuzzy_index").sum(axis=1)
        np.testing.assert_allclose(contributions["hierarchical_fuzzy_index"], expected)
        np.testing.assert_allclose(
            contributions["hierarchical_fuzzy_index"],
            self.bundle.raw["hierarchical_fuzzy_index"],
        )

    def test_known_pipeline_membership_results(self) -> None:
        first = self.bundle.fuzzy_indices.iloc[0]
        expected_first = {
            "urban_environment": 9.4366009795,
            "road_quality_dtc": 27.5749718674,
            "road_wellbeing_dtc": 9.6449270586,
            "accessible_environment": 8.9207297270,
            "public_spaces": 14.4284270484,
            "road_quality_transit": 10.4024016609,
            "road_wellbeing_transit": 13.3934224624,
            "parking_safety": 24.1732540837,
        }
        expected_last = {
            "urban_environment": 88.611092,
            "road_quality_dtc": 0.0,
            "road_wellbeing_dtc": 95.444293,
            "accessible_environment": 78.949130,
            "public_spaces": 95.545402,
            "road_quality_transit": 0.0,
            "road_wellbeing_transit": 94.739771,
            "parking_safety": 95.196587,
        }
        for name, expected in expected_first.items():
            self.assertAlmostEqual(first[name], expected, places=5, msg=name)
        for name, expected in expected_last.items():
            self.assertAlmostEqual(self.bundle.fuzzy_indices.iloc[-1][name], expected, places=5, msg=name)
        self.assertAlmostEqual(self.bundle.raw["pipeline_target"].iloc[0], 14.5569163653, places=6)
        self.assertAlmostEqual(self.bundle.raw["pipeline_target"].iloc[-1], 66.714047, places=5)
        target = self.bundle.raw["pipeline_target"]
        self.assertAlmostEqual(target.mean(), 46.934475, places=5)
        self.assertAlmostEqual(target.std(), 14.203631, places=5)
        self.assertAlmostEqual(target.min(), 14.556916, places=5)
        self.assertAlmostEqual(target.max(), 67.437482, places=5)


if __name__ == "__main__":
    unittest.main()
