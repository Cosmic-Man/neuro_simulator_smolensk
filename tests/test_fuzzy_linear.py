from __future__ import annotations

import unittest

import numpy as np

from app.data import load_problem_b_data
from app.fuzzy import FUZZY_INDEX_SPECS, build_fuzzy_system, trapmf, trimf


class FuzzyAndLinearTests(unittest.TestCase):
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

    def test_linear_contributions_sum_to_index(self) -> None:
        contributions = self.bundle.linear_contributions
        expected = contributions.drop(columns="linear_expert_index").sum(axis=1)
        np.testing.assert_allclose(contributions["linear_expert_index"], expected)
        np.testing.assert_allclose(contributions["linear_expert_index"] * 100.0, self.bundle.raw["linear_expert_index"])


if __name__ == "__main__":
    unittest.main()
