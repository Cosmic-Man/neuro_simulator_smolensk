from __future__ import annotations

import unittest

import numpy as np

from app.config import DATA_PATH, TRAIN_END
from app.data import EXPECTED_PERIODS, FEATURE_NAMES, NODE_IDS, load_problem_b_data


class DataPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_problem_b_data(DATA_PATH)

    def test_shared_excel_schema_and_periods(self) -> None:
        self.assertEqual(self.bundle.raw.index.to_list(), EXPECTED_PERIODS)
        self.assertEqual(self.bundle.features.shape, (80, 31))
        self.assertEqual(self.bundle.features.columns.to_list(), FEATURE_NAMES)
        self.assertEqual(len(set(self.bundle.features.columns)), 31)
        self.assertEqual(len(self.bundle.feature_metadata), 31)

    def test_time_splits_have_expected_size(self) -> None:
        periods = self.bundle.raw.index
        self.assertEqual(int((periods <= "2018Q4").sum()), 52)
        self.assertEqual(int(((periods >= "2019Q1") & (periods <= "2022Q4")).sum()), 16)
        self.assertEqual(int((periods >= "2023Q1").sum()), 12)

    def test_fuzzy_indices_and_factors_are_finite_and_bounded(self) -> None:
        self.assertNotIn("linear_expert_index", self.bundle.raw.columns)
        self.assertEqual(self.bundle.fuzzy_indices.shape, (80, 8))
        self.assertTrue(np.isfinite(self.bundle.fuzzy_indices.to_numpy()).all())
        self.assertGreaterEqual(float(self.bundle.fuzzy_indices.min().min()), 0.0)
        self.assertLessEqual(float(self.bundle.fuzzy_indices.max().max()), 100.0)
        self.assertEqual(self.bundle.factors.columns.to_list(), NODE_IDS)
        self.assertTrue(np.isfinite(self.bundle.factors.to_numpy()).all())
        self.assertGreaterEqual(float(self.bundle.factors.min().min()), 0.0)
        self.assertLessEqual(float(self.bundle.factors.max().max()), 1.0)

    def test_scalers_are_fit_on_train_only(self) -> None:
        for name, scaler in {**self.bundle.scalers, **self.bundle.feature_scalers}.items():
            self.assertEqual(scaler.fitted_until, TRAIN_END, name)
        train_accidents = self.bundle.raw.loc[:TRAIN_END, "accidents"]
        self.assertEqual(self.bundle.scalers["accidents"].minimum, float(train_accidents.min()))
        self.assertEqual(self.bundle.scalers["accidents"].maximum, float(train_accidents.max()))

    def test_integrated_index_is_mean_of_three_targets(self) -> None:
        expected = self.bundle.factors[["traffic_safety", "transport_regularity", "transport_accessibility"]].mean(axis=1) * 100.0
        np.testing.assert_allclose(self.bundle.raw["integrated_mobility"], expected)

    def test_hierarchical_index_uses_train_only_bounds(self) -> None:
        index = self.bundle.raw["hierarchical_fuzzy_index"]
        self.assertTrue(np.isfinite(index.to_numpy()).all())
        self.assertGreaterEqual(float(index.min()), 0.0)
        self.assertLessEqual(float(index.max()), 100.0)
        train = self.bundle.fuzzy_indices.loc[:TRAIN_END, self.bundle.hierarchical_model.feature_names]
        np.testing.assert_allclose(self.bundle.hierarchical_model.minimum_, train.min())
        np.testing.assert_allclose(self.bundle.hierarchical_model.maximum_, train.max())


if __name__ == "__main__":
    unittest.main()
