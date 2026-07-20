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


BUILTIN_SCENARIOS: dict[str, dict[str, object]] = {
    "inertial": {
        "version": 1,
        "label": "Инерционный",
        "description": "Продолжение текущей динамики без внешнего импульса.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {},
    },
    "limited_resources": {
        "version": 1,
        "label": "Ограниченный бюджет",
        "description": "Снижение исполнения дорожной, транспортной и безопасностной программ.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"road_budget_execution": -0.16, "transit_budget_execution": -0.14, "safety_budget_execution": -0.12},
    },
    "road_deterioration": {
        "version": 1,
        "label": "Ухудшение дорог",
        "description": "Снижение ремонта, нормативного состояния и эффективности устранения дефектов.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"road_repair": -0.14, "road_condition": -0.18, "defect_response": -0.10},
    },
    "transit_priority": {
        "version": 1,
        "label": "Приоритет общественного транспорта",
        "description": "Усиление транспортной программы, регулярности и пассажиропотока.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"transit_budget_execution": 0.16, "transport_regularity": 0.10, "passenger_flow": 0.08},
    },
    "digital_mobility": {
        "version": 1,
        "label": "Цифровая мобильность",
        "description": "Прокси цифровизации: повышение регулярности и скорости при снижении загруженности.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"transport_regularity": 0.08, "average_speed": 0.08, "congestion": -0.08},
    },
    "safety": {
        "version": 1,
        "label": "Повышение безопасности",
        "description": "Дополнительные ресурсы, переходы и более быстрое устранение дефектов.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {"safety_budget_execution": 0.15, "crossings": 0.16, "defect_response": 0.10},
    },
    "custom": {
        "version": 1,
        "label": "Пользовательский",
        "description": "Собственный набор управляющих воздействий.",
        "mode": "adapted",
        "horizon": 8,
        "impulses": {},
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

