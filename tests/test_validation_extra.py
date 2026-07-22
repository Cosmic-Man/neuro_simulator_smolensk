from __future__ import annotations

import unittest

from app.scenarios import validate_scenario
from app.service import ProblemBService


class ScenarioValueValidationTests(unittest.TestCase):
    def test_impulse_above_allowed_range_is_rejected(self) -> None:
        service = ProblemBService()
        with self.assertRaises(ValueError):
            service.simulate("custom", custom_impulses={"road_budget_execution": 1.01})

    def test_impulses_at_allowed_bounds_are_accepted(self) -> None:
        service = ProblemBService()
        for value in (-1.0, 1.0):
            with self.subTest(value=value):
                result = service.simulate("custom", custom_impulses={"road_budget_execution": value})
                applied = {item["node"]: item["value"] for item in result["applied_impulses"]}
                self.assertEqual(applied["road_budget_execution"], value)

    def test_existing_impulse_can_move_between_full_bounds(self) -> None:
        service = ProblemBService()
        result = service.simulate("relation_road_repair", custom_impulses={"road_repair": -2.0})
        applied = {item["node"]: item["value"] for item in result["applied_impulses"]}
        self.assertEqual(applied["road_repair"], -1.0)

    def test_saved_scenario_accepts_full_impulse_bounds(self) -> None:
        payload = {
            "version": 1,
            "id": "full-range",
            "label": "Полный диапазон",
            "description": "Проверка границ",
            "mode": "adapted",
            "horizon": 8,
            "impulses": {"road_budget_execution": -1.0, "road_repair": 1.0},
        }
        validated = validate_scenario(payload)
        self.assertEqual(validated["impulses"], payload["impulses"])


if __name__ == "__main__":
    unittest.main()

