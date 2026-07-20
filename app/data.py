from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .config import DATA_PATH, TEST_END, TRAIN_END, TRAIN_START
from .fuzzy import FUZZY_INDEX_SPECS, calculate_fuzzy_indices
from .hierarchical_index import HierarchicalFuzzyIndex


EXPECTED_PERIODS = [f"{year}Q{quarter}" for year in range(2006, 2026) for quarter in range(1, 5)]

FEATURE_NAMES = [feature for index_spec in FUZZY_INDEX_SPECS for feature in index_spec.features]
NEGATIVE_FEATURES = {
    "дтп_10тыс_A",
    "срок_устранения_деф_сут_A",
    "дтп_10тыс_B",
    "срок_устранения_деф_сут_B",
    "срок_устранения_деф_сут_C",
}
FEATURE_DIRECTIONS = {
    feature: -1 if feature in NEGATIVE_FEATURES else 1
    for feature in FEATURE_NAMES
}
LOG_FEATURES = {
    "дворы_благоустроено_ед",
    "пассажиропоток_тыс_A",
    "пассажиропоток_тыс_B",
    "дтп_10тыс_B",
    "переходы_регулируем_ед_B",
    "мероприятия_завершено_ед",
}


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    kind: str
    unit: str
    description: str
    adjustable: bool = False


NODE_SPECS = (
    NodeSpec("road_budget_execution", "Исполнение дорожного бюджета", "control", "%", "Исполнение программы дорожного комплекса.", True),
    NodeSpec("transit_budget_execution", "Исполнение бюджета транспорта", "control", "%", "Исполнение программы общественного транспорта.", True),
    NodeSpec("safety_budget_execution", "Исполнение бюджета безопасности", "control", "%", "Исполнение программы парковок и безопасности.", True),
    NodeSpec("road_repair", "Ремонт дорог", "control", "км", "Сводный объём ремонта дорог.", True),
    NodeSpec("road_condition", "Нормативное состояние дорог", "intermediate", "%", "Сводная доля дорог в нормативном состоянии.", True),
    NodeSpec("defect_response", "Эффективность устранения дефектов", "intermediate", "индекс", "Обратный нормализованный срок устранения дефектов.", True),
    NodeSpec("passenger_flow", "Пассажиропоток", "external", "тыс. поездок", "Сводный пассажиропоток транспортных программ.", True),
    NodeSpec("transport_regularity", "Регулярность транспорта", "target", "%", "Доля рейсов по расписанию.", True),
    NodeSpec("average_speed", "Средняя скорость", "intermediate", "км/ч", "Средняя скорость на магистралях.", True),
    NodeSpec("crossings", "Регулируемые переходы", "control", "ед.", "Количество регулируемых переходов.", True),
    NodeSpec("road_quality", "Нечёткое качество дорог", "intermediate", "индекс", "Среднее двух нечётких индексов качества дорог."),
    NodeSpec("road_wellbeing", "Нечёткое благополучие дорог", "intermediate", "индекс", "Среднее двух индексов дорожного благополучия."),
    NodeSpec("transport_environment", "Нечёткая транспортная среда", "intermediate", "индекс", "Агрегат среды, доступности, пространств и безопасности."),
    NodeSpec("congestion", "Загруженность", "external", "индекс", "Обратная нормализованная скорость.", True),
    NodeSpec("traffic_safety", "Безопасность движения", "target", "индекс", "Обратный нормализованный уровень ДТП."),
    NodeSpec("transport_accessibility", "Транспортная доступность", "target", "индекс", "Композит регулярности, скорости, дорог, переходов и среды."),
)
NODE_IDS = [spec.id for spec in NODE_SPECS]


