from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .config import GAIN, RETENTION, TRAIN_END
from .data import NODE_IDS, NODE_SPECS


EXPERT_EDGES = [
    ("road_budget", "road_repair", 0.75),
    ("road_budget", "road_condition", 0.20),
    ("management_efficiency", "road_repair", 0.35),
    ("management_efficiency", "transport_regularity", 0.25),
    ("management_efficiency", "lighting", 0.20),
    ("management_efficiency", "active_mobility", 0.20),
    ("road_repair", "road_condition", 0.65),
    ("road_repair", "congestion", -0.20),
    ("road_condition", "congestion", -0.35),
    ("road_condition", "traffic_safety", 0.55),
    ("road_condition", "accessibility", 0.35),
    ("transit_budget", "stops", 0.50),
    ("transit_budget", "transport_regularity", 0.60),
    ("transit_budget", "passenger_demand", 0.30),
    ("transit_budget", "digital_mobility", 0.35),
    ("stops", "transport_regularity", 0.30),
    ("stops", "accessibility", 0.40),
    ("digital_mobility", "transport_regularity", 0.35),
    ("digital_mobility", "congestion", -0.25),
    ("digital_mobility", "accessibility", 0.30),
    ("passenger_demand", "congestion", 0.45),
    ("passenger_demand", "transport_regularity", -0.20),
    ("congestion", "transport_regularity", -0.45),
    ("congestion", "traffic_safety", -0.35),
    ("congestion", "accessibility", -0.60),
    ("safety_budget", "lighting", 0.45),
    ("safety_budget", "crossings", 0.55),
    ("safety_budget", "traffic_safety", 0.20),
    ("lighting", "traffic_safety", 0.50),
    ("crossings", "traffic_safety", 0.55),
    ("crossings", "accessibility", 0.25),
    ("active_mobility_budget", "active_mobility", 0.65),
    ("active_mobility", "accessibility", 0.55),
    ("active_mobility", "traffic_safety", 0.20),
    ("transport_regularity", "passenger_demand", 0.25),
    ("transport_regularity", "accessibility", 0.65),
    ("traffic_safety", "accessibility", 0.25),
]


SCENARIOS: dict[str, dict[str, object]] = {
    "inertial": {"label": "Инерционный", "description": "Продолжение текущей динамики без внешнего импульса.", "impulses": {}},
    "limited_resources": {
        "label": "Ограничение ресурсов",
        "description": "Снижение финансирования и исполнения транспортных программ.",
        "impulses": {"road_budget": -0.16, "transit_budget": -0.14, "safety_budget": -0.12, "active_mobility_budget": -0.10, "management_efficiency": -0.06},
    },
    "road_deterioration": {
        "label": "Ухудшение дорог",
        "description": "Снижение ремонта и нормативного состояния при росте загруженности.",
        "impulses": {"road_repair": -0.14, "road_condition": -0.18, "congestion": 0.12},
    },
    "transit_priority": {
        "label": "Приоритет общественного транспорта",
        "description": "Усиление финансирования, остановок и регулярности транспорта.",
        "impulses": {"transit_budget": 0.16, "stops": 0.10, "transport_regularity": 0.10},
    },
    "digital_mobility": {
        "label": "Цифровая мобильность",
        "description": "Развитие информирования пассажиров и цифрового управления движением.",
        "impulses": {"digital_mobility": 0.18, "transport_regularity": 0.06, "congestion": -0.06},
    },
    "safety": {
        "label": "Повышение безопасности",
        "description": "Дополнительные ресурсы на освещение, переходы и безопасность движения.",
        "impulses": {"safety_budget": 0.15, "lighting": 0.16, "crossings": 0.16},
    },
    "custom": {"label": "Пользовательский", "description": "Собственный набор управляющих воздействий.", "impulses": {}},
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

    target_feature_map = {
        "traffic_safety": {
            "road_condition": "road_condition",
            "lighting": "lighting",
            "crossings": "crossings",
        },
        "transport_regularity": {
            "transit_budget": "transit_budget",
            "passenger_demand": "passenger_demand",
            "stops": "stops",
        },
        "accessibility": {
            "transport_regularity": "regularity",
            "congestion": "avg_speed",
            "active_mobility": "active_mobility",
        },
    }
    for target, mapping in target_feature_map.items():
        effects = anfis_effects.get(target, {})
        magnitudes = [abs(effects.get(feature, 0.0)) for feature in mapping.values()]
        scale = max(magnitudes, default=0.0)
        if scale < 1e-12:
            continue
        for source, feature in mapping.items():
            expert_weight = float(expert.loc[source, target])
            if expert_weight == 0.0:
                continue
            magnitude = float(np.clip(abs(effects.get(feature, 0.0)) / scale, 0.05, 1.0))
            data.loc[source, target] = np.sign(expert_weight) * magnitude

    adapted = 0.70 * expert + 0.30 * data
    adapted = adapted.clip(-1.0, 1.0)
    for source, target, expert_weight in EXPERT_EDGES:
        value = float(adapted.loc[source, target])
        if np.sign(value) != np.sign(expert_weight):
            adapted.loc[source, target] = np.sign(expert_weight) * abs(value)
    return WeightSet(expert=expert, data=data, adapted=adapted)


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-values))


