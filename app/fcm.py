from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .config import FCM_ALPHA, FCM_LAMBDA, TRAIN_END
from .data import NODE_IDS, NODE_SPECS


EXPERT_EDGES = (
    ("road_budget_execution", "road_repair", 0.75),
    ("road_budget_execution", "road_condition", 0.20),
    ("road_budget_execution", "road_quality", 0.20),
    ("road_repair", "road_condition", 0.65),
    ("road_repair", "road_quality", 0.50),
    ("road_repair", "congestion", -0.20),
    ("road_condition", "road_quality", 0.55),
    ("road_condition", "congestion", -0.35),
    ("road_condition", "traffic_safety", 0.55),
    ("road_condition", "transport_accessibility", 0.35),
    ("defect_response", "road_condition", 0.30),
    ("defect_response", "road_quality", 0.30),
    ("defect_response", "traffic_safety", 0.30),
    ("transit_budget_execution", "transport_regularity", 0.60),
    ("transit_budget_execution", "passenger_flow", 0.30),
    ("transit_budget_execution", "road_wellbeing", 0.35),
    ("passenger_flow", "congestion", 0.45),
    ("passenger_flow", "transport_regularity", -0.20),
    ("transport_regularity", "passenger_flow", 0.25),
    ("transport_regularity", "transport_accessibility", 0.65),
    ("average_speed", "congestion", -0.60),
    ("average_speed", "transport_accessibility", 0.30),
    ("safety_budget_execution", "crossings", 0.55),
    ("safety_budget_execution", "traffic_safety", 0.20),
    ("crossings", "traffic_safety", 0.55),
    ("crossings", "transport_accessibility", 0.25),
    ("road_quality", "traffic_safety", 0.25),
    ("road_quality", "transport_accessibility", 0.35),
    ("road_wellbeing", "transport_accessibility", 0.40),
    ("transport_environment", "transport_accessibility", 0.45),
    ("congestion", "transport_regularity", -0.45),
    ("congestion", "traffic_safety", -0.35),
    ("congestion", "transport_accessibility", -0.60),
    ("traffic_safety", "transport_accessibility", 0.25),
)


ADJUSTABLE_SPECS = tuple(spec for spec in NODE_SPECS if spec.adjustable)
REVERSE_REALLOCATION_FOCUS_IDS = (
    "congestion",
    "road_repair",
)
REALLOCATION_SHARE = 1.0 / (len(ADJUSTABLE_SPECS) - 1)


def _reverse_reallocation_scenario(focus_id: str, focus_label: str) -> dict[str, object]:
    impulses = {
        spec.id: (-1.0 if spec.id == focus_id else REALLOCATION_SHARE)
        for spec in ADJUSTABLE_SPECS
    }
    return {
        "version": 1,
        "label": f"−1 одному, +1 суммарно остальным · {focus_label}",
        "description": (
            f"Тип перераспределения: −1 одному фактору, +1 суммарно остальным. Фактор «{focus_label}» получает −1. "
            "Каждый из остальных управляемых факторов получает по +0,10: суммарный прирост равен +1, "
            "поэтому общий баланс импульсов равен нулю."
        ),
        "mode": "adapted",
        "horizon": 8,
        "impulses": impulses,
    }


_LABEL_BY_ID = {spec.id: spec.label for spec in ADJUSTABLE_SPECS}