@dataclass
class TrainMinMaxScaler:
    minimum: float
    maximum: float
    direction: str = "positive"
    lower_bound: float | None = None
    upper_bound: float | None = None
    log1p: bool = False
    fitted_until: str = TRAIN_END

    @classmethod
    def fit(
        cls,
        values: pd.Series,
        direction: str = "positive",
        *,
        log1p: bool = False,
        winsorize: bool = False,
    ) -> "TrainMinMaxScaler":
        numeric = pd.to_numeric(values, errors="coerce").astype(float)
        if numeric.isna().any():
            numeric = numeric.interpolate(limit_direction="both").fillna(numeric.median())
        transformed = np.log1p(numeric.clip(lower=0.0)) if log1p else numeric
        lower = upper = None
        if winsorize:
            q1, q3 = transformed.quantile([0.25, 0.75])
            iqr = float(q3 - q1)
            lower = float(q1 - 1.5 * iqr)
            upper = float(q3 + 1.5 * iqr)
            transformed = transformed.clip(lower, upper)
        return cls(
            minimum=float(transformed.min()),
            maximum=float(transformed.max()),
            direction=direction,
            lower_bound=lower,
            upper_bound=upper,
            log1p=log1p,
        )

    def _prepare(self, values: pd.Series | np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if self.log1p:
            array = np.log1p(np.clip(array, 0.0, None))
        if self.lower_bound is not None and self.upper_bound is not None:
            array = np.clip(array, self.lower_bound, self.upper_bound)
        return array

    def transform(self, values: pd.Series | np.ndarray) -> np.ndarray:
        array = self._prepare(values)
        span = self.maximum - self.minimum
        scaled = np.full_like(array, 0.5, dtype=float) if np.isclose(span, 0.0) else (array - self.minimum) / span
        if self.direction == "negative":
            scaled = 1.0 - scaled
        return np.clip(scaled, 0.0, 1.0)

    def inverse(self, values: pd.Series | np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if self.direction == "negative":
            array = 1.0 - array
        transformed = self.minimum + array * (self.maximum - self.minimum)
        return np.expm1(transformed) if self.log1p else transformed


@dataclass
class DataBundle:
    raw: pd.DataFrame
    features: pd.DataFrame
    quality_features: pd.DataFrame
    fuzzy_indices: pd.DataFrame
    factors: pd.DataFrame
    scalers: Dict[str, TrainMinMaxScaler]
    feature_scalers: Dict[str, TrainMinMaxScaler]
    hierarchical_model: HierarchicalFuzzyIndex
    hierarchical_contributions: pd.DataFrame
    feature_metadata: list[dict[str, str]]
    source_path: Path


def _read_shared_dataset(path: Path) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл данных: {path}")
    loaded = pd.read_excel(path, sheet_name="Лист1", header=[0, 1], engine="openpyxl")
    if loaded.shape != (80, 37):
        raise ValueError(f"Ожидалась таблица 80×37, получено {loaded.shape[0]}×{loaded.shape[1]}")

    periods = loaded.iloc[:, 0].astype(str).tolist()
    if periods != EXPECTED_PERIODS:
        raise ValueError("Датасет должен содержать кварталы 2006Q1–2025Q4 без пропусков")
    meta_names = [str(value).strip() for value in loaded.columns.get_level_values(1)[:5]]
    if meta_names != ["period", "period_start", "year", "quarter", "period_index"]:
        raise ValueError(f"Неожиданные служебные столбцы: {meta_names}")

    features = loaded.iloc[:, 5:36].copy()
    features.columns = FEATURE_NAMES
    features.index = pd.Index(periods, name="period")
    features = features.apply(pd.to_numeric, errors="raise").astype(float)
    if features.isna().any().any() or not np.isfinite(features.to_numpy()).all():
        raise ValueError("В 31 показателе обнаружены пропуски или бесконечные значения")

    top = pd.Series(loaded.columns.get_level_values(0)[5:36]).replace(r"^Unnamed:.*", np.nan, regex=True).ffill()
    labels = [str(value).strip() for value in loaded.columns.get_level_values(1)[5:36]]
    metadata = [
        {"id": feature, "group": str(group), "label": label}
        for feature, group, label in zip(FEATURE_NAMES, top, labels, strict=True)
    ]
    return features, metadata


def _mean(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    return frame.loc[:, columns].mean(axis=1)


def load_problem_b_data(path: Path = DATA_PATH) -> DataBundle:
    features, metadata = _read_shared_dataset(path)
    train = features.loc[TRAIN_START:TRAIN_END]

    feature_scalers: dict[str, TrainMinMaxScaler] = {}
    quality = pd.DataFrame(index=features.index)
    for feature in FEATURE_NAMES:
        direction = "negative" if FEATURE_DIRECTIONS[feature] < 0 else "positive"
        scaler = TrainMinMaxScaler.fit(
            train[feature],
            direction,
            log1p=feature in LOG_FEATURES,
            winsorize=True,
        )
        feature_scalers[feature] = scaler
        quality[feature] = scaler.transform(features[feature]) * 100.0

    fuzzy = calculate_fuzzy_indices(quality)
    hierarchical_model = HierarchicalFuzzyIndex().fit(fuzzy.loc[TRAIN_START:TRAIN_END])
    hierarchical_index = hierarchical_model.transform(fuzzy)
    hierarchical_contributions = hierarchical_model.contributions(fuzzy)

    raw = features.copy()
    raw["accidents"] = _mean(features, ["дтп_10тыс_A", "дтп_10тыс_B"])
    raw["regularity"] = _mean(features, ["рейсы_расписание_pct_A", "рейсы_расписание_pct_B"])
    raw["avg_speed"] = _mean(features, ["скорость_магистрали_A_кмч", "скорость_магистрали_B_кмч"])
    raw["road_repair"] = _mean(features, ["дороги_отремонт_км_A", "дороги_отремонт_км_B", "дороги_отремонт_км_C"])
    raw["road_condition"] = _mean(features, ["дороги_норматив_pct_A", "дороги_норматив_pct_B", "дороги_норматив_pct_C"])
    raw["defect_days"] = _mean(features, ["срок_устранения_деф_сут_A", "срок_устранения_деф_сут_B", "срок_устранения_деф_сут_C"])
    raw["passenger_flow"] = _mean(features, ["пассажиропоток_тыс_A", "пассажиропоток_тыс_B"])
    raw["crossings"] = _mean(features, ["переходы_регулируем_ед_A", "переходы_регулируем_ед_B"])
    raw["hierarchical_fuzzy_index"] = hierarchical_index * 100.0
    for column in fuzzy:
        raw[column] = fuzzy[column]

    aggregate_directions = {
        "accidents": "negative",
        "regularity": "positive",
        "avg_speed": "positive",
        "road_repair": "positive",
        "road_condition": "positive",
        "defect_days": "negative",
        "passenger_flow": "positive",
        "crossings": "positive",
    }
    scalers = {
        name: TrainMinMaxScaler.fit(raw.loc[:TRAIN_END, name], direction)
        for name, direction in aggregate_directions.items()
    }

    factors = pd.DataFrame(index=features.index)
    factors["road_budget_execution"] = quality["бюджет_трансп_A_pct"] / 100.0
    factors["transit_budget_execution"] = quality["бюджет_трансп_B_pct"] / 100.0
    factors["safety_budget_execution"] = quality["бюджет_дороги_C_pct"] / 100.0
    for column in ("road_repair", "road_condition", "defect_days", "passenger_flow", "regularity", "avg_speed", "crossings"):
        target = {"defect_days": "defect_response", "regularity": "transport_regularity", "avg_speed": "average_speed"}.get(column, column)
        factors[target] = scalers[column].transform(raw[column])
    factors["road_quality"] = fuzzy[["road_quality_dtc", "road_quality_transit"]].mean(axis=1) / 100.0
    factors["road_wellbeing"] = fuzzy[["road_wellbeing_dtc", "road_wellbeing_transit"]].mean(axis=1) / 100.0
    factors["transport_environment"] = fuzzy[["urban_environment", "accessible_environment", "public_spaces", "parking_safety"]].mean(axis=1) / 100.0
    factors["congestion"] = 1.0 - factors["average_speed"]
    factors["traffic_safety"] = scalers["accidents"].transform(raw["accidents"])
    factors["transport_accessibility"] = (
        0.30 * factors["transport_regularity"]
        + 0.20 * factors["average_speed"]
        + 0.20 * factors["road_condition"]
        + 0.15 * factors["crossings"]
        + 0.15 * factors["transport_environment"]
    ).clip(0.0, 1.0)
    factors = factors.loc[:, NODE_IDS]

    raw["traffic_safety"] = factors["traffic_safety"] * 100.0
    raw["accessibility"] = factors["transport_accessibility"] * 100.0
    raw["integrated_mobility"] = (
        factors[["traffic_safety", "transport_regularity", "transport_accessibility"]].mean(axis=1) * 100.0
    )
    if not np.isfinite(factors.to_numpy()).all() or factors.min().min() < 0.0 or factors.max().max() > 1.0:
        raise ValueError("Факторы FCM должны быть конечными и находиться в диапазоне [0, 1]")
    if raw.index[0] != TRAIN_START or raw.index[-1] != TEST_END:
        raise ValueError("Диапазон данных не совпадает с 2006Q1–2025Q4")

    return DataBundle(
        raw=raw,
        features=features,
        quality_features=quality,
        fuzzy_indices=fuzzy,
        factors=factors,
        scalers=scalers,
        feature_scalers=feature_scalers,
        hierarchical_model=hierarchical_model,
        hierarchical_contributions=hierarchical_contributions,
        feature_metadata=metadata,
        source_path=path,
    )
