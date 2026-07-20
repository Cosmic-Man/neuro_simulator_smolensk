from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.scenarios import ScenarioConflictError, ScenarioStore


class ScenarioStoreTests(unittest.TestCase):
    def test_user_scenario_is_persisted_and_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as directory:
            store = ScenarioStore(Path(directory))
            payload = {
                "version": 1,
                "id": "team-plan",
                "label": "Командный сценарий",
                "description": "Первый вариант",
                "mode": "adapted",
                "horizon": 8,
                "impulses": {"road_repair": 0.10},
            }
            store.save(payload)
            payload["description"] = "Обновлённый вариант"
            payload["impulses"] = {"road_repair": 0.15}
            store.save(payload)
            restored = ScenarioStore(Path(directory)).get("team-plan")
            self.assertEqual(restored["description"], "Обновлённый вариант")
            self.assertEqual(restored["impulses"]["road_repair"], 0.15)

    def test_builtin_scenario_is_protected(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as directory:
            store = ScenarioStore(Path(directory))
            with self.assertRaises(ScenarioConflictError):
                store.save({"version": 1, "id": "safety", "label": "X", "description": "", "mode": "adapted", "horizon": 8, "impulses": {}})


if __name__ == "__main__":
    unittest.main()