RELATION_SCENARIOS: dict[str, dict[str, object]] = {
    "relation_road_repair": {
        "version": 1,
        "label": "Связь · ремонт дорог → нормативное состояние",
        "description": "Проверяет, как максимальное усиление ремонта дорог меняет состояние дорожной сети и связанные показатели.",
        "mode": "adapted", "horizon": 8, "impulses": {"road_repair": 1.0},
    },
    "relation_road_condition": {
        "version": 1,
        "label": "Связь · состояние дорог → безопасность и время поездки",
        "description": "Улучшение нормативного состояния дорог должно снижать загруженность и поддерживать безопасность движения.",
        "mode": "adapted", "horizon": 8, "impulses": {"road_condition": 1.0},
    },
    "relation_lighting_proxy": {
        "version": 1,
        "label": "Связь · освещённость и переходы → безопасность",
        "description": "В датасете нет отдельного ряда освещённости, поэтому используется ближайший измеримый показатель — регулируемые переходы.",
        "mode": "adapted", "horizon": 8, "impulses": {"crossings": 1.0},
    },
    "relation_regularity": {
        "version": 1,
        "label": "Связь · регулярность → доступность транспорта",
        "description": "Показывает эффект максимального повышения доли рейсов, выполненных по расписанию.",
        "mode": "adapted", "horizon": 8, "impulses": {"transport_regularity": 1.0},
    },
    "relation_digital_control": {
        "version": 1,
        "label": "Связь · цифровое управление → пропускная способность",
        "description": "Прокси-сценарий цифрового управления: скорость повышается, а загруженность снижается одновременно.",
        "mode": "adapted", "horizon": 8, "impulses": {"average_speed": 0.6, "congestion": -0.4},
    },
    "relation_travel_time": {
        "version": 1,
        "label": "Связь · снижение времени поездки → доступность",
        "description": "Среднее время поездки представлено обратным показателем загруженности: импульс −1 означает её максимальное снижение.",
        "mode": "adapted", "horizon": 8, "impulses": {"congestion": -1.0},
    },
    "relation_accident_growth": {
        "version": 1,
        "label": "Риск · рост аварийности → снижение результата",
        "description": "Стресс-сценарий ухудшения безопасности движения для оценки устойчивости транспортной системы.",
        "mode": "adapted", "horizon": 8, "impulses": {"traffic_safety": -1.0},
    },
    "relation_pedestrian_space": {
        "version": 1,
        "label": "Баланс · пешеходная инфраструктура и дорожное пространство",
        "description": "Переходы усиливаются, но небольшая часть пропускной способности перераспределяется в пользу пешеходов.",
        "mode": "adapted", "horizon": 8, "impulses": {"crossings": 1.0, "average_speed": -0.2},
    },
}

BUILTIN_SCENARIOS: dict[str, dict[str, object]] = {
    "inertial": {
        "version": 1,
        "label": "Инерционный сценарий",
        "description": "Темпы ремонта дорог, развитие общественного транспорта и цифровизация сохраняются без значительных изменений.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {},
    },
    "road_infrastructure_decline": {
        "version": 1,
        "label": "Ухудшение дорожной инфраструктуры",
        "description": "Ремонт дорог замедляется, доля дорог в нормативном состоянии снижается, число аварийно-опасных участков растёт. Модель показывает последствия для аварийности, времени поездки и удовлетворённости.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"road_repair": -0.75, "road_condition": -0.75, "defect_response": -0.55},
    },
    "public_transport_priority": {
        "version": 1,
        "label": "Приоритет общественного транспорта",
        "description": "Улучшаются регулярность движения, состояние остановок, маршрутная связанность и пассажиропоток. Модель оценивает снижение нагрузки на дороги и рост доступности социальных объектов.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"transit_budget_execution": 0.8, "transport_regularity": 0.8, "passenger_flow": 0.55},
    },
    "digital_mobility": {
        "version": 1,
        "label": "Цифровая мобильность",
        "description": "Вводятся интеллектуальные светофоры, мониторинг потоков и цифровое управление маршрутами. Модель показывает, когда цифровые меры дают значимый эффект, а когда их ограничивает физическое состояние инфраструктуры.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"average_speed": 0.65, "congestion": -0.65, "transport_regularity": 0.35},
    },
    "traffic_safety_priority": {
        "version": 1,
        "label": "Безопасность движения",
        "description": "Ресурсы направляются на освещение, пешеходную инфраструктуру, ликвидацию аварийно-опасных участков и организацию движения. Оценивается влияние на ДТП и воспринимаемую безопасность.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"safety_budget_execution": 0.8, "crossings": 0.85, "road_repair": 0.35},
    },
}


@dataclass
class WeightSet:
    expert: pd.DataFrame
    data: pd.DataFrame
    adapted: pd.DataFrame


def build_expert_matrix() -> pd.DataFrame:
    matrix = pd.DataFrame(0.0, index=NODE_IDS, columns=NODE_IDS)
    for source, target, weight in EXPERT_EDGES:
        matrix.loc[source, target] = weight
    return matrix


