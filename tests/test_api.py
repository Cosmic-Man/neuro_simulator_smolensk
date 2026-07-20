from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_read_endpoints(self) -> None:
        paths = ("/api/health", "/api/metadata", "/api/history", "/api/indices", "/api/fcm?mode=adapted", "/api/evaluation", "/api/scenarios")
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        self.assertEqual(self.client.get("/api/health").json()["periods"], 80)
        self.assertGreater(self.client.get("/api/health").json()["initialization_seconds"], 0.0)

    def test_simulation_contract(self) -> None:
        response = self.client.post(
            "/api/simulate",
            json={"scenario": "safety", "mode": "adapted", "horizon": 8, "impulses": {}},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["baseline"]), 9)
        self.assertEqual(len(payload["scenario_result"]), 9)
        self.assertTrue(payload["explanation"])
        self.assertIn("integrated_mobility", payload["scenario_result"][-1])

    def test_builtin_scenario_cannot_be_overwritten(self) -> None:
        response = self.client.post(
            "/api/scenarios",
            json={"version": 1, "id": "safety", "label": "Подмена", "description": "", "mode": "adapted", "horizon": 8, "impulses": {}},
        )
        self.assertEqual(response.status_code, 409)

    def test_validation_rejects_bad_requests(self) -> None:
        self.assertEqual(self.client.get("/api/fcm?mode=wrong").status_code, 422)
        self.assertEqual(
            self.client.post("/api/simulate", json={"scenario": "missing", "horizon": 8}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/simulate", json={"scenario": "custom", "horizon": 50}).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()

