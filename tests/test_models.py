from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.data import NODE_SPECS
from app.fcm import (
    BUILTIN_SCENARIOS,
    EXPERT_EDGES,
    REALLOCATION_FOCUS_IDS,
    REVERSE_REALLOCATION_FOCUS_IDS,
)
from app.models import ANFIS, ModelArtifactError
from app.service import ProblemBService


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = ProblemBService()

    def test_fcm_shape_edge_count_and_weight_constraints(self) -> None:
        self.assertEqual(self.service.weights.expert.shape, (16, 16))
        self.assertGreaterEqual(len(EXPERT_EDGES), 30)
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
            self.assertIn(
                self.service.anfis_model_sources[target],
                {"artifact", "trained_and_cached", "trained_in_memory"},
            )
        self.assertEqual(len(self.service.pipeline_anfis.feature_names), 8)
        self.assertEqual(self.service.pipeline_anfis.rule_count, 6)
        self.assertTrue(math.isfinite(self.service.pipeline_anfis.validation_rmse_))

    def test_anfis_artifact_round_trip_and_compatibility_checks(self) -> None:
        x_train = np.asarray(
            [[0.0, 0.1], [0.2, 0.3], [0.4, 0.2], [0.6, 0.7], [0.8, 0.6], [1.0, 0.9]],
            dtype=float,
        )
        y_train = 20.0 + 15.0 * x_train[:, 0] - 4.0 * x_train[:, 1]
        x_validation = np.asarray([[0.1, 0.2], [0.5, 0.5], [0.9, 0.8]], dtype=float)
        y_validation = 20.0 + 15.0 * x_validation[:, 0] - 4.0 * x_validation[:, 1]
        model = ANFIS(("first", "second"))
        signature = model.training_signature(
            x_train,
            y_train,
            x_validation,
            y_validation,
            context="round-trip",
        )
        model.fit(x_train, y_train, x_validation, y_validation)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            model.save(path, training_signature=signature)
            loaded = ANFIS.load(
                path,
                expected_features=("first", "second"),
                expected_training_signature=signature,
            )
            np.testing.assert_allclose(model.predict(x_validation), loaded.predict(x_validation))
            self.assertEqual(loaded.rule_count, model.rule_count)
            with self.assertRaises(ModelArtifactError):
                ANFIS.load(
                    path,
                    expected_features=("first", "second"),
                    expected_training_signature="0" * 64,
                )
            with self.assertRaises(ModelArtifactError):
                ANFIS.load(
                    path,
                    expected_features=("second", "first"),
                    expected_training_signature=signature,
                )

    def test_all_evaluation_metrics_are_finite(self) -> None:
        catalog = self.service.evaluation()["model_catalog"]
        self.assertEqual([item["id"] for item in catalog], list(self.service.evaluation()["model_labels"]))
        self.assertEqual(len(catalog), 3)
        for item in catalog:
            for key in ("label", "role", "how", "inputs", "purpose"):
                self.assertTrue(item[key].strip(), f"{item['id']} {key}")
        for target in self.service.evaluation()["targets"]:
            for row in target["metrics"]:
                for key in ("mae", "rmse", "smape", "mase", "directional_accuracy"):
                    self.assertTrue(math.isfinite(row[key]), f"{target['id']} {row['model']} {key}")

    def test_scenario_directions_are_plausible(self) -> None:
        safety = self.service.simulate("improve_safety_budget_execution")
        self.assertGreater(safety["scenario_result"][-1]["safety_index"], safety["baseline"][-1]["safety_index"])
        self.assertLess(safety["scenario_result"][-1]["accidents"], safety["baseline"][-1]["accidents"])

        transit = self.service.simulate("improve_transit_budget_execution")
        self.assertGreater(transit["scenario_result"][-1]["regularity"], transit["baseline"][-1]["regularity"])
        self.assertGreater(transit["scenario_result"][-1]["accessibility"], transit["baseline"][-1]["accessibility"])

        roads = self.service.simulate("improve_road_budget_execution")
        self.assertGreater(roads["scenario_result"][-1]["accessibility"], roads["baseline"][-1]["accessibility"])

    def test_builtin_scenarios_follow_point_and_reallocation_rules(self) -> None:
        adjustable = {spec.id for spec in NODE_SPECS if spec.adjustable}
        point_scenarios = {
            scenario_id: scenario
            for scenario_id, scenario in BUILTIN_SCENARIOS.items()
            if scenario_id.startswith("improve_")
        }
        self.assertEqual(len(point_scenarios), 10)
        for scenario in point_scenarios.values():
            self.assertEqual(len(scenario["impulses"]), 1)
            self.assertEqual(next(iter(scenario["impulses"].values())), 1.0)

        reallocation_scenarios = {
            scenario_id: scenario
            for scenario_id, scenario in BUILTIN_SCENARIOS.items()
            if scenario_id.startswith("reallocate_")
        }
        self.assertEqual(len(reallocation_scenarios), len(REALLOCATION_FOCUS_IDS))
        for focus_id in REALLOCATION_FOCUS_IDS:
            impulses = reallocation_scenarios[f"reallocate_{focus_id}"]["impulses"]
            self.assertEqual(set(impulses), adjustable)
            self.assertEqual(impulses[focus_id], 1.0)
            negatives = [value for node, value in impulses.items() if node != focus_id]
            self.assertTrue(all(value < 0 for value in negatives))
            self.assertAlmostEqual(sum(negatives), -1.0)
            self.assertAlmostEqual(sum(impulses.values()), 0.0)

        reverse_scenarios = {
            scenario_id: scenario
            for scenario_id, scenario in BUILTIN_SCENARIOS.items()
            if scenario_id.startswith("reverse_reallocate_")
        }
        self.assertEqual(len(reverse_scenarios), len(REVERSE_REALLOCATION_FOCUS_IDS))
        kind_by_id = {spec.id: spec.kind for spec in NODE_SPECS}
        for focus_id in REVERSE_REALLOCATION_FOCUS_IDS:
            self.assertNotEqual(kind_by_id[focus_id], "target")
            scenario = reverse_scenarios[f"reverse_reallocate_{focus_id}"]
            impulses = scenario["impulses"]
            self.assertEqual(set(impulses), adjustable)
            self.assertEqual(impulses[focus_id], -1.0)
            positives = [value for node, value in impulses.items() if node != focus_id]
            self.assertTrue(all(value > 0 for value in positives))
            self.assertAlmostEqual(sum(positives), 1.0)
            self.assertAlmostEqual(sum(impulses.values()), 0.0)

        self.assertEqual(len(BUILTIN_SCENARIOS), 25)

    def test_unknown_node_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.simulate("custom", custom_impulses={"unknown": 0.1})


if __name__ == "__main__":
    unittest.main()

