from __future__ import annotations

import unittest

from app.scenarios import builtin_items, export_payload, validate_scenario


class ScenarioTests(unittest.TestCase):
    @staticmethod
    def payload() -> dict[str, object]:
        return {
            "version": 1,
            "id": "team-plan",
            "label": "Командный сценарий",
            "description": "Локальный JSON",
            "mode": "adapted",
            "horizon": 8,
            "impulses": {"road_repair": 0.1},
        }

    def test_builtin_catalog_is_available_without_storage(self) -> None:
        scenarios = builtin_items()
        self.assertGreater(len(scenarios), 1)
        self.assertTrue(all(item["builtin"] for item in scenarios))
        self.assertTrue(all("database_id" not in item for item in scenarios))

    def test_local_json_is_validated_and_exported(self) -> None:
        validated = validate_scenario(self.payload())
        self.assertFalse(validated["builtin"])
        self.assertEqual(export_payload(validated), self.payload())

    def test_impulses_are_limited_to_one(self) -> None:
        payload = self.payload()
        payload["impulses"] = {"road_repair": 1.01}
        with self.assertRaises(ValueError):
            validate_scenario(payload)


if __name__ == "__main__":
    unittest.main()
