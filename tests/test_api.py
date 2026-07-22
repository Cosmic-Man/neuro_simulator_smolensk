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
