from __future__ import annotations

import unittest

from sqlalchemy.orm import Session

from app.database import Base, build_engine
from app.db_models import User
from app.scenarios import ScenarioConflictError, ScenarioNotFoundError, ScenarioStore


class ScenarioStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = build_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.owner = User(
            username="owner",
            display_name="Владелец",
            password_hash="not-used",
            role="user",
            must_change_password=False,
        )
        self.other = User(
            username="other",
            display_name="Другой пользователь",
            password_hash="not-used",
            role="user",
            must_change_password=False,
        )
        self.observer = User(
            username="observer",
            display_name="Наблюдатель",
            password_hash="not-used",
            role="observer",
            must_change_password=False,
        )
        self.session.add_all((self.owner, self.other, self.observer))
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def payload() -> dict[str, object]:
        return {
            "version": 1,
            "id": "team-plan",
            "label": "Командный сценарий",
            "description": "Первый вариант",
            "mode": "adapted",
            "horizon": 8,
            "impulses": {"road_repair": 0.10},
        }

    def test_user_scenario_is_persisted_and_updated(self) -> None:
        store = ScenarioStore(self.session)
        saved = store.save(self.payload(), self.owner)
        payload = self.payload()
        payload["description"] = "Обновлённый вариант"
        payload["impulses"] = {"road_repair": 0.15}
        store.update(saved["database_id"], payload, self.owner)

        restored = store.get(saved["database_id"], self.owner)
        self.assertEqual(restored["description"], "Обновлённый вариант")
        self.assertEqual(restored["impulses"]["road_repair"], 0.15)

    def test_scenarios_are_isolated_by_owner(self) -> None:
        store = ScenarioStore(self.session)
        saved = store.save(self.payload(), self.owner)
        with self.assertRaises(ScenarioNotFoundError):
            store.get(saved["database_id"], self.other)
        self.assertTrue(all(item["builtin"] for item in store.list(self.observer)))

        sharing = store.set_sharing(saved["database_id"], self.owner, [self.observer.id])
        self.assertTrue(sharing["observers"][0]["selected"])
        shared = store.get(saved["database_id"], self.observer)
        self.assertEqual(shared["owner"]["username"], self.owner.username)
        self.assertIn(saved["database_id"], {item["database_id"] for item in store.list(self.observer)})

        store.set_sharing(saved["database_id"], self.owner, [])
        with self.assertRaises(ScenarioNotFoundError):
            store.get(saved["database_id"], self.observer)

    def test_builtin_scenario_is_protected(self) -> None:
        payload = self.payload()
        payload["id"] = "improve_safety_budget_execution"
        with self.assertRaises(ScenarioConflictError):
            ScenarioStore(self.session).save(payload, self.owner)


if __name__ == "__main__":
    unittest.main()
