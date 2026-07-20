from __future__ import annotations

import unittest

import numpy as np

from app.config import DATA_PATH, TRAIN_END
from app.data import EXPECTED_PERIODS, NODE_IDS, load_problem_b_data


class DataPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_problem_b_data(DATA_PATH)

    def test_all_quarters_and_selected_sheets_are_present(self) -> None:
        self.assertEqual(self.bundle.raw.index.to_list(), EXPECTED_PERIODS)
        self.assertEqual(len(self.bundle.sheets), 5)
        self.assertTrue(all(len(frame) == 80 for frame in self.bundle.sheets.values()))

    def test_time_splits_have_expected_size(self) -> None:
        periods = self.bundle.raw.index
        self.assertEqual(int((periods <= "2018Q4").sum()), 52)
        self.assertEqual(int(((periods >= "2019Q1") & (periods <= "2022Q4")).sum()), 16)
        self.assertEqual(int((periods >= "2023Q1").sum()), 12)

    def test_factors_are_finite_and_bounded(self) -> None:
        self.assertEqual(self.bundle.factors.columns.to_list(), NODE_IDS)
        self.assertTrue(np.isfinite(self.bundle.factors.to_numpy()).all())
        self.assertGreaterEqual(float(self.bundle.factors.min().min()), 0.0)
        self.assertLessEqual(float(self.bundle.factors.max().max()), 1.0)

    def test_scalers_are_fit_on_train_only(self) -> None:
        for name, scaler in self.bundle.scalers.items():
            self.assertEqual(scaler.fitted_until, TRAIN_END, name)
        train_accidents = self.bundle.raw.loc[:TRAIN_END, "accidents"]
        self.assertEqual(self.bundle.scalers["accidents"].minimum, float(train_accidents.min()))
        self.assertEqual(self.bundle.scalers["accidents"].maximum, float(train_accidents.max()))


if __name__ == "__main__":
    unittest.main()

