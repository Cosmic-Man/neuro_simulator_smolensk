from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_HORIZON,
    GAIN,
    RETENTION,
    SHEETS,
    TEST_END,
    TEST_START,
    TRAIN_END,
    TRAIN_START,
    VALIDATION_END,
    VALIDATION_START,
)
from .data import DataBundle, NODE_IDS, NODE_SPECS, load_problem_b_data
from .fcm import (
    EXPERT_EDGES,
    SCENARIOS,
    WeightSet,
    build_weight_set,
    fcm_forecast,
    fcm_step,
    graph_payload,
    impulse_vector,
    next_period,
)
from .models import (
    ANFISRegressor,
    RidgeRegressor,
    SampleSet,
    build_lag_samples,
    build_one_step_samples,
    metric_set,
    split_mask,
)


@dataclass(frozen=True)
class TargetConfig:
    id: str
    label: str
    unit: str
    raw_column: str
    anfis_features: tuple[str, ...]


TARGETS = {
    "traffic_safety": TargetConfig(
        "traffic_safety",
        "ДТП на 10 тыс. жителей",
        "ДТП на 10 тыс.",
        "accidents",
        ("road_condition", "lighting", "crossings", "accidents"),
    ),
    "transport_regularity": TargetConfig(
        "transport_regularity",
        "Рейсы по расписанию",
        "%",
        "regularity",
        ("transit_budget", "passenger_demand", "stops", "regularity"),
    ),
    "accessibility": TargetConfig(
        "accessibility",
        "Индекс транспортной доступности",
        "баллы из 100",
        "accessibility",
        ("regularity", "avg_speed", "active_mobility", "accessibility"),
    ),
}


HISTORY_SERIES = [
    ("accidents", "ДТП на 10 тыс. жителей", "ДТП на 10 тыс.", "target"),
    ("regularity", "Рейсы по расписанию", "%", "target"),
    ("accessibility", "Индекс транспортной доступности", "баллы", "target"),
    ("congestion", "Индекс загруженности", "баллы", "proxy"),
    ("avg_speed", "Средняя скорость на магистралях", "км/ч", "indicator"),
    ("road_condition", "Дороги в нормативном состоянии", "%", "indicator"),
    ("road_repair", "Отремонтированные дороги", "км", "indicator"),
    ("lighting", "Освещённые улицы", "%", "indicator"),
    ("crossings", "Регулируемые переходы", "ед.", "indicator"),
    ("stops", "Обустроенные остановки", "ед.", "indicator"),
    ("digital_mobility", "Остановки с инфотабло", "%", "proxy"),
    ("active_mobility", "Вело-пешеходная инфраструктура", "км", "indicator"),
    ("passenger_demand", "Пассажиропоток", "тыс. поездок", "indicator"),
    ("road_budget", "Финансирование дорог", "млн руб.", "control"),
    ("transit_budget", "Финансирование транспорта", "млн руб.", "control"),
    ("safety_budget", "Финансирование безопасности", "млн руб.", "control"),
]


