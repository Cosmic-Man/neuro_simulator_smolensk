from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .config import ANFIS_MODEL_DIR, DEFAULT_HORIZON, IMPULSE_LIMIT, TEST_END, TRAIN_END, VALIDATION_END
from .data import DataBundle, FEATURE_DIRECTIONS, NODE_IDS, NODE_SPECS, load_problem_b_data
from .fcm import EXPERT_EDGES, WeightSet, build_weight_set, fcm_forecast, fcm_step, graph_payload, impulse_vector, next_period
from .fuzzy import FUZZY_INDEX_SPECS
from .models import (
    ANFIS,
    ModelArtifactError,
    PipelineANFIS,
    RidgeRegressor,
    RobustScaler,
    SampleSet,
    build_lag_samples,
    build_one_step_samples,
    metric_set,
    split_mask,
    smape,
)
from .scenarios import builtin_items, get_builtin, validate_scenario


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
    "seasonal_naive": "Seasonal Naive — сезонный повтор",
    "ridge": "Ridge Regression — лаговые признаки",
    "anfis": "ANFIS — 8 нечётких правил",
}

MODEL_CATALOG = {
    "seasonal_naive": {
        "role": "Простой сезонный baseline",
        "how": "Прогноз следующего квартала равен фактическому значению того же квартала год назад.",
        "inputs": "Только целевой показатель с лагом 4 квартала; городские факторы не используются.",
        "purpose": "Минимальный ориентир: сложная модель должна быть полезнее простого повторения прошлого года.",
    },
    "ridge": {
        "role": "Линейный статистический baseline",
        "how": "Использует лаги 1, 2 и 4 квартала и среднее за четыре предыдущих квартала.",
        "inputs": "Нормализованный итоговый индекс Pipeline; коэффициенты обучаются только на train.",
        "purpose": "Показывает качество линейной модели временного ряда до применения ANFIS.",
    },
    "anfis": {
        "role": "Основная модель Pipeline",
        "how": "Объединяет восемь гауссовых правил Сугено и линейные выводы правил; параметры обучаются Adam.",
        "inputs": "Шесть индексов Pipeline квартала t после объединения показателей ДТК и ГОТ и RobustScaler; целевая переменная — итоговый индекс квартала t+1.",
        "purpose": "Прогнозирует следующий квартал без использования его показателей и сравнивается с двумя временными baseline.",
    },
}

NODE_ACTIONS = {
    "road_budget_execution": "Повысить фактическое исполнение дорожной программы и перенести средства на готовые к реализации работы.",
    "transit_budget_execution": "Ускорить финансирование перевозчиков, выпуска транспорта и диспетчерского управления.",
    "safety_budget_execution": "Направить ресурсы на парковки, разметку, освещение и мероприятия безопасности движения.",
    "road_repair": "Увеличить объём ремонта на участках, которые сильнее всего ограничивают движение и безопасность.",
    "road_condition": "Приоритизировать доведение дорог до нормативного состояния, а не только локальный ремонт.",
    "defect_response": "Сократить срок обнаружения и устранения дефектов через норматив реакции и контроль исполнения.",
    "passenger_flow": "Поддержать востребованные маршруты и пересадки, чтобы рост пассажиропотока был устойчивым.",
    "transport_regularity": "Стабилизировать интервалы и соблюдение расписания на проблемных маршрутах.",
    "average_speed": "Убрать задержки на узких местах, настроить приоритет и координацию движения.",
    "crossings": "Улучшить регулируемые переходы, освещение и организацию конфликтных точек.",
    "congestion": "Снизить перегрузку сети управлением потоками, парковкой и маршрутами объезда.",
}

INDEX_CONTROL_NODES = {
    "urban_environment": "transport_environment",
    "road_quality_dtc": "road_condition",
    "accessible_environment": "transport_accessibility",
    "public_spaces": "crossings",
    "road_quality_transit": "transport_regularity",
    "parking_safety": "traffic_safety",
}

FUZZY_FEATURE_PRIORITY = {
    "road_quality_dtc": (
        "дороги_отремонт_км_A", "рейсы_расписание_pct_A", "скорость_магистрали_A_кмч",
        "дтп_10тыс_A", "срок_устранения_деф_сут_A",
    ),
    "road_quality_transit": (
        "дороги_отремонт_км_B", "рейсы_расписание_pct_B", "скорость_магистрали_B_кмч",
        "дтп_10тыс_B", "срок_устранения_деф_сут_B",
    ),
}

FUZZY_ADJACENT_NODES = {
    "urban_environment": ("road_condition", "crossings"),
    "road_wellbeing_dtc": ("road_repair", "defect_response"),
    "accessible_environment": ("transport_regularity", "crossings"),
    "public_spaces": ("crossings", "road_condition"),
    "road_wellbeing_transit": ("road_repair", "defect_response"),
    "parking_safety": ("crossings",),
}

FUZZY_RELATED_TARGET = {
    "urban_environment": "integrated_mobility",
    "road_quality_dtc": "traffic_safety",
    "road_wellbeing_dtc": "transport_accessibility",
    "accessible_environment": "transport_accessibility",
    "public_spaces": "integrated_mobility",
    "road_quality_transit": "transport_regularity",
    "road_wellbeing_transit": "transport_regularity",
    "parking_safety": "traffic_safety",
}


