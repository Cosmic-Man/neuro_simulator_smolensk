from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .data import NODE_SPECS
from .db_models import Scenario, ScenarioShare, User
from .fcm import BUILTIN_SCENARIOS


SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ADJUSTABLE_NODES = {spec.id for spec in NODE_SPECS if spec.adjustable}


class ScenarioConflictError(ValueError):
    pass


class ScenarioNotFoundError(ValueError):
    pass


def validate_scenario(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {"id", "label", "description", "mode", "horizon", "impulses"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"В сценарии отсутствуют поля: {sorted(missing)}")
    if int(payload.get("version", 1)) != 1:
        raise ValueError("Поддерживается только версия сценария 1")
    scenario_id = str(payload["id"]).strip().lower()
    if not SCENARIO_ID.fullmatch(scenario_id):
        raise ValueError("id должен состоять из латинских букв, цифр, '_' или '-'")
    label = str(payload["label"]).strip()
    description = str(payload["description"]).strip()
    if not 1 <= len(label) <= 100:
        raise ValueError("Длина label должна составлять от 1 до 100 символов")
    if len(description) > 1000:
        raise ValueError("Описание сценария не должно превышать 1000 символов")
    mode = str(payload["mode"])
    if mode not in {"expert", "adapted"}:
        raise ValueError("mode должен быть expert или adapted")
    horizon = int(payload["horizon"])
    if not 1 <= horizon <= 20:
        raise ValueError("Горизонт должен составлять от 1 до 20 кварталов")
    raw_impulses = payload["impulses"]
    if not isinstance(raw_impulses, Mapping) or len(raw_impulses) > len(ADJUSTABLE_NODES):
        raise ValueError("impulses должен быть словарём разрешённых узлов")
    impulses: dict[str, float] = {}
    for node, value in raw_impulses.items():
        if node not in ADJUSTABLE_NODES:
            raise ValueError(f"Узел {node} нельзя изменять в пользовательском сценарии")
        numeric = float(value)
        if not -0.30 <= numeric <= 0.30:
            raise ValueError(f"Воздействие на {node} должно быть в диапазоне [-0.30, 0.30]")
        if abs(numeric) > 1e-12:
            impulses[node] = numeric
    return {
        "version": 1,
        "id": scenario_id,
        "label": label,
        "description": description,
        "mode": mode,
        "horizon": horizon,
        "impulses": impulses,
        "builtin": False,
    }


def builtin_items() -> list[dict[str, Any]]:
    return [
        {"id": scenario_id, **scenario, "builtin": True, "database_id": None}
        for scenario_id, scenario in BUILTIN_SCENARIOS.items()
    ]


def get_builtin(scenario_id: str) -> dict[str, Any] | None:
    scenario = BUILTIN_SCENARIOS.get(scenario_id)
    if scenario is None:
        return None
    return {"id": scenario_id, **scenario, "builtin": True, "database_id": None}


def scenario_to_dict(scenario: Scenario, *, include_owner: bool = False) -> dict[str, Any]:
    output: dict[str, Any] = {
        "version": scenario.schema_version,
        "id": scenario.slug,
        "database_id": str(scenario.id),
        "label": scenario.label,
        "description": scenario.description,
        "mode": scenario.mode,
        "horizon": scenario.horizon,
        "impulses": dict(scenario.impulses or {}),
        "builtin": False,
    }
    if include_owner:
        output["owner"] = {
            "id": str(scenario.owner.id),
            "username": scenario.owner.username,
            "display_name": scenario.owner.display_name,
        }
    return output


def export_payload(scenario: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: scenario[key]
        for key in ("version", "id", "label", "description", "mode", "horizon", "impulses")
    }


class ScenarioStore:
    def __init__(self, session: Session):
        self.session = session

    def list(self, user: User) -> list[dict[str, Any]]:
        query = (
            select(Scenario)
            .options(joinedload(Scenario.owner))
            .order_by(Scenario.updated_at.desc(), Scenario.slug)
        )
        if user.role == "observer":
            query = query.join(ScenarioShare).where(ScenarioShare.observer_id == user.id)
        elif user.role != "admin":
            query = query.where(Scenario.owner_id == user.id)
        records = self.session.scalars(query).all()
        return builtin_items() + [
            scenario_to_dict(record, include_owner=user.role in {"admin", "observer"})
            for record in records
        ]

    def _get_record(self, reference: str, user: User) -> Scenario:
        try:
            scenario_uuid = uuid.UUID(str(reference))
        except ValueError:
            scenario_uuid = None

        query = select(Scenario)
        if scenario_uuid is not None:
            query = query.where(Scenario.id == scenario_uuid)
        else:
            query = query.where(Scenario.slug == str(reference).lower())
        if user.role == "observer":
            query = query.join(ScenarioShare).where(ScenarioShare.observer_id == user.id)
        elif user.role != "admin":
            query = query.where(Scenario.owner_id == user.id)

        records = self.session.scalars(query.limit(2)).all()
        if not records:
            raise ScenarioNotFoundError("Сценарий не найден")
        if len(records) > 1:
            raise ScenarioConflictError("Сценарий неоднозначен; используйте database_id")
        return records[0]

    def get(self, reference: str, user: User) -> dict[str, Any]:
        builtin = get_builtin(reference)
        if builtin is not None:
            return builtin
        return scenario_to_dict(
            self._get_record(reference, user),
            include_owner=user.role in {"admin", "observer"},
        )

    def sharing(self, reference: str, user: User) -> dict[str, Any]:
        if get_builtin(reference) is not None:
            raise ScenarioConflictError("Встроенный сценарий доступен всем и не требует выдачи доступа")
        if user.role not in {"user", "admin"}:
            raise ScenarioNotFoundError("Сценарий не найден")
        record = self._get_record(reference, user)
        selected_ids = set(
            self.session.scalars(
                select(ScenarioShare.observer_id).where(ScenarioShare.scenario_id == record.id)
            ).all()
        )
        observers = self.session.scalars(
            select(User)
            .where(User.role == "observer", User.is_active.is_(True))
            .order_by(User.display_name, User.username)
        ).all()
        return {
            "scenario": scenario_to_dict(record, include_owner=True),
            "observers": [
                {
                    "id": str(observer.id),
                    "username": observer.username,
                    "display_name": observer.display_name,
                    "selected": observer.id in selected_ids,
                }
                for observer in observers
            ],
        }

    def set_sharing(
        self,
        reference: str,
        user: User,
        observer_ids: list[uuid.UUID],
    ) -> dict[str, Any]:
        if get_builtin(reference) is not None:
            raise ScenarioConflictError("Встроенный сценарий доступен всем и не требует выдачи доступа")
        if user.role not in {"user", "admin"}:
            raise ScenarioNotFoundError("Сценарий не найден")
        record = self._get_record(reference, user)
        unique_ids = set(observer_ids)
        observers = self.session.scalars(
            select(User).where(
                User.id.in_(unique_ids),
                User.role == "observer",
                User.is_active.is_(True),
            )
        ).all() if unique_ids else []
        if {observer.id for observer in observers} != unique_ids:
            raise ValueError("Доступ можно выдать только активным пользователям с ролью наблюдателя")

        self.session.execute(delete(ScenarioShare).where(ScenarioShare.scenario_id == record.id))
        self.session.add_all(
            ScenarioShare(scenario_id=record.id, observer_id=observer.id)
            for observer in observers
        )
        self.session.commit()
        return self.sharing(reference, user)

    def save(self, payload: Mapping[str, Any], owner: User) -> dict[str, Any]:
        scenario = validate_scenario(payload)
        if scenario["id"] in BUILTIN_SCENARIOS:
            raise ScenarioConflictError("Встроенный сценарий нельзя перезаписать")
        record = Scenario(
            owner_id=owner.id,
            slug=scenario["id"],
            label=scenario["label"],
            description=scenario["description"],
            mode=scenario["mode"],
            horizon=scenario["horizon"],
            impulses=scenario["impulses"],
            schema_version=scenario["version"],
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise ScenarioConflictError("Сценарий с таким id уже существует у пользователя") from error
        self.session.refresh(record)
        return scenario_to_dict(record, include_owner=owner.role == "admin")

    def update(self, reference: str, payload: Mapping[str, Any], user: User) -> dict[str, Any]:
        if get_builtin(reference) is not None:
            raise ScenarioConflictError("Встроенный сценарий нельзя изменить")
        record = self._get_record(reference, user)
        scenario = validate_scenario(payload)
        if scenario["id"] in BUILTIN_SCENARIOS:
            raise ScenarioConflictError("Нельзя использовать id встроенного сценария")
        record.slug = scenario["id"]
        record.label = scenario["label"]
        record.description = scenario["description"]
        record.mode = scenario["mode"]
        record.horizon = scenario["horizon"]
        record.impulses = scenario["impulses"]
        record.schema_version = scenario["version"]
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise ScenarioConflictError("Сценарий с таким id уже существует у пользователя") from error
        self.session.refresh(record)
        return scenario_to_dict(record, include_owner=user.role == "admin")

    def delete(self, reference: str, user: User) -> dict[str, Any]:
        if get_builtin(reference) is not None:
            raise ScenarioConflictError("Встроенный сценарий нельзя удалить")
        record = self._get_record(reference, user)
        result = scenario_to_dict(record, include_owner=user.role == "admin")
        self.session.delete(record)
        self.session.commit()
        return result
