from __future__ import annotations

import unittest

from app.service import ProblemBService


class ScenarioValueValidationTests(unittest.TestCase):
    def test_impulse_above_allowed_range_is_rejected(self) -> None:
        service = ProblemBService()
        with self.assertRaises(ValueError):
            service.simulate("custom", custom_impulses={"road_budget_execution": 0.31})


if __name__ == "__main__":
    unittest.main()

