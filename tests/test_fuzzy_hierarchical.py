from __future__ import annotations

import unittest

import numpy as np

from app.data import load_problem_b_data
from app.fuzzy import FUZZY_INDEX_SPECS, build_fuzzy_system, trapmf, trimf
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
        self.assertEqual(sum(len(build_fuzzy_system(spec).rules) for spec in FUZZY_INDEX_SPECS), 2164)

    def test_hierarchical_weights_and_contributions(self) -> None:
        self.assertEqual([spec.weight for spec in HIERARCHICAL_FUZZY_SPECS], [0.6, 0.6, 0.7, 0.2, 0.5, 0.7, 0.9, 0.4])
        contributions = self.bundle.hierarchical_contributions
        expected = contributions.drop(columns="hierarchical_fuzzy_index").sum(axis=1)
        np.testing.assert_allclose(contributions["hierarchical_fuzzy_index"], expected)
        np.testing.assert_allclose(
            contributions["hierarchical_fuzzy_index"] * 100.0,
            self.bundle.raw["hierarchical_fuzzy_index"],
        )


if __name__ == "__main__":
    unittest.main()
