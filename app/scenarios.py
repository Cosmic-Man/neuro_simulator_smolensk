from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Mapping

from .config import SCENARIO_DIR
from .data import NODE_SPECS
from .fcm import BUILTIN_SCENARIOS


SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ADJUSTABLE_NODES = {spec.id for spec in NODE_SPECS if spec.adjustable}


class ScenarioConflictError(ValueError):
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


class ScenarioStore:
    def __init__(self, directory: Path = SCENARIO_DIR):
        self.directory = Path(directory)
        self._lock = threading.RLock()

    @staticmethod
    def builtin_items() -> list[dict[str, Any]]:
        return [
            {"id": scenario_id, **scenario, "builtin": True}
            for scenario_id, scenario in BUILTIN_SCENARIOS.items()
        ]

    def _user_items(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                validated = validate_scenario(data)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            items.append(validated)
        return items

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return self.builtin_items() + self._user_items()

    def get(self, scenario_id: str) -> dict[str, Any]:
        for scenario in self.list():
            if scenario["id"] == scenario_id:
                return scenario
        raise ValueError(f"Неизвестный сценарий: {scenario_id}")

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        scenario = validate_scenario(payload)
        if scenario["id"] in BUILTIN_SCENARIOS:
            raise ScenarioConflictError("Встроенный сценарий нельзя перезаписать")
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{scenario['id']}.json"
            temporary = self.directory / f".{scenario['id']}.tmp"
            serialized = json.dumps(
                {key: value for key, value in scenario.items() if key != "builtin"},
                ensure_ascii=False,
                indent=2,
            )
            temporary.write_text(serialized + "\n", encoding="utf-8")
            os.replace(temporary, target)
        return scenario
