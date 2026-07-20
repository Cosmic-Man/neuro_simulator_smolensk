from __future__ import annotations

import math
import unittest

import numpy as np

from app.fcm import EXPERT_EDGES
from app.service import ProblemBService


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = ProblemBService()

    def test_fcm_shape_edge_count_and_weight_constraints(self) -> None:
        self.assertEqual(self.service.weights.expert.shape, (17, 17))
        self.assertGreaterEqual(len(EXPERT_EDGES), 25)
        self.assertLessEqual(float(np.abs(self.service.weights.adapted.to_numpy()).max()), 1.0)
        for source, target, expert in EXPERT_EDGES:
            adapted = float(self.service.weights.adapted.loc[source, target])
            self.assertEqual(np.sign(adapted), np.sign(expert), f"{source} -> {target}")

    def test_anfis_is_small_reproducible_and_finite(self) -> None:
        for target, model in self.service.anfis_models.items():
            self.assertLessEqual(len(model.feature_names), 4, target)
            self.assertLessEqual(model.rule_count, 16, target)
            sample = self.service.anfis_samples[target]
            first = model.predict(sample.x[-5:])
            second = model.predict(sample.x[-5:])
            self.assertTrue(np.isfinite(first).all(), target)
            np.testing.assert_allclose(first, second)

    def test_all_evaluation_metrics_are_finite(self) -> None:
        for target in self.service.evaluation()["targets"]:
            for row in target["metrics"]:
                for key in ("mae", "rmse", "smape", "mase", "directional_accuracy"):
                    self.assertTrue(math.isfinite(row[key]), f"{target['id']} {row['model']} {key}")

    def test_scenario_directions_are_plausible(self) -> None:
        safety = self.service.simulate("safety")
        self.assertGreater(safety["scenario_result"][-1]["safety_index"], safety["baseline"][-1]["safety_index"])
        self.assertLess(safety["scenario_result"][-1]["accidents"], safety["baseline"][-1]["accidents"])

        deterioration = self.service.simulate("road_deterioration")
        self.assertLess(deterioration["scenario_result"][-1]["safety_index"], deterioration["baseline"][-1]["safety_index"])
        self.assertLess(deterioration["scenario_result"][-1]["accessibility"], deterioration["baseline"][-1]["accessibility"])

        transit = self.service.simulate("transit_priority")
        self.assertGreater(transit["scenario_result"][-1]["regularity"], transit["baseline"][-1]["regularity"])
        self.assertGreater(transit["scenario_result"][-1]["accessibility"], transit["baseline"][-1]["accessibility"])

    def test_unknown_node_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.simulate("custom", custom_impulses={"unknown": 0.1})


if __name__ == "__main__":
    unittest.main()

