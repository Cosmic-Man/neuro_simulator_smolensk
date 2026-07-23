from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .config import IMPULSE_LIMIT, PROJECT_ROOT
from .data import NODE_SPECS
from .fcm import BUILTIN_SCENARIOS


SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ADJUSTABLE_NODES = {spec.id for spec in NODE_SPECS if spec.adjustable}
INDEX_CONTROL_IDS = {
    "urban_environment",
    "road_quality_dtc",
    "accessible_environment",
    "public_spaces",
    "road_quality_transit",
    "parking_safety",
}
SCENARIO_DIR = PROJECT_ROOT / "runtime" / "scenarios"


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
    raw_index_values = payload.get("index_values", {})
    if not isinstance(raw_index_values, Mapping):
        raise ValueError("index_values должен быть словарём шести индексов")
    unknown_indexes = set(raw_index_values) - INDEX_CONTROL_IDS
    if unknown_indexes:
        raise ValueError(f"Неизвестные управляемые индексы: {sorted(unknown_indexes)}")
    index_values = {str(index_id): float(value) for index_id, value in raw_index_values.items()}
    if any(not 0.0 <= value <= 100.0 for value in index_values.values()):
        raise ValueError("Значения управляемых индексов должны быть в диапазоне [0, 100]")
    return {
        "version": 1,
        "id": scenario_id,
        "label": label,
        "description": description,
        "mode": mode,
        "horizon": horizon,
        "impulses": impulses,
        "index_values": index_values,
        "builtin": False,
    }


def builtin_items() -> list[dict[str, Any]]:
    return [
        {"id": scenario_id, **scenario, "index_values": {}, "builtin": True}
        for scenario_id, scenario in BUILTIN_SCENARIOS.items()
    ]


def get_builtin(scenario_id: str) -> dict[str, Any] | None:
    scenario = BUILTIN_SCENARIOS.get(scenario_id)
    if scenario is None:
        return None
    return {"id": scenario_id, **scenario, "index_values": {}, "builtin": True}


def export_payload(scenario: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: scenario[key]
        for key in ("version", "id", "label", "description", "mode", "horizon", "impulses", "index_values")
    }


class ScenarioStore:
    """JSON-сценарии в отслеживаемой Git папке runtime/scenarios."""

    def __init__(self, directory: Path | str = SCENARIO_DIR):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, scenario_id: str) -> Path:
        if not SCENARIO_ID.fullmatch(scenario_id):
            raise ValueError("Некорректный id сценария")
        return self.directory / f"{scenario_id}.json"

    def get(self, scenario_id: str) -> dict[str, Any] | None:
        path = self._path(scenario_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_scenario(payload)

    def items(self) -> list[dict[str, Any]]:
        return [self.get(path.stem) for path in sorted(self.directory.glob("*.json"))]

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        scenario = validate_scenario(payload)
        path = self._path(scenario["id"])
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{scenario['id']}-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(export_payload(scenario), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            Path(temp_name).replace(path)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return scenario