def fcm_step(
    state: np.ndarray,
    weights: np.ndarray,
    external: np.ndarray | None = None,
    retention: float = RETENTION,
    gain: float = GAIN,
) -> np.ndarray:
    state = np.asarray(state, dtype=float)
    external = np.zeros_like(state) if external is None else np.asarray(external, dtype=float)
    activated = sigmoid(gain * (state @ weights + external))
    return np.clip(retention * state + (1.0 - retention) * activated, 0.0, 1.0)


def fcm_forecast(
    initial_state: np.ndarray,
    weights: np.ndarray,
    horizon: int,
    external: np.ndarray | None = None,
) -> np.ndarray:
    states = [np.asarray(initial_state, dtype=float).copy()]
    for _ in range(horizon):
        states.append(fcm_step(states[-1], weights, external))
    return np.vstack(states)


def impulse_vector(impulses: Mapping[str, float]) -> np.ndarray:
    vector = np.zeros(len(NODE_IDS), dtype=float)
    for node, value in impulses.items():
        if node not in NODE_IDS:
            raise ValueError(f"Неизвестный узел сценария: {node}")
        numeric = float(value)
        if not -0.30 <= numeric <= 0.30:
            raise ValueError(f"Воздействие на {node} должно быть в диапазоне [-0.30, 0.30].")
        vector[NODE_IDS.index(node)] = numeric
    return vector


def graph_payload(weight_set: WeightSet, mode: str) -> dict[str, object]:
    if mode not in {"expert", "adapted"}:
        raise ValueError("Режим FCM должен быть expert или adapted.")
    selected = weight_set.expert if mode == "expert" else weight_set.adapted
    nodes = [
        {
            "id": spec.id,
            "label": spec.label,
            "kind": spec.kind,
            "unit": spec.unit,
            "description": spec.description,
        }
        for spec in NODE_SPECS
    ]
    edges = []
    for source, target, _ in EXPERT_EDGES:
        weight = float(selected.loc[source, target])
        edges.append(
            {
                "id": f"{source}__{target}",
                "source": source,
                "target": target,
                "weight": round(weight, 5),
                "sign": "positive" if weight > 0 else "negative",
                "expert_weight": round(float(weight_set.expert.loc[source, target]), 5),
                "data_weight": round(float(weight_set.data.loc[source, target]), 5),
                "adapted_weight": round(float(weight_set.adapted.loc[source, target]), 5),
            }
        )
    return {"mode": mode, "node_count": len(nodes), "edge_count": len(edges), "nodes": nodes, "edges": edges}


def next_period(period: str, offset: int) -> str:
    year = int(period[:4])
    quarter = int(period[-1])
    absolute = year * 4 + (quarter - 1) + offset
    return f"{absolute // 4}Q{absolute % 4 + 1}"

