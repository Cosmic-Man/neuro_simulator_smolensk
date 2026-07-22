from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, build_engine, get_db
from app.main import app
from app.security import create_user


PASSWORD = "DemoPassword2026!"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = build_engine("sqlite+pysqlite:///:memory:")
        if cls.engine.dialect.name != "sqlite":
            raise RuntimeError("API-тесты разрешено выполнять только на SQLite")
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

        def override_get_db():
            with cls.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        with cls.session_factory() as db:
            for username, role in (("api-observer", "observer"), ("api-user", "user"), ("api-admin", "admin")):
                create_user(
                    db,
                    username=username,
                    display_name=username,
                    password=PASSWORD,
                    role=role,
                    must_change_password=False,
                )

        cls.observer, cls.observer_csrf = cls.login("api-observer")
        cls.user, cls.user_csrf = cls.login("api-user")
        cls.admin, cls.admin_csrf = cls.login("api-admin")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.observer.close()
        cls.user.close()
        cls.admin.close()
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    @classmethod
    def login(cls, username: str) -> tuple[TestClient, str]:
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        if response.status_code != 200:
            raise RuntimeError(response.text)
        return client, response.json()["csrf_token"]

    @staticmethod
    def scenario_payload(suffix: str) -> dict[str, object]:
        return {
            "version": 1,
            "id": f"api-plan-{suffix}",
            "label": "API-сценарий",
            "description": "Проверка PostgreSQL-хранилища",
            "mode": "adapted",
            "horizon": 8,
            "impulses": {"road_repair": 0.10},
        }

    def test_public_and_protected_endpoints(self) -> None:
        with TestClient(app) as anonymous:
            self.assertEqual(anonymous.get("/api/health").status_code, 200)
            self.assertEqual(anonymous.get("/api/metadata").status_code, 401)
            self.assertEqual(anonymous.post("/api/simulate", json={"scenario": "improve_safety_budget_execution"}).status_code, 401)

        paths = ("/api/metadata", "/api/history", "/api/indices", "/api/fcm?mode=adapted", "/api/evaluation", "/api/scenarios")
        for path in paths:
            self.assertEqual(self.observer.get(path).status_code, 200, path)
        health = self.observer.get("/api/health").json()
        self.assertEqual(health["periods"], 80)
        self.assertEqual(health["database"], "ok")

    def test_simulation_contains_business_percentages_and_budget_ranking(self) -> None:
        response = self.observer.post(
            "/api/simulate",
            json={"scenario": "improve_safety_budget_execution", "mode": "adapted", "horizon": 8, "impulses": {}},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["baseline"]), 9)
        self.assertEqual(len(payload["scenario_result"]), 9)
        for metric in ("safety", "regularity", "accessibility", "integrated_mobility"):
            self.assertIn("relative_change_percent", payload["summary"][metric])
        self.assertIn("improvement_percent", payload["summary"]["accidents"])
        self.assertEqual(len(payload["budget_analysis"]["programs"]), 3)

    def test_role_permissions_csrf_and_scenario_ownership(self) -> None:
        payload = self.scenario_payload(uuid.uuid4().hex[:8])
        self.assertEqual(self.observer.post("/api/scenarios", json=payload).status_code, 403)
        self.assertEqual(self.user.post("/api/scenarios", json=payload).status_code, 403)

        created = self.user.post(
            "/api/scenarios",
            json=payload,
            headers={"X-CSRF-Token": self.user_csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        scenario_id = created.json()["database_id"]
        payload["description"] = "Сохранено повторно из интерфейса"
        payload["impulses"] = {"road_repair": 0.17, "crossings": 0.05}
        updated = self.user.put(
            f"/api/scenarios/{scenario_id}",
            json=payload,
            headers={"X-CSRF-Token": self.user_csrf},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["impulses"]["road_repair"], 0.17)
        exported = self.user.get(f"/api/scenarios/{scenario_id}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["description"], "Сохранено повторно из интерфейса")
        self.assertEqual(self.observer.get(f"/api/scenarios/{scenario_id}/export").status_code, 404)

        sharing = self.user.get(f"/api/scenarios/{scenario_id}/shares")
        self.assertEqual(sharing.status_code, 200, sharing.text)
        observer_id = next(item["id"] for item in sharing.json()["observers"] if item["username"] == "api-observer")
        shared = self.user.put(
            f"/api/scenarios/{scenario_id}/shares",
            json={"observer_ids": [observer_id]},
            headers={"X-CSRF-Token": self.user_csrf},
        )
        self.assertEqual(shared.status_code, 200, shared.text)
        self.assertEqual(self.observer.get(f"/api/scenarios/{scenario_id}/export").status_code, 200)
        observer_scenarios = self.observer.get("/api/scenarios").json()["scenarios"]
        shared_scenario = next(item for item in observer_scenarios if item["database_id"] == scenario_id)
        self.assertEqual(shared_scenario["owner"]["username"], "api-user")

        denied = self.observer.put(
            f"/api/scenarios/{scenario_id}/shares",
            json={"observer_ids": []},
            headers={"X-CSRF-Token": self.observer_csrf},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.admin.get(f"/api/scenarios/{scenario_id}/export").status_code, 200)
        admin_scenario = next(
            item for item in self.admin.get("/api/scenarios").json()["scenarios"]
            if item["database_id"] == scenario_id
        )
        self.assertEqual(admin_scenario["owner"]["username"], "api-user")

    def test_builtin_scenario_cannot_be_overwritten(self) -> None:
        response = self.admin.post(
            "/api/scenarios",
            json={"version": 1, "id": "improve_safety_budget_execution", "label": "Подмена", "description": "", "mode": "adapted", "horizon": 8, "impulses": {}},
            headers={"X-CSRF-Token": self.admin_csrf},
        )
        self.assertEqual(response.status_code, 409)

    def test_admin_user_management(self) -> None:
        self.assertEqual(self.user.get("/api/admin/users").status_code, 403)
        created = self.admin.post(
            "/api/admin/users",
            json={
                "username": f"viewer-{uuid.uuid4().hex[:8]}",
                "display_name": "Новый наблюдатель",
                "password": PASSWORD,
                "role": "observer",
                "must_change_password": True,
            },
            headers={"X-CSRF-Token": self.admin_csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        user_id = created.json()["id"]
        updated = self.admin.patch(
            f"/api/admin/users/{user_id}",
            json={"role": "user", "is_active": True},
            headers={"X-CSRF-Token": self.admin_csrf},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["role"], "user")

        me = self.admin.get("/api/auth/me").json()
        current_admin_id = me["user"]["id"]
        type(self).admin_csrf = me["csrf_token"]
        blocked = self.admin.patch(
            f"/api/admin/users/{current_admin_id}",
            json={"is_active": False},
            headers={"X-CSRF-Token": type(self).admin_csrf},
        )
        self.assertEqual(blocked.status_code, 409)

    def test_validation_rejects_bad_requests(self) -> None:
        self.assertEqual(self.observer.get("/api/fcm?mode=wrong").status_code, 422)
        self.assertEqual(self.observer.post("/api/simulate", json={"scenario": "missing", "horizon": 8}).status_code, 404)
        self.assertEqual(self.observer.post("/api/simulate", json={"scenario": "inertial", "horizon": 50}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
