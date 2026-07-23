from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    @staticmethod
    def scenario_payload() -> dict[str, object]:
        return {
            "version": 1,
            "id": "api-plan",
            "label": "Локальный сценарий",
            "description": "Проверка JSON без базы данных",
            "mode": "adapted",
            "horizon": 8,
            "impulses": {"road_repair": 0.1},
        }

    def test_public_health_reports_xlsx_storage(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["storage"], "xlsx")

    def test_core_endpoints_require_no_login(self) -> None:
        for path in ("/api/metadata", "/api/history", "/api/indices", "/api/analysis", "/api/scenarios", "/api/datasets"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        scenario = self.client.post("/api/anfis/scenario", json={"index_values": {}})
        self.assertEqual(scenario.status_code, 200)
        self.assertEqual(len(scenario.json()["inputs"]), 6)
        self.assertEqual(len(scenario.json()["forecast"]), 8)
        self.assertEqual(len(scenario.json()["recommendations"]), 3)

    def test_customer_prediction_uses_anfis_instead_of_fcm(self) -> None:
        script_response = self.client.get("/assets/app.js")
        self.assertEqual(script_response.status_code, 200)
        script = script_response.text
        start = script.index("async function runScenario()")
        end = script.index("\nfunction renderSensitivity()", start)
        run_scenario = script[start:end]
        self.assertIn('api("/api/anfis/scenario"', run_scenario)
        self.assertNotIn('api("/api/simulate"', run_scenario)

        baseline = self.client.post("/api/anfis/scenario", json={"index_values": {}, "horizon": 1}).json()
        zero_values = {item["id"]: 0.0 for item in baseline["inputs"]}
        zero = self.client.post(
            "/api/anfis/scenario",
            json={"index_values": zero_values, "horizon": 1},
        )
        self.assertEqual(zero.status_code, 200, zero.text)
        self.assertEqual(zero.json()["scenario_prediction"], 0.0)

    def test_auth_and_admin_routes_are_removed(self) -> None:
        self.assertEqual(self.client.get("/api/auth/me").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 404)

    def test_local_scenario_can_be_validated_and_simulated(self) -> None:
        payload = self.scenario_payload()
        validated = self.client.post("/api/scenarios/validate", json=payload)
        self.assertEqual(validated.status_code, 200, validated.text)
        response = self.client.post(
            "/api/simulate",
            json={"scenario": payload["id"], "scenario_payload": payload},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["scenario"]["id"], payload["id"])
        self.assertIn("summary", result)
        self.assertIn("budget_analysis", result)


if __name__ == "__main__":
    unittest.main()