def _lagged_strength(factors: pd.DataFrame, source: str, target: str) -> float:
    train = factors.loc[:TRAIN_END]
    x = train[source].iloc[:-1].to_numpy(dtype=float)
    y = train[target].iloc[1:].to_numpy(dtype=float)
    if np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return 0.05
    correlation = float(np.corrcoef(x, y)[0, 1])
    return float(np.clip(abs(correlation), 0.05, 1.0)) if np.isfinite(correlation) else 0.05


def build_weight_set(
    factors: pd.DataFrame,
    anfis_effects: Mapping[str, Mapping[str, float]],
) -> WeightSet:
    expert = build_expert_matrix()
    data = pd.DataFrame(0.0, index=NODE_IDS, columns=NODE_IDS)
    for source, target, weight in EXPERT_EDGES:
        data.loc[source, target] = np.sign(weight) * _lagged_strength(factors, source, target)

    for target, effects in anfis_effects.items():
        if target not in NODE_IDS:
            continue
        available = {source: value for source, value in effects.items() if source in NODE_IDS and expert.loc[source, target] != 0.0}
        scale = max((abs(value) for value in available.values()), default=0.0)
        if scale <= 1e-12:
            continue
        for source, value in available.items():
            magnitude = float(np.clip(abs(value) / scale, 0.05, 1.0))
            data.loc[source, target] = np.sign(expert.loc[source, target]) * magnitude

    adapted = (0.70 * expert + 0.30 * data).clip(-1.0, 1.0)
    for source, target, expert_weight in EXPERT_EDGES:
        adapted.loc[source, target] = np.sign(expert_weight) * abs(float(adapted.loc[source, target]))
    return WeightSet(expert=expert, data=data, adapted=adapted)


def sigmoid(x: np.ndarray, lamb: float = FCM_LAMBDA) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-float(lamb) * np.clip(x, -60.0, 60.0)))


def fcm_step(
    state: np.ndarray,
    weights: np.ndarray,
    external: np.ndarray | None = None,
    alpha: float = FCM_ALPHA,
    lamb: float = FCM_LAMBDA,
) -> np.ndarray:
    state = np.asarray(state, dtype=float)
    external = np.zeros_like(state) if external is None else np.asarray(external, dtype=float)
    if weights.shape != (len(state), len(state)) or external.shape != state.shape:
        raise ValueError("Несовместимые размеры состояния, матрицы FCM или импульса")
    activated = sigmoid(state @ weights + external, lamb=lamb)
    return np.clip((1.0 - alpha) * state + alpha * activated, 0.0, 1.0)


def fcm_forecast(
    initial_state: np.ndarray,
    weights: np.ndarray,
    horizon: int,
    external: np.ndarray | None = None,
) -> np.ndarray:
    states = [np.asarray(initial_state, dtype=float).copy()]
    current = states[0]
    for _ in range(int(horizon)):
        current = fcm_step(current, weights, external)
        states.append(current.copy())
    return np.vstack(states)


def impulse_vector(impulses: Mapping[str, float]) -> np.ndarray:
    result = np.zeros(len(NODE_IDS), dtype=float)
    for node, value in impulses.items():
        if node not in NODE_IDS:
            raise ValueError(f"Неизвестный узел FCM: {node}")
        result[NODE_IDS.index(node)] = float(value)
    return result


def graph_payload(weights: WeightSet, mode: str) -> dict[str, object]:
    if mode == "expert":
        matrix = weights.expert
    elif mode == "adapted":
        matrix = weights.adapted
    else:
        raise ValueError("Режим FCM должен быть expert или adapted")
    nodes = [
        {
            "data": {
                "id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "unit": spec.unit,
                "description": spec.description,
            }
        }
        for spec in NODE_SPECS
    ]
    edges = []
    for source, target, _ in EXPERT_EDGES:
        weight = float(matrix.loc[source, target])
        edges.append(
            {
                "data": {
                    "id": f"{source}-{target}",
                    "source": source,
                    "target": target,
                    "weight": round(weight, 4),
                    "label": f"{weight:+.2f}",
                    "sign": "positive" if weight >= 0.0 else "negative",
                }
            }
        )
    return {"mode": mode, "nodes": nodes, "edges": edges}


def next_period(period: str, offset: int = 1) -> str:
    year, quarter = int(period[:4]), int(period[-1])
    index = year * 4 + quarter - 1 + int(offset)
    return f"{index // 4}Q{index % 4 + 1}"