class ProblemBService:
    def __init__(self, bundle: DataBundle | None = None):
        self.bundle = bundle or load_problem_b_data()
        self.ridge_models: dict[str, RidgeRegressor] = {}
        self.lag_samples: dict[str, SampleSet] = {}
        self.anfis_models: dict[str, ANFISRegressor] = {}
        self.anfis_samples: dict[str, SampleSet] = {}
        self.anfis_effects: dict[str, dict[str, float]] = {}
        self._train_models()
        self.weights: WeightSet = build_weight_set(self.bundle.factors, self.anfis_effects)
        self._evaluation = self._build_evaluation()
        self._sensitivity_cache = self._build_sensitivity("adapted")

    def _train_models(self) -> None:
        raw = self.bundle.raw
        for target_id, config in TARGETS.items():
            target_series = raw[config.raw_column]
            lag_samples = build_lag_samples(target_series)
            train = split_mask(lag_samples.periods, "train")
            ridge = RidgeRegressor(alpha=1.0).fit(lag_samples.x[train], lag_samples.y[train])
            self.lag_samples[target_id] = lag_samples
            self.ridge_models[target_id] = ridge

            anfis_samples = build_one_step_samples(raw, config.anfis_features, config.raw_column)
            anfis_train = split_mask(anfis_samples.periods, "train")
            anfis_validation = split_mask(anfis_samples.periods, "validation")
            anfis = ANFISRegressor(config.anfis_features).fit(
                anfis_samples.x[anfis_train],
                anfis_samples.y[anfis_train],
                anfis_samples.x[anfis_validation],
                anfis_samples.y[anfis_validation],
            )
            self.anfis_models[target_id] = anfis
            self.anfis_samples[target_id] = anfis_samples
            self.anfis_effects[target_id] = anfis.feature_effects(anfis_samples.x[anfis_validation])

    def _clip_prediction(self, target_id: str, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        if target_id == "traffic_safety":
            train_max = float(self.bundle.raw.loc[:TRAIN_END, "accidents"].max())
            return np.clip(values, 0.0, train_max * 1.5)
        return np.clip(values, 0.0, 100.0)

    def _factor_target_to_raw(self, target_id: str, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        if target_id == "traffic_safety":
            return self.bundle.scalers["accidents"].inverse(values)
        if target_id == "transport_regularity":
            return self.bundle.scalers["regularity"].inverse(values)
        if target_id == "accessibility":
            return values * 100.0
        raise ValueError(f"Неизвестная цель: {target_id}")

    def _fcm_prediction_lookup(self, target_id: str, mode: str) -> dict[str, float]:
        matrix = self.weights.expert if mode == "expert" else self.weights.adapted
        target_index = NODE_IDS.index(target_id)
        result: dict[str, float] = {}
        periods = self.bundle.factors.index.to_list()
        for index in range(1, len(periods)):
            prediction = fcm_step(
                self.bundle.factors.iloc[index - 1].to_numpy(dtype=float),
                matrix.to_numpy(dtype=float),
            )[target_index]
            result[periods[index]] = float(self._factor_target_to_raw(target_id, np.asarray([prediction]))[0])
        return result

    def _prediction_lookups(self, target_id: str) -> dict[str, dict[str, float]]:
        lag = self.lag_samples[target_id]
        seasonal = lag.x[:, 3]
        ridge = self._clip_prediction(target_id, self.ridge_models[target_id].predict(lag.x))
        anfis_samples = self.anfis_samples[target_id]
        anfis = self._clip_prediction(target_id, self.anfis_models[target_id].predict(anfis_samples.x))
        return {
            "seasonal_naive": dict(zip(lag.periods, seasonal, strict=True)),
            "ridge": dict(zip(lag.periods, ridge, strict=True)),
            "fcm_expert": self._fcm_prediction_lookup(target_id, "expert"),
            "fcm_adapted": self._fcm_prediction_lookup(target_id, "adapted"),
            "anfis": dict(zip(anfis_samples.periods, anfis, strict=True)),
        }

    def _build_evaluation(self) -> dict[str, Any]:
        model_labels = {
            "seasonal_naive": "Seasonal Naive",
            "ridge": "Ridge по лагам",
            "fcm_expert": "FCM экспертная",
            "fcm_adapted": "FCM адаптированная",
            "anfis": "ANFIS",
        }
        result_targets = []
        for target_id, config in TARGETS.items():
            raw_series = self.bundle.raw[config.raw_column]
            train_values = raw_series.loc[:TRAIN_END].to_numpy(dtype=float)
            lookups = self._prediction_lookups(target_id)
            metrics_rows = []
            predictions: dict[str, list[dict[str, Any]]] = {}
            for split in ("validation", "test"):
                periods = raw_series.index.to_numpy(dtype=str)
                mask = split_mask(periods, split)
                selected_periods = periods[mask]
                actual = raw_series.loc[selected_periods].to_numpy(dtype=float)
                previous = np.asarray(
                    [raw_series.iloc[raw_series.index.get_loc(period) - 1] for period in selected_periods],
                    dtype=float,
                )
                split_rows = []
                for index, period in enumerate(selected_periods):
                    row: dict[str, Any] = {"period": period, "actual": round(float(actual[index]), 5)}
                    for model_id, lookup in lookups.items():
                        if period not in lookup:
                            raise RuntimeError(f"У модели {model_id} нет прогноза для {period}.")
                        row[model_id] = round(float(lookup[period]), 5)
                    split_rows.append(row)
                predictions[split] = split_rows

                for model_id, lookup in lookups.items():
                    predicted = np.asarray([lookup[period] for period in selected_periods], dtype=float)
                    metrics = metric_set(actual, predicted, train_values, previous)
                    metrics_rows.append(
                        {
                            "model": model_id,
                            "model_label": model_labels[model_id],
                            "split": split,
                            **{name: round(value, 6) for name, value in metrics.items()},
                        }
                    )
            result_targets.append(
                {
                    "id": target_id,
                    "label": config.label,
                    "unit": config.unit,
                    "metrics": metrics_rows,
                    "predictions": predictions,
                }
            )

        return {
            "targets": result_targets,
            "model_labels": model_labels,
            "note": "Все модели обучаются только на 2006Q1–2018Q4; параметры ANFIS выбираются по 2019Q1–2022Q4, тест 2023Q1–2025Q4 не используется при настройке.",
        }

    def metadata(self) -> dict[str, Any]:
        anfis = []
        for target_id, model in self.anfis_models.items():
            anfis.append(
                {
                    "target": target_id,
                    "target_label": TARGETS[target_id].label,
                    "inputs": model.feature_names,
                    "rule_count": model.rule_count,
                    "sigma": model.sigma_,
                    "ridge": model.ridge_,
                    "validation_rmse": model.validation_rmse_,
                }
            )
        return {
            "project": "Транспортная доступность и безопасность Смоленска",
            "problem": "Б",
            "source": self.bundle.source_path.name,
            "sheets": [{"id": key, "name": value} for key, value in SHEETS.items()],
            "period": {"start": TRAIN_START, "end": TEST_END, "quarters": len(self.bundle.raw)},
            "splits": {
                "train": {"start": TRAIN_START, "end": TRAIN_END, "quarters": 52},
                "validation": {"start": VALIDATION_START, "end": VALIDATION_END, "quarters": 16},
                "test": {"start": TEST_START, "end": TEST_END, "quarters": 12},
            },
            "fcm": {"nodes": len(NODE_IDS), "edges": len(EXPERT_EDGES), "retention": RETENTION, "gain": GAIN, "blend": "0.70 × expert + 0.30 × data"},
            "nodes": [spec.__dict__ for spec in NODE_SPECS],
            "targets": [config.__dict__ for config in TARGETS.values()],
            "scenarios": [
                {"id": scenario_id, "label": item["label"], "description": item["description"], "impulses": item["impulses"]}
                for scenario_id, item in SCENARIOS.items()
            ],
            "proxies": [
                {"id": "congestion", "label": "Загруженность", "formula": "100 × (1 − нормализованная средняя скорость)"},
                {"id": "accessibility", "label": "Доступность", "formula": "30% регулярность + 20% скорость + 15% остановки + 15% переходы + 20% активная мобильность"},
                {"id": "traffic_safety", "label": "Безопасность FCM", "formula": "1 − нормализованный показатель ДТП"},
                {"id": "digital_mobility", "label": "Цифровая мобильность", "formula": "Прокси по доле остановок с информационными табло"},
            ],
            "anfis": anfis,
        }

    def history(self) -> dict[str, Any]:
        periods = self.bundle.raw.index.to_list()
        split = ["train" if period <= TRAIN_END else "validation" if period <= VALIDATION_END else "test" for period in periods]
        series = []
        for series_id, label, unit, role in HISTORY_SERIES:
            series.append(
                {
                    "id": series_id,
                    "label": label,
                    "unit": unit,
                    "role": role,
                    "values": [round(float(value), 5) for value in self.bundle.raw[series_id]],
                }
            )
        latest = {
            "period": periods[-1],
            "accidents": round(float(self.bundle.raw.iloc[-1]["accidents"]), 2),
            "regularity": round(float(self.bundle.raw.iloc[-1]["regularity"]), 2),
            "accessibility": round(float(self.bundle.raw.iloc[-1]["accessibility"]), 2),
            "avg_speed": round(float(self.bundle.raw.iloc[-1]["avg_speed"]), 2),
        }
        return {"periods": periods, "split": split, "series": series, "latest": latest}

    def fcm(self, mode: str) -> dict[str, object]:
        return graph_payload(self.weights, mode)

    def evaluation(self) -> dict[str, Any]:
        return {**self._evaluation, "sensitivity": self._sensitivity_cache}

    def _weights_array(self, mode: str) -> np.ndarray:
        if mode == "expert":
            return self.weights.expert.to_numpy(dtype=float)
        if mode == "adapted":
            return self.weights.adapted.to_numpy(dtype=float)
        raise ValueError("Режим FCM должен быть expert или adapted.")

    def _scenario_row(self, step: int, state: np.ndarray) -> dict[str, Any]:
        safety = float(state[NODE_IDS.index("traffic_safety")])
        regularity = float(state[NODE_IDS.index("transport_regularity")])
        accessibility = float(state[NODE_IDS.index("accessibility")])
        return {
            "step": step,
            "period": self.bundle.raw.index[-1] if step == 0 else next_period(self.bundle.raw.index[-1], step),
            "safety_index": round(safety * 100.0, 4),
            "accidents": round(float(self._factor_target_to_raw("traffic_safety", np.asarray([safety]))[0]), 4),
            "regularity": round(float(self._factor_target_to_raw("transport_regularity", np.asarray([regularity]))[0]), 4),
            "accessibility": round(accessibility * 100.0, 4),
        }

    def _build_sensitivity(self, mode: str, horizon: int = DEFAULT_HORIZON) -> dict[str, list[dict[str, Any]]]:
        initial = self.bundle.factors.iloc[-1].to_numpy(dtype=float)
        weights = self._weights_array(mode)
        baseline = fcm_forecast(initial, weights, horizon)[-1]
        non_targets = [spec for spec in NODE_SPECS if spec.kind != "target"]
        output: dict[str, list[dict[str, Any]]] = {target: [] for target in TARGETS}
        for spec in non_targets:
            perturbed = fcm_forecast(initial, weights, horizon, impulse_vector({spec.id: 0.07}))[-1]
            for target_id in TARGETS:
                target_index = NODE_IDS.index(target_id)
                normalized_delta = float(perturbed[target_index] - baseline[target_index])
                base_raw = self._factor_target_to_raw(target_id, np.asarray([baseline[target_index]]))[0]
                perturbed_raw = self._factor_target_to_raw(target_id, np.asarray([perturbed[target_index]]))[0]
                output[target_id].append(
                    {
                        "node": spec.id,
                        "label": spec.label,
                        "delta_index_points": round(normalized_delta * 100.0, 5),
                        "delta_raw": round(float(perturbed_raw - base_raw), 5),
                    }
                )
        for target_id in output:
            output[target_id].sort(key=lambda item: abs(item["delta_index_points"]), reverse=True)
        return output

    def simulate(
        self,
        scenario_id: str,
        mode: str = "adapted",
        horizon: int = DEFAULT_HORIZON,
        custom_impulses: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        if scenario_id not in SCENARIOS:
            raise ValueError(f"Неизвестный сценарий: {scenario_id}")
        if not 1 <= int(horizon) <= 20:
            raise ValueError("Горизонт должен составлять от 1 до 20 кварталов.")
        impulses = {key: float(value) for key, value in SCENARIOS[scenario_id]["impulses"].items()}
        for key, value in (custom_impulses or {}).items():
            numeric = float(value)
            if not -0.30 <= numeric <= 0.30:
                raise ValueError(f"Воздействие на {key} должно быть в диапазоне [-0.30, 0.30].")
            impulses[key] = float(np.clip(impulses.get(key, 0.0) + numeric, -0.30, 0.30))

        initial = self.bundle.factors.iloc[-1].to_numpy(dtype=float)
        weights = self._weights_array(mode)
        baseline_states = fcm_forecast(initial, weights, int(horizon))
        scenario_states = fcm_forecast(initial, weights, int(horizon), impulse_vector(impulses))
        baseline_rows = [self._scenario_row(step, state) for step, state in enumerate(baseline_states)]
        scenario_rows = [self._scenario_row(step, state) for step, state in enumerate(scenario_states)]

        final_base = baseline_rows[-1]
        final_scenario = scenario_rows[-1]
        sensitivity = self._sensitivity_cache if mode == "adapted" else self._build_sensitivity(mode)
        label_by_id = {spec.id: spec.label for spec in NODE_SPECS}
        explanations = []
        target_output_keys = {
            "traffic_safety": ("safety_index", "индекс безопасности", "п.п."),
            "transport_regularity": ("regularity", "регулярность", "п.п."),
            "accessibility": ("accessibility", "доступность", "п.п."),
        }
        for target_id, (output_key, target_label, unit) in target_output_keys.items():
            delta = float(final_scenario[output_key] - final_base[output_key])
            sensitivity_by_node = {item["node"]: item["delta_index_points"] for item in sensitivity[target_id]}
            contributions = [
                (node, float(value) / 0.07 * sensitivity_by_node.get(node, 0.0))
                for node, value in impulses.items()
            ]
            contributions.sort(key=lambda item: abs(item[1]), reverse=True)
            drivers = ", ".join(label_by_id[node] for node, _ in contributions[:3]) or "внешние воздействия отсутствуют"
            explanations.append(
                f"К концу горизонта {target_label} изменяется на {delta:+.2f} {unit} относительно инерционного расчёта. Основные факторы: {drivers}."
            )
        accident_delta = float(final_scenario["accidents"] - final_base["accidents"])
        explanations.insert(1, f"Фактический показатель ДТП изменяется на {accident_delta:+.2f} на 10 тыс. жителей; отрицательное значение означает улучшение.")

        return {
            "scenario": {"id": scenario_id, "label": SCENARIOS[scenario_id]["label"], "description": SCENARIOS[scenario_id]["description"]},
            "mode": mode,
            "horizon": int(horizon),
            "applied_impulses": [
                {"node": node, "label": label_by_id[node], "value": round(value, 4)} for node, value in impulses.items()
            ],
            "baseline": baseline_rows,
            "scenario_result": scenario_rows,
            "explanation": explanations,
        }

