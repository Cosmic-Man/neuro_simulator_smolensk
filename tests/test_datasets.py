from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.data import FEATURE_NAMES, load_problem_b_data
from app.datasets import DatasetStore
from app.fcm import next_period
from app.service import ProblemBService


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
        before = self.store.read(self.target.name)
        expected_period = next_period(before["rows_data"][-1]["period"])
        period = self.store.append_row(self.target.name, zeros, load_problem_b_data)
        self.assertEqual(period, expected_period)
        detail = self.store.read(self.target.name)
        self.assertEqual(detail["rows"], before["rows"] + 1)
        self.assertEqual(detail["rows_data"][-1]["period"], expected_period)
        self.assertTrue(all(value == 0.0 for value in detail["rows_data"][-1]["values"].values()))

        updated = dict(zeros)
        updated["скорость_магистрали_B_кмч"] = 47.0
        self.store.update_row(self.target.name, expected_period, updated, load_problem_b_data)
        detail = self.store.read(self.target.name)
        self.assertEqual(detail["rows_data"][-1]["values"]["скорость_магистрали_B_кмч"], 47.0)

    def test_paths_cannot_escape_dataset_directory(self) -> None:
        with self.assertRaises(ValueError):
            self.store.read("../smolensk_dataset_shared.xlsx")

    def test_catalog_survives_unreadable_xlsx(self) -> None:
        unreadable = Path(self.temp_dir.name) / "unreadable.xlsx"
        unreadable.write_bytes(b"not an xlsx")

        catalog = self.store.catalog(self.target.name)

        broken = next(item for item in catalog["datasets"] if item["name"] == unreadable.name)
        valid = next(item for item in catalog["datasets"] if item["name"] == self.target.name)
        self.assertFalse(broken["readable"])
        self.assertTrue(valid["readable"])

    def test_xlsx_can_be_uploaded_and_validated(self) -> None:
        content = self.target.read_bytes()
        uploaded = self.store.import_xlsx("uploaded.xlsx", content, load_problem_b_data)
        self.assertEqual(uploaded, "uploaded.xlsx")
        self.assertEqual(self.store.read(uploaded)["rows"], self.store.read(self.target.name)["rows"])
        with self.assertRaises(ValueError):
            self.store.import_xlsx("broken.xlsx", b"not an xlsx", load_problem_b_data)
        self.assertFalse((Path(self.temp_dir.name) / "broken.xlsx").exists())

    def test_new_quarter_marks_model_pending_until_full_retraining(self) -> None:
        model_dir = Path(self.temp_dir.name) / "models"
        service = ProblemBService(
            bundle=load_problem_b_data(self.target),
            model_dir=model_dir,
        )
        latest_values = self.store.read(self.target.name)["rows_data"][-1]["values"]
        expected_period = next_period(self.store.read(self.target.name)["rows_data"][-1]["period"])
        period = self.store.append_row(self.target.name, latest_values, load_problem_b_data)
        self.assertEqual(period, expected_period)
        self.assertTrue(service.training_status(self.target)["pending_retrain"])

        refreshed = ProblemBService(
            bundle=load_problem_b_data(self.target),
            model_dir=model_dir,
            force_retrain=True,
        )
        status = refreshed.training_status(self.target)
        self.assertFalse(status["pending_retrain"])
        self.assertEqual(status["trained_through"], expected_period)
        self.assertEqual(status["new_quarters"], sum(period > "2025Q4" for period in refreshed.bundle.raw.index))


if __name__ == "__main__":
    unittest.main()
