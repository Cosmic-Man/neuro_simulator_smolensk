from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.data import FEATURE_NAMES, load_problem_b_data
from app.datasets import DatasetStore


class DatasetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        source = Path("datasets_ready/smolensk_dataset_shared.xlsx")
        self.target = Path(self.temp_dir.name) / source.name
        shutil.copy2(source, self.target)
        self.store = DatasetStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_and_update_are_validated_by_pipeline(self) -> None:
        zeros = {name: 0.0 for name in FEATURE_NAMES}
        period = self.store.append_row(self.target.name, zeros, load_problem_b_data)
        self.assertEqual(period, "2026Q1")
        detail = self.store.read(self.target.name)
        self.assertEqual(detail["rows"], 81)
        self.assertEqual(detail["rows_data"][-1]["period"], "2026Q1")
        self.assertTrue(all(value == 0.0 for value in detail["rows_data"][-1]["values"].values()))

        updated = dict(zeros)
        updated["скорость_магистрали_B_кмч"] = 47.0
        self.store.update_row(self.target.name, "2026Q1", updated, load_problem_b_data)
        detail = self.store.read(self.target.name)
        self.assertEqual(detail["rows_data"][-1]["values"]["скорость_магистрали_B_кмч"], 47.0)

    def test_paths_cannot_escape_dataset_directory(self) -> None:
        with self.assertRaises(ValueError):
            self.store.read("../smolensk_dataset_shared.xlsx")


if __name__ == "__main__":
    unittest.main()