class ProblemBService:
    def __init__(
        self,
        bundle: DataBundle | None = None,
        model_dir: Path | str | None = None,
        *,
        force_retrain: bool = False,
    ):
        self.bundle = bundle or load_problem_b_data()
        self.model_dir = Path(model_dir) if model_dir is not None else ANFIS_MODEL_DIR
        self.force_retrain = force_retrain
        self.trained_at = datetime.now(timezone.utc)
        self.source_fingerprint = self._file_fingerprint(self.bundle.source_path)
        self.ridge_models: dict[str, RidgeRegressor] = {}
        self.lag_samples: dict[str, SampleSet] = {}
        self.anfis_models: dict[str, ANFIS] = {}
        self.anfis_model_sources: dict[str, str] = {}
        self.anfis_samples: dict[str, SampleSet] = {}
        self.anfis_effects: dict[str, dict[str, float]] = {}
        self._train_models()
        self.weights: WeightSet = build_weight_set(self.bundle.factors, self.anfis_effects)
        self._prediction_cache = {target_id: self._prediction_lookups(target_id) for target_id in TARGETS}
        self._evaluation = self._build_pipeline_evaluation()
        self._sensitivity_cache = self._build_sensitivity("adapted")
        self._recommendations_cache = self._build_improvement_recommendations()

    @staticmethod
    def _file_fingerprint(path: Path | str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _operational_windows(samples: SampleSet) -> tuple[np.ndarray, np.ndarray]:
        """Отделяет короткое окно для выбора гиперпараметров до финального обучения на всех строках."""
        calibration_size = min(8, max(4, len(samples.y) // 10))
        split = len(samples.y) - calibration_size
        if split < 8:
            raise ValueError("Недостаточно кварталов для переобучения рабочей модели")
        return np.arange(split), np.arange(split, len(samples.y))

    def _fit_operational_anfis(self, target_id: str, config: TargetConfig, samples: SampleSet) -> ANFIS:
        tuning_rows, calibration_rows = self._operational_windows(samples)
        template = ANFIS(config.anfis_features)
        signature = template.training_signature(
            samples.x,
            samples.y,
            samples.x[calibration_rows],
            samples.y[calibration_rows],
            context=f"{target_id}:operational-full-history-v1",
        )
        artifact_path = self.model_dir / f"anfis_{target_id}.npz"
        if not self.force_retrain:
            try:
                model = ANFIS.load(
                    artifact_path,
                    expected_features=config.anfis_features,
                    expected_training_signature=signature,
                )
                self.anfis_model_sources[target_id] = "artifact"
                return model
            except ModelArtifactError:
                pass

        tuned = template.fit(
            samples.x[tuning_rows],
            samples.y[tuning_rows],
            samples.x[calibration_rows],
            samples.y[calibration_rows],
        )
        validation_rmse = tuned.validation_rmse_
        model = ANFIS(
            config.anfis_features,
            sigma_candidates=(float(tuned.sigma_),),
            ridge_candidates=(float(tuned.ridge_),),
        ).fit(
            samples.x,
            samples.y,
            samples.x[calibration_rows],
            samples.y[calibration_rows],
        )
        # Показываем честную ошибку окна настройки, а не ошибку повторного прогона
        # по строкам, которые уже вошли в финальную рабочую модель.
        model.validation_rmse_ = validation_rmse
        try:
            model.save(artifact_path, training_signature=signature)
            source = "trained_and_cached"
        except OSError:
            source = "trained_in_memory"
        self.anfis_model_sources[target_id] = source
        return model

    def _train_models(self) -> None:
        for target_id, config in TARGETS.items():
            target_series = self.bundle.raw[config.raw_column]
            lag_samples = build_lag_samples(target_series)
            ridge = RidgeRegressor(alpha=1.0).fit(lag_samples.x, lag_samples.y)
            self.lag_samples[target_id] = lag_samples
            self.ridge_models[target_id] = ridge

            model_frame = self.bundle.factors.copy()
            target_column = f"target__{target_id}"
            model_frame[target_column] = target_series
            anfis_samples = build_one_step_samples(model_frame, config.anfis_features, target_column)
            anfis = self._fit_operational_anfis(target_id, config, anfis_samples)
            self.anfis_models[target_id] = anfis
            self.anfis_samples[target_id] = anfis_samples
            recent_rows = min(8, len(anfis_samples.x))
            self.anfis_effects[target_id] = anfis.feature_effects(anfis_samples.x[-recent_rows:])

    def training_status(self, current_path: Path | str | None = None) -> dict[str, Any]:
        current_fingerprint = self._file_fingerprint(current_path or self.bundle.source_path)
        latest_period = str(self.bundle.raw.index[-1])
        return {
            "dataset": self.bundle.source_path.name,
            "trained_at": self.trained_at.isoformat(),
            "trained_through": latest_period,
            "source_rows": len(self.bundle.source_features),
            "processed_rows": len(self.bundle.features),
            "training_samples": min(len(samples.y) for samples in self.anfis_samples.values()),
            "new_quarters": sum(str(period) > TEST_END for period in self.bundle.raw.index),
            "models": len(self.anfis_models),
            "pending_retrain": current_fingerprint != self.source_fingerprint,
            "strategy": "Рабочие ANFIS и веса FCM обучены на всех подтверждённых кварталах; контрольные выборки notebook сохранены отдельно.",
        }

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

    @staticmethod
    def _pipeline_metric_set(
        actual: np.ndarray,
        predicted: np.ndarray,
        train_values: np.ndarray,
        previous: np.ndarray,
        *,
        mase_period: int,
    ) -> dict[str, float]:
        errors = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)
        scale = float(np.mean(np.abs(train_values[mase_period:] - train_values[:-mase_period])))
        if scale < 1e-12:
            scale = 1.0
        return {
            "mae": float(np.mean(np.abs(errors))),
            "rmse": float(np.sqrt(np.mean(errors**2))),
            "smape": smape(np.asarray(actual), np.asarray(predicted)),
            "mase": float(np.mean(np.abs(errors)) / scale),
            "directional_accuracy": float(
                np.mean(np.sign(np.asarray(actual) - previous) == np.sign(np.asarray(predicted) - previous))
            ),
        }

    def _build_pipeline_evaluation(self) -> dict[str, Any]:
        feature_names = [
            "urban_environment",
            "road_quality_dtc",
            "accessible_environment",
            "public_spaces",
            "road_quality_transit",
            "parking_safety",
        ]
        all_periods = self.bundle.fuzzy_indices.index.to_numpy(dtype=str)
        fuzzy = self.bundle.fuzzy_indices
        pipeline_inputs = pd.DataFrame(
            {
                "urban_environment": fuzzy["urban_environment"],
                "road_quality_dtc": (
                    0.7 * fuzzy["road_wellbeing_dtc"] + 0.6 * fuzzy["road_quality_dtc"]
                ) / 100.0,
                "accessible_environment": fuzzy["accessible_environment"],
                "public_spaces": fuzzy["public_spaces"],
                "road_quality_transit": (
                    0.9 * fuzzy["road_wellbeing_transit"] + 0.7 * fuzzy["road_quality_transit"]
                ) / 100.0,
                "parking_safety": fuzzy["parking_safety"],
            },
            index=fuzzy.index,
        )
        self.pipeline_display_inputs = pd.DataFrame(
            {
                "urban_environment": fuzzy["urban_environment"],
                "road_quality_dtc": (
                    0.7 * fuzzy["road_wellbeing_dtc"] + 0.6 * fuzzy["road_quality_dtc"]
                ) / 1.3,
                "accessible_environment": fuzzy["accessible_environment"],
                "public_spaces": fuzzy["public_spaces"],
                "road_quality_transit": (
                    0.9 * fuzzy["road_wellbeing_transit"] + 0.7 * fuzzy["road_quality_transit"]
                ) / 1.6,
                "parking_safety": fuzzy["parking_safety"],
            },
            index=fuzzy.index,
        )
        all_x_raw = pipeline_inputs.loc[:, feature_names].to_numpy(dtype=float)
        all_y_raw = self.bundle.raw["pipeline_target"].to_numpy(dtype=float)

        # Прогноз на один квартал: JSON-индексы периода t предсказывают target t+1.
        # Маски относятся к периоду цели, поэтому будущие строки не входят в train.
        input_periods = all_periods[:-1]
        periods = all_periods[1:]
        x_raw = all_x_raw[:-1]
        y_raw = all_y_raw[1:]
        previous_raw = all_y_raw[:-1]
        train_mask = periods <= TRAIN_END
        validation_mask = (periods >= "2019Q1") & (periods <= VALIDATION_END)

        self.pipeline_x_scaler = RobustScaler().fit(x_raw[train_mask])
        self.pipeline_y_scaler = RobustScaler().fit(y_raw[train_mask, None])
        x_scaled = self.pipeline_x_scaler.transform(x_raw)
        y_scaled = self.pipeline_y_scaler.transform(y_raw[:, None]).reshape(-1)
        previous_scaled = self.pipeline_y_scaler.transform(previous_raw[:, None]).reshape(-1)
        self.pipeline_anfis = PipelineANFIS(feature_names).fit(
            x_scaled[train_mask],
            y_scaled[train_mask],
            x_scaled[validation_mask],
            y_scaled[validation_mask],
        )
        anfis_prediction = self.pipeline_anfis.predict(x_scaled)

        # Baseline используют только значения target, известные до целевого квартала.
        all_y_scaled = self.pipeline_y_scaler.transform(all_y_raw[:, None]).reshape(-1)
        lagged = np.full((len(all_y_scaled), 4), np.nan, dtype=float)
        for index in range(4, len(all_y_scaled)):
            lagged[index] = (
                all_y_scaled[index - 1],
                all_y_scaled[index - 2],
                all_y_scaled[index - 4],
                float(np.mean(all_y_scaled[index - 4:index])),
            )
        ridge_train = (all_periods <= TRAIN_END) & np.isfinite(lagged).all(axis=1)
        ridge_x = lagged[ridge_train]
        ridge_y = all_y_scaled[ridge_train]
        ridge_x_mean = ridge_x.mean(axis=0)
        ridge_y_mean = float(ridge_y.mean())
        ridge_centered = ridge_x - ridge_x_mean
        ridge_coef = np.linalg.solve(
            ridge_centered.T @ ridge_centered + np.eye(ridge_centered.shape[1]),
            ridge_centered.T @ (ridge_y - ridge_y_mean),
        )
        ridge_prediction = np.full(len(all_y_scaled), np.nan, dtype=float)
        valid_lags = np.isfinite(lagged).all(axis=1)
        ridge_prediction[valid_lags] = (
            ridge_y_mean + (lagged[valid_lags] - ridge_x_mean) @ ridge_coef
        )

        prediction_rows: dict[str, list[dict[str, Any]]] = {}
        metric_rows: list[dict[str, Any]] = []
        train_values = y_scaled[train_mask]
        for split in ("validation", "test"):
            mask = split_mask(periods, split)
            selected = np.flatnonzero(mask)
            target_indexes = selected + 1
            seasonal_values = all_y_scaled[target_indexes - 4]
            predictions_by_model = {
                "seasonal_naive": np.asarray(seasonal_values),
                "ridge": ridge_prediction[target_indexes],
                "anfis": anfis_prediction[mask],
            }
            rows = []
            for position, index in enumerate(selected):
                rows.append(
                    {
                        "period": periods[index],
                        "input_period": input_periods[index],
                        "actual": round(float(y_scaled[index]), 6),
                        **{
                            model: round(float(values[position]), 6)
                            for model, values in predictions_by_model.items()
                        },
                    }
                )
            prediction_rows[split] = rows
            actual = y_scaled[mask]
            previous = previous_scaled[mask]
            for model, values in predictions_by_model.items():
                metrics = self._pipeline_metric_set(
                    actual,
                    values,
                    ridge_y if model == "ridge" else train_values,
                    previous,
                    mase_period=4 if model == "seasonal_naive" else 1,
                )
                metric_rows.append(
                    {
                        "model": model,
                        "model_label": MODEL_LABELS[model],
                        "split": split,
                        **{name: round(value, 6) for name, value in metrics.items()},
                    }
                )

        target = {
            "id": "pipeline_target",
            "label": "Итоговый индекс Pipeline",
            "unit": "нормализованное значение",
            "metrics": metric_rows,
            "predictions": prediction_rows,
        }
        return {
            "targets": [target],
            "sensitivity_targets": [
                {"id": target_id, "label": config.label}
                for target_id, config in TARGETS.items()
            ] + [{"id": "integrated_mobility", "label": "Итоговый индекс безопасности и мобильности"}],
            "model_labels": MODEL_LABELS,
            "model_catalog": [
                {"id": model_id, "label": label, **MODEL_CATALOG[model_id]}
                for model_id, label in MODEL_LABELS.items()
            ],
            "note": (
                "Прогноз без утечки: шесть индексов Pipeline квартала t предсказывают target квартала t+1. "
                "Train заканчивается целью 2018Q4, validation — 2019–2022, test — 2023–2025. "
                "RobustScaler обучается только на train; test не используется при обучении и настройке ANFIS."
            ),
        }

    def simulate_pipeline_index(
        self,
        index_values: Mapping[str, float] | None = None,
        *,
        horizon: int = DEFAULT_HORIZON,
    ) -> dict[str, Any]:
        """Прогнозирует итоговый индекс t+1 по шести входам Pipeline."""
        horizon = int(horizon)
        if not 1 <= horizon <= 20:
            raise ValueError("Горизонт должен составлять от 1 до 20 кварталов")
        labels = {
            "urban_environment": "Индекс качества современной городской среды",
            "road_quality_dtc": "Индекс качества ДТК",
            "accessible_environment": "Индекс удовлетворённости доступной среды",
            "public_spaces": "Индекс качества общественного благоустройства",
            "road_quality_transit": "Индекс качества ГОТ",
            "parking_safety": "Индекс качества парковок и безопасности движения",
        }
        baseline = {key: float(value) for key, value in self.pipeline_display_inputs.iloc[-1].items()}
        supplied = dict(index_values or {})
        unknown = set(supplied) - set(labels)
        if unknown:
            raise ValueError(f"Неизвестные индексы Pipeline: {sorted(unknown)}")
        scenario = baseline.copy()
        for key, value in supplied.items():
            numeric = float(value)
            if not np.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
                raise ValueError(f"Значение индекса {key} должно быть в диапазоне [0, 100]")
            scenario[key] = numeric

        def model_row(values: Mapping[str, float]) -> np.ndarray:
            return np.asarray([[
                values["urban_environment"],
                values["road_quality_dtc"] * 1.3 / 100.0,
                values["accessible_environment"],
                values["public_spaces"],
                values["road_quality_transit"] * 1.6 / 100.0,
                values["parking_safety"],
            ]], dtype=float)

        def predict(values: Mapping[str, float]) -> float:
            scaled = self.pipeline_x_scaler.transform(model_row(values))
            predicted_scaled = self.pipeline_anfis.predict(scaled).reshape(-1, 1)
            predicted = float(self.pipeline_y_scaler.inverse_transform(predicted_scaled)[0, 0])
            return float(np.clip(predicted, 0.0, 100.0))

        baseline_prediction = predict(baseline)
        current_period = str(self.bundle.raw.index[-1])
        forecast_rows = []
        period = current_period
        for step in range(1, horizon + 1):
            progress = step / horizon
            step_values = {
                key: baseline[key] + (scenario[key] - baseline[key]) * progress
                for key in labels
            }
            period = next_period(period)
            forecast_rows.append({
                "step": step,
                "period": period,
                "baseline": round(baseline_prediction, 5),
                "scenario": round(predict(step_values), 5),
            })
        scenario_prediction = float(forecast_rows[-1]["scenario"])
        delta = scenario_prediction - baseline_prediction
        relative = None if abs(baseline_prediction) < 1e-12 else delta / abs(baseline_prediction) * 100.0

        if scenario_prediction <= 20:
            level = {"label": "Критический", "tone": "critical", "explanation": "Нужен срочный план восстановления сразу по нескольким направлениям."}
        elif scenario_prediction <= 40:
            level = {"label": "Низкий", "tone": "low", "explanation": "Сначала устраните наиболее слабые ограничения городской и транспортной среды."}
        elif scenario_prediction <= 60:
            level = {"label": "Удовлетворительный", "tone": "medium", "explanation": "Система работоспособна, но слабые индексы заметно ограничивают итоговый результат."}
        elif scenario_prediction <= 80:
            level = {"label": "Хороший", "tone": "good", "explanation": "Сосредоточьтесь на двух–трёх отстающих направлениях, чтобы закрепить рост."}
        elif scenario_prediction <= 95:
            level = {"label": "Отличный", "tone": "excellent", "explanation": "Поддерживайте достигнутый уровень и точечно улучшайте самый слабый индекс."}
        else:
            level = {"label": "Превосходный", "tone": "excellent", "explanation": "Резерв роста небольшой; приоритет — сохранить устойчивость результата."}

        actions = {
            "urban_environment": "Повысить исполнение программ благоустройства дворов и проверить удовлетворённость жителей.",
            "road_quality_dtc": "Направить работы на ремонт и нормативное состояние дорог, одновременно сократив сроки устранения дефектов.",
            "accessible_environment": "Увеличить число завершённых мероприятий и охват адресной поддержкой.",
            "public_spaces": "Ускорить благоустройство общественных территорий и контролировать оценку жителей.",
            "road_quality_transit": "Повысить регулярность рейсов, качество маршрутов и состояние инфраструктуры общественного транспорта.",
            "parking_safety": "Приоритизировать безопасность движения, состояние дорог и быстрое устранение опасных дефектов.",
        }
        weakest = sorted(labels, key=lambda key: scenario[key])[:3]
        recommendations = [
            {
                "rank": rank,
                "index": key,
                "label": labels[key],
                "value": round(scenario[key], 2),
                "action": actions[key],
                "rule": "Индекс входит в три минимальных значения сценария.",
            }
            for rank, key in enumerate(weakest, start=1)
        ]
        return {
            "model": "ANFIS",
            "rule_count": self.pipeline_anfis.rule_count,
            "input_period": current_period,
            "forecast_period": period,
            "horizon": horizon,
            "current_target": round(float(self.bundle.raw["pipeline_target"].iloc[-1]), 5),
            "baseline_prediction": round(baseline_prediction, 5),
            "scenario_prediction": round(scenario_prediction, 5),
            "delta_points": round(delta, 5),
            "relative_change_percent": None if relative is None else round(relative, 5),
            "baseline_values": {key: round(value, 5) for key, value in baseline.items()},
            "scenario_values": {key: round(value, 5) for key, value in scenario.items()},
            "inputs": [{"id": key, "label": label} for key, label in labels.items()],
            "forecast": forecast_rows,
            "level": level,
            "recommendations": recommendations,
        }

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
            "model_catalog": [
                {"id": model_id, "label": label, **MODEL_CATALOG[model_id]}
                for model_id, label in MODEL_LABELS.items()
            ],
            "note": "Обучение: 2006Q1–2018Q4; настройка ANFIS: 2019Q1–2022Q4; test 2023Q1–2025Q4 не используется при настройке.",
        }

    def metadata(self) -> dict[str, Any]:
        anfis = [
            {
                "target": "pipeline_target",
                "inputs": self.pipeline_anfis.feature_names,
                "rule_count": self.pipeline_anfis.rule_count,
                "sigma": float(np.mean(self.pipeline_anfis.sigmas_)),
                "epochs": self.pipeline_anfis.trained_epochs_,
                "validation_rmse": self.pipeline_anfis.validation_rmse_,
                "source": "trained_from_pipeline",
            }
        ]
        return {
            "project": "Транспортная доступность и безопасность городской мобильности Смоленска",
            "problem": "Б",
            "source": self.bundle.source_path.name,
            "canonical_notebook": "primer/Pipeline (2).ipynb",
            "dataset": {
                "source_rows": len(self.bundle.source_features),
                "rows": len(self.bundle.features),
                "features": len(self.bundle.features.columns),
                "sheet": "Лист1",
                "header_rows": 2,
                "excluded_outliers": self.bundle.outlier_periods,
            },
            "features": self.bundle.feature_metadata,
            "period": {"start": self.bundle.raw.index[0], "end": self.bundle.raw.index[-1], "quarters": len(self.bundle.raw)},
            "splits": {
                "train": {"start": self.bundle.raw.index[0], "end": TRAIN_END, "quarters": 51},
                "validation": {"start": "2019Q1", "end": VALIDATION_END, "quarters": 16},
                "test": {"start": "2023Q1", "end": TEST_END, "quarters": 12},
            },
            "fcm": {"nodes": len(NODE_IDS), "edges": len(EXPERT_EDGES), "alpha": 0.35, "lambda": 1.3, "blend": "0.70 × expert + 0.30 × data"},
            "nodes": [spec.__dict__ for spec in NODE_SPECS],
            "targets": [config.__dict__ for config in TARGETS.values()] + [
                {"id": "integrated_mobility", "label": "Итоговый индекс безопасности и мобильности", "unit": "баллы из 100"},
                {"id": "pipeline_target", "label": "Итоговый индекс Pipeline", "unit": "баллы из 100"},
            ],
            "scenarios": builtin_items(),
            "fuzzy_indices": [{"id": spec.id, "label": spec.label, "rules": spec.rule_count} for spec in FUZZY_INDEX_SPECS],
            "anfis": anfis,
            "operational_training": self.training_status(),
            "proxies": [{"id": "digital_mobility", "label": "Цифровая мобильность", "description": "Прямого ряда цифровизации нет; сценарий воздействует на регулярность, скорость и загруженность."}],
        }

    def history(self) -> dict[str, Any]:
        periods = self.bundle.raw.index.to_list()
        split = [
            "train" if period <= TRAIN_END else
            "validation" if period <= VALIDATION_END else
            "test" if period <= TEST_END else
            "new_data"
            for period in periods
        ]
        definitions = [
            ("traffic_safety", "Безопасность движения", "баллы", "target"),
            ("accidents", "ДТП на 10 тыс. жителей", "ДТП на 10 тыс.", "indicator"),
            ("regularity", "Рейсы по расписанию", "%", "target"),
            ("accessibility", "Транспортная доступность", "баллы", "target"),
            ("integrated_mobility", "Итоговый индекс мобильности", "баллы", "target"),
            ("pipeline_target", "Итоговый индекс Pipeline", "баллы", "target"),
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
                "pipeline_target",
            )
        }
        latest["period"] = periods[-1]
        return {"periods": periods, "split": split, "series": series, "latest": latest}

    def indices(self) -> dict[str, Any]:
        fuzzy_label_by_id = {spec.id: spec.label for spec in FUZZY_INDEX_SPECS}
        hierarchical_contributions = self.bundle.hierarchical_contributions.iloc[-1].drop("hierarchical_fuzzy_index")
        hierarchical = self.bundle.raw["pipeline_target"]
        return {
            "periods": self.bundle.raw.index.to_list(),
            "fuzzy": [
                {
                    "id": spec.id,
                    "label": spec.label,
                    "features": list(spec.features),
                    "values": [round(float(value), 5) for value in self.bundle.fuzzy_indices[spec.id]],
                }
                for spec in FUZZY_INDEX_SPECS
            ],
            "hierarchical": [round(float(value), 5) for value in hierarchical],
            "hierarchical_stats": {
                "minimum": round(float(hierarchical.min()), 5),
                "maximum": round(float(hierarchical.max()), 5),
                "mean": round(float(hierarchical.mean()), 5),
                "median": round(float(hierarchical.median()), 5),
                "std": round(float(hierarchical.std()), 5),
                "latest": round(float(hierarchical.iloc[-1]), 5),
            },
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

    def analysis(self) -> dict[str, Any]:
        """Данные раздела EDA и функций принадлежности из Pipeline.ipynb."""
        periods = self.bundle.source_features.index.astype(str).to_list()
        metadata = {item["id"]: item for item in self.bundle.feature_metadata}
        boxplots: list[dict[str, Any]] = []
        for feature in self.bundle.source_features.columns:
            values = self.bundle.source_features[feature].astype(float)
            q1, median, q3 = values.quantile([0.25, 0.5, 0.75])
            iqr = float(q3 - q1)
            lower_limit = float(q1 - 1.5 * iqr)
            upper_limit = float(q3 + 1.5 * iqr)
            regular = values[(values >= lower_limit) & (values <= upper_limit)]
            outlier_mask = (values < lower_limit) | (values > upper_limit)
            item = metadata[feature]
            boxplots.append(
                {
                    "id": feature,
                    "label": item["label"],
                    "group": item["group"],
                    "values": [round(float(value), 6) for value in values],
                    "stats": {
                        "q1": round(float(q1), 6),
                        "median": round(float(median), 6),
                        "q3": round(float(q3), 6),
                        "lower_whisker": round(float(regular.min()), 6),
                        "upper_whisker": round(float(regular.max()), 6),
                        "outlier_count": int(outlier_mask.sum()),
                    },
                    "outliers": [
                        {"period": str(period), "value": round(float(value), 6)}
                        for period, value in values[outlier_mask].items()
                    ],
                }
            )

        memberships = []
        for spec in FUZZY_INDEX_SPECS:
            variables = []
            for feature, variable in zip(spec.features, spec.variables, strict=True):
                variables.append(
                    {
                        "id": feature,
                        "label": variable.name,
                        "kind": "input",
                        "universe": [variable.universe_min, variable.universe_max],
                        "quantiles": [
                            round(float(value), 6)
                            for value in self.bundle.pipeline_features[feature].quantile([0.25, 0.5, 0.75])
                        ],
                        "terms": [
                            {"name": term.name, "type": term.mf_type, "params": list(term.params)}
                            for term in variable.terms
                        ],
                    }
                )
            variables.append(
                {
                    "id": f"{spec.id}__output",
                    "label": spec.output.name,
                    "kind": "output",
                    "universe": [spec.output.universe_min, spec.output.universe_max],
                    "terms": [
                        {"name": term.name, "type": term.mf_type, "params": list(term.params)}
                        for term in spec.output.terms
                    ],
                }
            )
            memberships.append({"id": spec.id, "label": spec.label, "variables": variables})

        return {
            "source": "primer/Pipeline (2).ipynb",
            "periods": periods,
            "source_rows": len(periods),
            "processed_rows": len(self.bundle.features),
            "excluded_outliers": self.bundle.outlier_periods,
            "log1p_features": sorted(self.bundle.feature_scalers.keys() & {
                "дворы_благоустроено_ед",
                "пассажиропоток_тыс_A",
                "пассажиропоток_тыс_B",
                "дтп_10тыс_B",
                "переходы_регулируем_ед_B",
                "мероприятия_завершено_ед",
            }),
            "boxplots": boxplots,
            "memberships": memberships,
            "rule_files": sorted({spec.rule_filename for spec in FUZZY_INDEX_SPECS}),
            "applied_rules": sum(spec.rule_count for spec in FUZZY_INDEX_SPECS),
            "reference_memberships": {
                "universe": [0.0, 1.0],
                "terms": [
                    {"name": "Треугольная", "type": "trimf", "params": [0.0, 0.5, 1.0]},
                    {"name": "Трапециевидная", "type": "trapmf", "params": [0.0, 0.25, 0.75, 1.0]},
                ],
                "note": "В расчётах Pipeline используются треугольные функции; трапециевидная показана как поддерживаемая форма для экспертной настройки.",
            },
            "linear_weights": self.bundle.hierarchical_model.weights_table(
                {spec.id: spec.label for spec in FUZZY_INDEX_SPECS}
            ).to_dict(orient="records"),
            "target": [round(float(value), 6) for value in self.bundle.raw["pipeline_target"]],
            "target_periods": self.bundle.raw.index.astype(str).to_list(),
        }

    def fcm(self, mode: str) -> dict[str, object]:
        return graph_payload(self.weights, mode)

    def evaluation(self) -> dict[str, Any]:
        return {**self._evaluation, "sensitivity": self._sensitivity_cache}

    def scenarios(self) -> list[dict[str, Any]]:
        return builtin_items()

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

    def _fcm_simulation_trace(
        self,
        baseline_states: np.ndarray,
        scenario_states: np.ndarray,
    ) -> dict[str, Any]:
        """Возвращает полную динамику узлов для визуализации сценария на графе FCM."""

        steps: list[dict[str, Any]] = []
        max_abs_delta = 0.0
        for step, (baseline_state, scenario_state) in enumerate(
            zip(baseline_states, scenario_states, strict=True)
        ):
            nodes: dict[str, dict[str, float]] = {}
            for position, node_id in enumerate(NODE_IDS):
                baseline_value = float(baseline_state[position] * 100.0)
                scenario_value = float(scenario_state[position] * 100.0)
                delta = scenario_value - baseline_value
                max_abs_delta = max(max_abs_delta, abs(delta))
                nodes[node_id] = {
                    "baseline": round(baseline_value, 4),
                    "scenario": round(scenario_value, 4),
                    "delta": round(delta, 4),
                }
            steps.append(
                {
                    "step": step,
                    "period": str(
                        self.bundle.raw.index[-1]
                        if step == 0
                        else next_period(str(self.bundle.raw.index[-1]), step)
                    ),
                    "nodes": nodes,
                }
            )
        return {
            "steps": steps,
            "max_abs_delta": round(max_abs_delta, 4),
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

    @staticmethod
    def _level_status(value: float) -> str:
        if value < 40.0:
            return "Низкий уровень — нужны первоочередные меры"
        if value < 70.0:
            return "Средний уровень — есть заметный резерв улучшения"
        return "Устойчивый уровень — меры помогут закрепить результат"

    @staticmethod
    def _indicator_summary(
        series: pd.Series,
        label: str,
        unit: str,
        *,
        lower_is_better: bool = False,
    ) -> dict[str, Any]:
        current = float(series.iloc[-1])
        previous = float(series.iloc[-2])
        change_percent = None if abs(previous) < 1e-12 else (current - previous) / abs(previous) * 100.0
        delta = current - previous
        improved = delta < 0 if lower_is_better else delta > 0
        if abs(delta) < 1e-9:
            trend = "Без изменений к прошлому кварталу"
            tone = "neutral"
        elif improved:
            trend = "Показатель улучшился к прошлому кварталу"
            tone = "positive"
        else:
            trend = "Показатель ухудшился — нужны меры"
            tone = "negative"
        return {
            "label": label,
            "value": round(current, 3),
            "previous": round(previous, 3),
            "unit": unit,
            "change_percent": None if change_percent is None else round(change_percent, 2),
            "lower_is_better": lower_is_better,
            "trend": trend,
            "tone": tone,
        }

    def _build_improvement_recommendations(self) -> dict[str, Any]:
        """Пять понятных управленческих действий для каждой цели заказчика."""
        labels = {spec.id: spec.label for spec in NODE_SPECS}
        objectives: list[dict[str, Any]] = []
        target_values = {
            "traffic_safety": float(self.bundle.raw.iloc[-1]["traffic_safety"]),
            "transport_regularity": float(self.bundle.raw.iloc[-1]["regularity"]),
            "transport_accessibility": float(self.bundle.raw.iloc[-1]["accessibility"]),
            "integrated_mobility": float(self.bundle.raw.iloc[-1]["integrated_mobility"]),
        }
        target_labels = {
            "traffic_safety": "Безопасность движения",
            "transport_regularity": "Регулярность транспорта",
            "transport_accessibility": "Транспортная доступность",
            "integrated_mobility": "Сбалансированный результат",
        }
        indicators = {
            "traffic_safety": self._indicator_summary(
                self.bundle.raw["accidents"],
                "ДТП на 10 тыс. жителей",
                "ДТП на 10 тыс.",
                lower_is_better=True,
            ),
            "transport_regularity": self._indicator_summary(
                self.bundle.raw["regularity"],
                "Рейсы по расписанию",
                "%",
            ),
            "transport_accessibility": self._indicator_summary(
                self.bundle.raw["accessibility"],
                "Транспортная доступность",
                "баллов",
            ),
            "integrated_mobility": self._indicator_summary(
                self.bundle.raw["integrated_mobility"],
                "Сбалансированный индекс",
                "баллов",
            ),
        }
        for target_id, target_label in target_labels.items():
            ranked = sorted(
                self._sensitivity_cache[target_id],
                key=lambda item: item["delta_index_points"],
                reverse=True,
            )[:5]
            items = []
            for rank, item in enumerate(ranked, start=1):
                node = item["node"]
                target_nodes = (
                    ("traffic_safety", "transport_regularity", "transport_accessibility")
                    if target_id == "integrated_mobility"
                    else (TARGETS[target_id].factor_column,)
                )
                direct = any(abs(float(self.weights.adapted.loc[node, target])) > 1e-12 for target in target_nodes)
                items.append(
                    {
                        "rank": rank,
                        "factor": node,
                        "label": labels[node],
                        "action": NODE_ACTIONS.get(node, f"Улучшить направление «{labels[node]}» и закрепить ответственного."),
                        "relation": "Прямое влияние" if direct else "Смежное влияние через связанные показатели",
                        "expected_effect_points": round(float(item["delta_index_points"]), 4),
                        "current_level": round(float(self.bundle.factors.iloc[-1][node]) * 100.0, 2),
                    }
                )
            current = target_values[target_id]
            objectives.append(
                {
                    "id": target_id,
                    "label": target_label,
                    "current": round(current, 2),
                    "status": self._level_status(current),
                    "indicator": indicators[target_id],
                    "items": items,
                }
            )

        metadata = {item["id"]: item for item in self.bundle.feature_metadata}
        for spec in FUZZY_INDEX_SPECS:
            feature_ids = list(FUZZY_FEATURE_PRIORITY.get(spec.id, spec.features))[:5]
            items = []
            for feature in feature_ids:
                item = metadata[feature]
                improve = "Сократить" if FEATURE_DIRECTIONS[feature] < 0 else "Повысить"
                items.append(
                    {
                        "factor": feature,
                        "label": item["label"],
                        "action": f"{improve} показатель «{item['label']}» в направлении «{item['group']}».",
                        "relation": "Прямой вход JSON-правил этого индекса",
                        "expected_effect_points": None,
                        "current_level": round(float(self.bundle.source_features.loc[self.bundle.features.index[-1], feature]), 2),
                    }
                )
            related_target = FUZZY_RELATED_TARGET[spec.id]
            sensitivity = {item["node"]: item["delta_index_points"] for item in self._sensitivity_cache[related_target]}
            for node in FUZZY_ADJACENT_NODES.get(spec.id, ()):
                if len(items) >= 5:
                    break
                items.append(
                    {
                        "factor": node,
                        "label": labels[node],
                        "action": NODE_ACTIONS[node],
                        "relation": "Смежный фактор FCM",
                        "expected_effect_points": round(float(sensitivity.get(node, 0.0)), 4),
                        "current_level": round(float(self.bundle.factors.iloc[-1][node]) * 100.0, 2),
                    }
                )
            items = items[:5]
            for rank, item in enumerate(items, start=1):
                item["rank"] = rank
            current = float(self.bundle.fuzzy_indices.iloc[-1][spec.id])
            objectives.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "current": round(current, 2),
                    "status": self._level_status(current),
                    "items": items,
                }
            )
        if any(len(objective["items"]) != 5 for objective in objectives):
            raise RuntimeError("Для каждой цели заказчика должно быть сформировано ровно пять рекомендаций")
        return {
            "period": str(self.bundle.features.index[-1]),
            "objectives": objectives,
            "methodology_note": (
                "Первые четыре цели ранжируются по чувствительности FCM. Индексы Pipeline используют прямые входы "
                "канонических JSON-правил и связанные факторы. Это приоритеты для обсуждения, а не автоматическое решение о расходах."
            ),
        }

    def simulate(
        self,
        scenario_id: str,
        mode: str | None = None,
        horizon: int | None = None,
        custom_impulses: Mapping[str, float] | None = None,
        index_values: Mapping[str, float] | None = None,
        scenario_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        scenario = validate_scenario(scenario_payload) if scenario_payload is not None else get_builtin(scenario_id)
        if scenario is None:
            raise ValueError(f"Неизвестный сценарий: {scenario_id}")
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
            combined = impulses.get(key, 0.0) + numeric
            if not -IMPULSE_LIMIT <= combined <= IMPULSE_LIMIT:
                raise ValueError(f"Итоговое воздействие на {key} должно быть в диапазоне [-1, 1]")
            impulses[key] = float(np.clip(combined, -IMPULSE_LIMIT, IMPULSE_LIMIT))

        initial = self.bundle.factors.iloc[-1].to_numpy(dtype=float)
        scenario_initial = initial.copy()
        node_positions = {spec.id: index for index, spec in enumerate(NODE_SPECS)}
        fuzzy_latest = self.bundle.fuzzy_indices.iloc[-1]
        effective_index_values = {
            **dict(scenario.get("index_values", {})),
            **dict(index_values or {}),
        }
        for index_id, value in effective_index_values.items():
            if index_id not in INDEX_CONTROL_NODES:
                raise ValueError(f"Индекс {index_id} нельзя изменять в лаборатории")
            numeric = float(value)
            if not np.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
                raise ValueError(f"Значение индекса {index_id} должно быть в диапазоне [0, 100]")
            node_id = INDEX_CONTROL_NODES[index_id]
            if node_id not in node_positions:
                raise RuntimeError(f"Для индекса {index_id} не настроен узел FCM: {node_id}")
            delta = (numeric - float(fuzzy_latest[index_id])) / 100.0
            position = node_positions[node_id]
            scenario_initial[position] = float(np.clip(scenario_initial[position] + delta, 0.0, 1.0))
        weights = self._weights_array(selected_mode)
        baseline_states = fcm_forecast(initial, weights, selected_horizon)
        scenario_states = fcm_forecast(scenario_initial, weights, selected_horizon, impulse_vector(impulses))
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

        summary = self._business_summary(final_base, final_scenario)
        budget_analysis = self._budget_analysis(
            initial=initial,
            weights=weights,
            baseline_final=final_base,
            horizon=selected_horizon,
            mode=selected_mode,
        )

        return {
            "scenario": {"id": scenario["id"], "label": scenario["label"], "description": scenario["description"], "builtin": scenario["builtin"]},
            "mode": selected_mode,
            "horizon": selected_horizon,
            "applied_impulses": [{"node": node, "label": label_by_id[node], "value": round(value, 4)} for node, value in impulses.items()],
            "fcm_simulation": self._fcm_simulation_trace(baseline_states, scenario_states),
            "baseline": baseline_rows,
            "scenario_result": scenario_rows,
            "explanation": explanations,
            "summary": summary,
            "budget_analysis": budget_analysis,
            "improvement_recommendations": self._recommendations_cache,
        }

    @staticmethod
    def _relative_change(baseline: float, scenario: float) -> float | None:
        if abs(baseline) < 1e-9:
            return None
        return round((scenario - baseline) / abs(baseline) * 100.0, 4)

    def _business_summary(
        self,
        baseline: Mapping[str, Any],
        scenario: Mapping[str, Any],
    ) -> dict[str, Any]:
        definitions = {
            "safety": ("safety_index", "Безопасность движения", "индексных пунктов"),
            "regularity": ("regularity", "Регулярность транспорта", "процентных пунктов"),
            "accessibility": ("accessibility", "Транспортная доступность", "индексных пунктов"),
            "integrated_mobility": ("integrated_mobility", "Итоговый индекс мобильности", "индексных пунктов"),
        }
        output: dict[str, Any] = {}
        for metric_id, (source_key, label, delta_unit) in definitions.items():
            base_value = float(baseline[source_key])
            scenario_value = float(scenario[source_key])
            output[metric_id] = {
                "label": label,
                "baseline": round(base_value, 4),
                "scenario": round(scenario_value, 4),
                "delta_points": round(scenario_value - base_value, 4),
                "delta_unit": delta_unit,
                "relative_change_percent": self._relative_change(base_value, scenario_value),
            }

        base_accidents = float(baseline["accidents"])
        scenario_accidents = float(scenario["accidents"])
        improvement = None
        if abs(base_accidents) >= 1e-9:
            improvement = round((base_accidents - scenario_accidents) / abs(base_accidents) * 100.0, 4)
        output["accidents"] = {
            "label": "ДТП на 10 тыс. жителей",
            "baseline": round(base_accidents, 4),
            "scenario": round(scenario_accidents, 4),
            "delta": round(scenario_accidents - base_accidents, 4),
            "improvement_percent": improvement,
        }
        return output

    def _budget_analysis(
        self,
        *,
        initial: np.ndarray,
        weights: np.ndarray,
        baseline_final: Mapping[str, Any],
        horizon: int,
        mode: str,
        standard_impulse: float = 0.07,
    ) -> dict[str, Any]:
        budget_nodes = (
            "road_budget_execution",
            "transit_budget_execution",
            "safety_budget_execution",
        )
        labels = {spec.id: spec.label for spec in NODE_SPECS}
        programs: list[dict[str, Any]] = []
        for node in budget_nodes:
            states = fcm_forecast(
                initial,
                weights,
                horizon,
                impulse_vector({node: standard_impulse}),
            )
            scenario_final = self._scenario_row(horizon, states[-1])
            summary = self._business_summary(baseline_final, scenario_final)
            programs.append(
                {
                    "node": node,
                    "label": labels[node],
                    "standard_impulse": standard_impulse,
                    "metrics": {
                        key: summary[key]
                        for key in ("safety", "regularity", "accessibility", "integrated_mobility")
                    },
                }
            )
        return {
            "mode": mode,
            "horizon": horizon,
            "standard_impulse": standard_impulse,
            "default_target": "integrated_mobility",
            "programs": programs,
            "methodology_note": (
                "Рейтинг сравнивает одинаковое безразмерное воздействие FCM и не является "
                "расчётом финансового ROI или рекомендацией суммы в рублях."
            ),
        }
