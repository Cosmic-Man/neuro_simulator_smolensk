from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import DEFAULT_HORIZON, TEST_END, TRAIN_END, VALIDATION_END
from .data import DataBundle, NODE_IDS, NODE_SPECS, load_problem_b_data
from .fcm import EXPERT_EDGES, WeightSet, build_weight_set, fcm_forecast, fcm_step, graph_payload, impulse_vector, next_period
from .fuzzy import FUZZY_INDEX_SPECS
from .models import ANFISRegressor, RidgeRegressor, SampleSet, build_lag_samples, build_one_step_samples, metric_set, split_mask
from .scenarios import ScenarioStore


@dataclass(frozen=True)
class TargetConfig:
    id: str
    label: str
    unit: str
    raw_column: str
    factor_column: str
    anfis_features: tuple[str, ...]


TARGETS = {
    "traffic_safety": TargetConfig(
        "traffic_safety",
        "Индекс безопасности движения",
        "баллы из 100",
        "traffic_safety",
        "traffic_safety",
        ("road_condition", "defect_response", "crossings", "congestion"),
    ),
    "transport_regularity": TargetConfig(
        "transport_regularity",
        "Рейсы по расписанию",
        "%",
        "regularity",
        "transport_regularity",
        ("transit_budget_execution", "passenger_flow", "congestion", "road_wellbeing"),
    ),
    "transport_accessibility": TargetConfig(
        "transport_accessibility",
        "Индекс транспортной доступности",
        "баллы из 100",
        "accessibility",
        "transport_accessibility",
        ("road_condition", "transport_regularity", "congestion", "transport_environment"),
    ),
}

MODEL_LABELS = {
    "seasonal_naive": "Seasonal Naive",
    "ridge": "Ridge по четырём лагам",
    "fcm_expert": "FCM экспертная",
    "fcm_adapted": "FCM адаптированная",
    "anfis": "ANFIS",
}


