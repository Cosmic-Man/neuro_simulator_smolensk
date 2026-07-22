from __future__ import annotations

import re
from typing import Any, Mapping

from .config import IMPULSE_LIMIT
from .data import NODE_SPECS
from .fcm import BUILTIN_SCENARIOS


SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ADJUSTABLE_NODES = {spec.id for spec in NODE_SPECS if spec.adjustable}


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
        if not -IMPULSE_LIMIT <= numeric <= IMPULSE_LIMIT:
            raise ValueError(f"Воздействие на {node} должно быть в диапазоне [-1, 1]")
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
        {"id": scenario_id, **scenario, "builtin": True}
        for scenario_id, scenario in BUILTIN_SCENARIOS.items()
    ]


def get_builtin(scenario_id: str) -> dict[str, Any] | None:
    scenario = BUILTIN_SCENARIOS.get(scenario_id)
    if scenario is None:
        return None
    return {"id": scenario_id, **scenario, "builtin": True}


def export_payload(scenario: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: scenario[key]
        for key in ("version", "id", "label", "description", "mode", "horizon", "impulses")
    }