class ProblemBService:
    def __init__(
        self,
        bundle: DataBundle | None = None,
        scenario_store: ScenarioStore | None = None,
    ):
        self.bundle = bundle or load_problem_b_data()
        self.scenario_store = scenario_store or ScenarioStore()
        self.ridge_models: dict[str, RidgeRegressor] = {}
        self.lag_samples: dict[str, SampleSet] = {}
        self.anfis_models: dict[str, ANFISRegressor] = {}
        self.anfis_samples: dict[str, SampleSet] = {}
        self.anfis_effects: dict[str, dict[str, float]] = {}
        self._train_models()
        self.weights: WeightSet = build_weight_set(self.bundle.factors, self.anfis_effects)
        self._prediction_cache = {target_id: self._prediction_lookups(target_id) for target_id in TARGETS}
        self._evaluation = self._build_evaluation()
        self._sensitivity_cache = self._build_sensitivity("adapted")

    def _train_models(self) -> None:
        for target_id, config in TARGETS.items():
            target_series = self.bundle.raw[config.raw_column]
            lag_samples = build_lag_samples(target_series)
            train = split_mask(lag_samples.periods, "train")
            ridge = RidgeRegressor(alpha=1.0).fit(lag_samples.x[train], lag_samples.y[train])
            self.lag_samples[target_id] = lag_samples
            self.ridge_models[target_id] = ridge

            model_frame = self.bundle.factors.copy()
            target_column = f"target__{target_id}"
            model_frame[target_column] = target_series
            anfis_samples = build_one_step_samples(model_frame, config.anfis_features, target_column)
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
        if target_id == "transport_regularity":
            return np.clip(values, 0.0, 100.0)
        return np.clip(values, 0.0, 100.0)

    def _factor_target_to_raw(self, target_id: str, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        if target_id == "transport_regularity":
            return self.bundle.scalers["regularity"].inverse(values)
        if target_id in {"traffic_safety", "transport_accessibility"}:
            return values * 100.0
        raise ValueError(f"Неизвестная цель: {target_id}")

    def _fcm_prediction_lookup(self, target_id: str, mode: str) -> dict[str, float]:
        matrix = self.weights.expert if mode == "expert" else self.weights.adapted
        target_index = NODE_IDS.index(TARGETS[target_id].factor_column)
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

    def _evaluate_target(
        self,
        target_id: str,
        label: str,
        unit: str,
        actual_series: pd.Series,
        lookups: Mapping[str, Mapping[str, float]],
    ) -> dict[str, Any]:
        train_values = actual_series.loc[:TRAIN_END].to_numpy(dtype=float)
        metrics_rows: list[dict[str, Any]] = []
        predictions: dict[str, list[dict[str, Any]]] = {}
        periods = actual_series.index.to_numpy(dtype=str)
        for split in ("validation", "test"):
            selected_periods = periods[split_mask(periods, split)]
            actual = actual_series.loc[selected_periods].to_numpy(dtype=float)
            previous = np.asarray(
                [actual_series.iloc[actual_series.index.get_loc(period) - 1] for period in selected_periods],
                dtype=float,
            )
            split_rows: list[dict[str, Any]] = []
            for index, period in enumerate(selected_periods):
                row: dict[str, Any] = {"period": period, "actual": round(float(actual[index]), 5)}
                for model_id, lookup in lookups.items():
                    row[model_id] = round(float(lookup[period]), 5)
                split_rows.append(row)
            predictions[split] = split_rows
            for model_id, lookup in lookups.items():
                predicted = np.asarray([lookup[period] for period in selected_periods], dtype=float)
                metrics = metric_set(actual, predicted, train_values, previous)
                metrics_rows.append(
                    {
                        "model": model_id,
                        "model_label": MODEL_LABELS[model_id],
                        "split": split,
                        **{name: round(value, 6) for name, value in metrics.items()},
                    }
                )
        return {"id": target_id, "label": label, "unit": unit, "metrics": metrics_rows, "predictions": predictions}

    def _integrated_lookups(self) -> dict[str, dict[str, float]]:
        periods = self.bundle.raw.index.to_list()[4:]
        output: dict[str, dict[str, float]] = {model: {} for model in MODEL_LABELS}
        regularity_scaler = self.bundle.scalers["regularity"]
        for model in MODEL_LABELS:
            for period in periods:
                safety = self._prediction_cache["traffic_safety"][model].get(period)
                regularity = self._prediction_cache["transport_regularity"][model].get(period)
                accessibility = self._prediction_cache["transport_accessibility"][model].get(period)
                if safety is None or regularity is None or accessibility is None:
                    continue
                regularity_factor = float(regularity_scaler.transform(np.asarray([regularity]))[0])
                output[model][period] = float((safety / 100.0 + regularity_factor + accessibility / 100.0) / 3.0 * 100.0)
        return output

    def _build_evaluation(self) -> dict[str, Any]:
        targets = [
            self._evaluate_target(
                target_id,
                config.label,
                config.unit,
                self.bundle.raw[config.raw_column],
                self._prediction_cache[target_id],
            )
            for target_id, config in TARGETS.items()
        ]
        targets.append(
            self._evaluate_target(
                "integrated_mobility",
                "Итоговый индекс безопасности и мобильности",
                "баллы из 100",
                self.bundle.raw["integrated_mobility"],
                self._integrated_lookups(),
            )
        )
        return {
            "targets": targets,
            "model_labels": MODEL_LABELS,
            "note": "Обучение: 2006Q1–2018Q4; настройка ANFIS: 2019Q1–2022Q4; test 2023Q1–2025Q4 не используется при настройке.",
        }

    def metadata(self) -> dict[str, Any]:
        anfis = [
            {
                "target": target_id,
                "inputs": model.feature_names,
                "rule_count": model.rule_count,
                "sigma": model.sigma_,
                "ridge": model.ridge_,
                "validation_rmse": model.validation_rmse_,
            }
            for target_id, model in self.anfis_models.items()
        ]
        return {
            "project": "Транспортная доступность и безопасность городской мобильности Смоленска",
            "problem": "Б",
            "source": self.bundle.source_path.name,
            "dataset": {"rows": len(self.bundle.features), "features": len(self.bundle.features.columns), "sheet": "Лист1", "header_rows": 2},
            "features": self.bundle.feature_metadata,
            "period": {"start": self.bundle.raw.index[0], "end": TEST_END, "quarters": len(self.bundle.raw)},
            "splits": {
                "train": {"start": self.bundle.raw.index[0], "end": TRAIN_END, "quarters": 52},
                "validation": {"start": "2019Q1", "end": VALIDATION_END, "quarters": 16},
                "test": {"start": "2023Q1", "end": TEST_END, "quarters": 12},
            },
            "fcm": {"nodes": len(NODE_IDS), "edges": len(EXPERT_EDGES), "alpha": 0.35, "lambda": 1.3, "blend": "0.70 × expert + 0.30 × data"},
            "nodes": [spec.__dict__ for spec in NODE_SPECS],
            "targets": [config.__dict__ for config in TARGETS.values()] + [{"id": "integrated_mobility", "label": "Итоговый индекс безопасности и мобильности", "unit": "баллы из 100"}],
            "scenarios": self.scenario_store.list(),
            "fuzzy_indices": [{"id": spec.id, "label": spec.label, "rules": len(spec.rule_table)} for spec in FUZZY_INDEX_SPECS],
            "anfis": anfis,
            "proxies": [{"id": "digital_mobility", "description": "Прямого ряда цифровизации нет; сценарий воздействует на регулярность, скорость и загруженность."}],
        }

    def history(self) -> dict[str, Any]:
        periods = self.bundle.raw.index.to_list()
        split = ["train" if period <= TRAIN_END else "validation" if period <= VALIDATION_END else "test" for period in periods]
        definitions = [
            ("traffic_safety", "Безопасность движения", "баллы", "target"),
            ("accidents", "ДТП на 10 тыс. жителей", "ДТП на 10 тыс.", "indicator"),
            ("regularity", "Рейсы по расписанию", "%", "target"),
            ("accessibility", "Транспортная доступность", "баллы", "target"),
            ("integrated_mobility", "Итоговый индекс мобильности", "баллы", "target"),
            ("linear_expert_index", "Линейный экспертный индекс", "баллы", "baseline"),
            ("hierarchical_fuzzy_index", "Иерархический экспертный индекс Гульдар", "баллы", "baseline"),
            ("avg_speed", "Средняя скорость", "км/ч", "indicator"),
            ("road_condition", "Дороги в нормативном состоянии", "%", "indicator"),
            ("road_repair", "Отремонтированные дороги", "км", "control"),
            ("crossings", "Регулируемые переходы", "ед.", "control"),
            ("passenger_flow", "Пассажиропоток", "тыс. поездок", "indicator"),
        ]
        definitions += [(spec.id, spec.label, "баллы", "fuzzy") for spec in FUZZY_INDEX_SPECS]
        series = [
            {"id": series_id, "label": label, "unit": unit, "role": role, "values": [round(float(value), 5) for value in self.bundle.raw[series_id]]}
            for series_id, label, unit, role in definitions
        ]
        latest = {
            key: round(float(self.bundle.raw.iloc[-1][key]), 2)
            for key in (
                "accidents",
                "regularity",
                "accessibility",
                "traffic_safety",
                "integrated_mobility",
                "linear_expert_index",
                "hierarchical_fuzzy_index",
            )
        }
        latest["period"] = periods[-1]
        return {"periods": periods, "split": split, "series": series, "latest": latest}

    def indices(self) -> dict[str, Any]:
        latest_contributions = self.bundle.linear_contributions.iloc[-1].drop("linear_expert_index")
        top = latest_contributions.sort_values(ascending=False).head(10)
        label_by_id = {item["id"]: item["label"] for item in self.bundle.feature_metadata}
        fuzzy_label_by_id = {spec.id: spec.label for spec in FUZZY_INDEX_SPECS}
        hierarchical_contributions = self.bundle.hierarchical_contributions.iloc[-1].drop("hierarchical_fuzzy_index")
        hierarchical = self.bundle.raw["hierarchical_fuzzy_index"]
        return {
            "periods": self.bundle.raw.index.to_list(),
            "fuzzy": [
                {"id": spec.id, "label": spec.label, "values": [round(float(value), 5) for value in self.bundle.fuzzy_indices[spec.id]]}
                for spec in FUZZY_INDEX_SPECS
            ],
            "linear": [round(float(value), 5) for value in self.bundle.raw["linear_expert_index"]],
            "hierarchical": [round(float(value), 5) for value in hierarchical],
            "hierarchical_stats": {
                "minimum": round(float(hierarchical.min()), 5),
                "maximum": round(float(hierarchical.max()), 5),
                "mean": round(float(hierarchical.mean()), 5),
                "median": round(float(hierarchical.median()), 5),
                "std": round(float(hierarchical.std()), 5),
                "latest": round(float(hierarchical.iloc[-1]), 5),
            },
            "top_contributions": [
                {"feature": feature, "label": label_by_id.get(feature, feature), "value": round(float(value), 6)}
                for feature, value in top.items()
            ],
            "weights": self.bundle.linear_model.weights_table(label_by_id).to_dict(orient="records"),
            "hierarchical_contributions": [
                {
                    "feature": feature,
                    "label": fuzzy_label_by_id.get(feature, feature),
                    "value": round(float(value), 6),
                }
                for feature, value in hierarchical_contributions.sort_values(ascending=False).items()
            ],
            "hierarchical_weights": self.bundle.hierarchical_model.weights_table(fuzzy_label_by_id).to_dict(orient="records"),
        }

    def fcm(self, mode: str) -> dict[str, object]:
        return graph_payload(self.weights, mode)

    def evaluation(self) -> dict[str, Any]:
        return {**self._evaluation, "sensitivity": self._sensitivity_cache}

    def scenarios(self) -> list[dict[str, Any]]:
        return self.scenario_store.list()

    def save_scenario(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.scenario_store.save(payload)

    def _weights_array(self, mode: str) -> np.ndarray:
        if mode == "expert":
            return self.weights.expert.to_numpy(dtype=float)
        if mode == "adapted":
            return self.weights.adapted.to_numpy(dtype=float)
        raise ValueError("Режим FCM должен быть expert или adapted")

    def _scenario_row(self, step: int, state: np.ndarray) -> dict[str, Any]:
        safety = float(state[NODE_IDS.index("traffic_safety")])
        regularity_factor = float(state[NODE_IDS.index("transport_regularity")])
        accessibility = float(state[NODE_IDS.index("transport_accessibility")])
        regularity = float(self.bundle.scalers["regularity"].inverse(np.asarray([regularity_factor]))[0])
        accidents = float(self.bundle.scalers["accidents"].inverse(np.asarray([safety]))[0])
        integrated = (safety + regularity_factor + accessibility) / 3.0 * 100.0
        return {
            "step": step,
            "period": self.bundle.raw.index[-1] if step == 0 else next_period(self.bundle.raw.index[-1], step),
            "safety_index": round(safety * 100.0, 4),
            "accidents": round(accidents, 4),
            "regularity": round(regularity, 4),
            "accessibility": round(accessibility * 100.0, 4),
            "integrated_mobility": round(integrated, 4),
        }

    def _target_state_value(self, target_id: str, state: np.ndarray) -> float:
        if target_id == "integrated_mobility":
            return float(np.mean([state[NODE_IDS.index(name)] for name in ("traffic_safety", "transport_regularity", "transport_accessibility")]))
        factor_name = TARGETS[target_id].factor_column
        return float(state[NODE_IDS.index(factor_name)])

    def _build_sensitivity(self, mode: str, horizon: int = DEFAULT_HORIZON) -> dict[str, list[dict[str, Any]]]:
        initial = self.bundle.factors.iloc[-1].to_numpy(dtype=float)
        weights = self._weights_array(mode)
        baseline = fcm_forecast(initial, weights, horizon)[-1]
        adjustable = [spec for spec in NODE_SPECS if spec.adjustable and spec.kind != "target"]
        target_ids = [*TARGETS, "integrated_mobility"]
        output: dict[str, list[dict[str, Any]]] = {target: [] for target in target_ids}
        for spec in adjustable:
            perturbed = fcm_forecast(initial, weights, horizon, impulse_vector({spec.id: 0.07}))[-1]
            for target_id in target_ids:
                delta = self._target_state_value(target_id, perturbed) - self._target_state_value(target_id, baseline)
                output[target_id].append({"node": spec.id, "label": spec.label, "delta_index_points": round(delta * 100.0, 5)})
        for target_id in output:
            output[target_id].sort(key=lambda item: abs(item["delta_index_points"]), reverse=True)
        return output

    def simulate(
        self,
        scenario_id: str,
        mode: str | None = None,
        horizon: int | None = None,
        custom_impulses: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        scenario = self.scenario_store.get(scenario_id)
        selected_mode = mode or str(scenario["mode"])
        selected_horizon = int(horizon if horizon is not None else scenario["horizon"])
        if not 1 <= selected_horizon <= 20:
            raise ValueError("Горизонт должен составлять от 1 до 20 кварталов")
        impulses = {key: float(value) for key, value in scenario["impulses"].items()}
        adjustable = {spec.id for spec in NODE_SPECS if spec.adjustable}
        for key, value in (custom_impulses or {}).items():
            if key not in adjustable:
                raise ValueError(f"Узел {key} нельзя изменять")
            numeric = float(value)
            if not -0.30 <= numeric <= 0.30:
                raise ValueError(f"Воздействие на {key} должно быть в диапазоне [-0.30, 0.30]")
            impulses[key] = float(np.clip(impulses.get(key, 0.0) + numeric, -0.30, 0.30))

        initial = self.bundle.factors.iloc[-1].to_numpy(dtype=float)
        weights = self._weights_array(selected_mode)
        baseline_states = fcm_forecast(initial, weights, selected_horizon)
        scenario_states = fcm_forecast(initial, weights, selected_horizon, impulse_vector(impulses))
        baseline_rows = [self._scenario_row(step, state) for step, state in enumerate(baseline_states)]
        scenario_rows = [self._scenario_row(step, state) for step, state in enumerate(scenario_states)]

        final_base, final_scenario = baseline_rows[-1], scenario_rows[-1]
        label_by_id = {spec.id: spec.label for spec in NODE_SPECS}
        keys = (
            ("safety_index", "безопасность", "п.п."),
            ("regularity", "регулярность", "п.п."),
            ("accessibility", "доступность", "п.п."),
            ("integrated_mobility", "итоговый индекс", "п.п."),
        )
        explanations: list[str] = []
        sensitivity = self._sensitivity_cache if selected_mode == "adapted" else self._build_sensitivity(selected_mode)
        target_map = {"safety_index": "traffic_safety", "regularity": "transport_regularity", "accessibility": "transport_accessibility", "integrated_mobility": "integrated_mobility"}
        for output_key, label, unit in keys:
            delta = float(final_scenario[output_key] - final_base[output_key])
            sensitivity_by_node = {item["node"]: item["delta_index_points"] for item in sensitivity[target_map[output_key]]}
            drivers = sorted(
                ((node, float(value) / 0.07 * sensitivity_by_node.get(node, 0.0)) for node, value in impulses.items()),
                key=lambda item: abs(item[1]),
                reverse=True,
            )
            names = ", ".join(label_by_id[node] for node, _ in drivers[:3]) or "внешние воздействия отсутствуют"
            explanations.append(f"К концу горизонта {label} меняется на {delta:+.2f} {unit}. Основные факторы: {names}.")
        accident_delta = float(final_scenario["accidents"] - final_base["accidents"])
        explanations.insert(1, f"Расчётный показатель ДТП меняется на {accident_delta:+.2f} на 10 тыс. жителей; отрицательное изменение означает улучшение.")

        return {
            "scenario": {"id": scenario_id, "label": scenario["label"], "description": scenario["description"], "builtin": scenario["builtin"]},
            "mode": selected_mode,
            "horizon": selected_horizon,
            "applied_impulses": [{"node": node, "label": label_by_id[node], "value": round(value, 4)} for node, value in impulses.items()],
            "baseline": baseline_rows,
            "scenario_result": scenario_rows,
            "explanation": explanations,
        }
