from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LinearFeatureSpec:
    feature: str
    weight: float
    direction: int


LINEAR_FEATURE_SPECS = (
    LinearFeatureSpec("бюджет_дворы_pct", 0.3, 1),
    LinearFeatureSpec("дворы_благоустроено_ед", 0.4, 1),
    LinearFeatureSpec("удовлетворенность_средой_дворы_pct", 0.4, 1),
    LinearFeatureSpec("бюджет_трансп_A_pct", 0.8, 1),
    LinearFeatureSpec("дороги_отремонт_км_A", 0.7, 1),
    LinearFeatureSpec("дороги_норматив_pct_A", 0.8, 1),
    LinearFeatureSpec("пассажиропоток_тыс_A", 0.6, 1),
    LinearFeatureSpec("рейсы_расписание_pct_A", 0.6, 1),
    LinearFeatureSpec("скорость_магистрали_A_кмч", 0.6, 1),
    LinearFeatureSpec("дтп_10тыс_A", 0.5, -1),
    LinearFeatureSpec("срок_устранения_деф_сут_A", 0.7, -1),
    LinearFeatureSpec("переходы_регулируем_ед_A", 0.4, 1),
    LinearFeatureSpec("бюджет_соцподдержка_pct", 0.2, 1),
    LinearFeatureSpec("мероприятия_завершено_ед", 0.2, 1),
    LinearFeatureSpec("получатели_адрподдержки_чел", 0.2, 1),
    LinearFeatureSpec("бюджет_обществ_территории_pct", 0.6, 1),
    LinearFeatureSpec("территории_благоустроено_ед", 0.4, 1),
    LinearFeatureSpec("удовлетворенность_средой_терр_pct", 0.6, 1),
    LinearFeatureSpec("бюджет_трансп_B_pct", 0.9, 1),
    LinearFeatureSpec("дороги_отремонт_км_B", 0.8, 1),
    LinearFeatureSpec("дороги_норматив_pct_B", 0.9, 1),
    LinearFeatureSpec("пассажиропоток_тыс_B", 0.8, 1),
    LinearFeatureSpec("рейсы_расписание_pct_B", 0.8, 1),
    LinearFeatureSpec("скорость_магистрали_B_кмч", 0.7, 1),
    LinearFeatureSpec("дтп_10тыс_B", 0.7, -1),
    LinearFeatureSpec("срок_устранения_деф_сут_B", 0.7, -1),
    LinearFeatureSpec("переходы_регулируем_ед_B", 0.5, 1),
    LinearFeatureSpec("бюджет_дороги_C_pct", 0.6, 1),
    LinearFeatureSpec("дороги_отремонт_км_C", 0.4, 1),
    LinearFeatureSpec("дороги_норматив_pct_C", 0.5, 1),
    LinearFeatureSpec("срок_устранения_деф_сут_C", 0.3, -1),
)

HIERARCHICAL_FUZZY_SPECS = (
    LinearFeatureSpec("urban_environment", 0.6, 1),
    LinearFeatureSpec("road_quality_dtc", 0.6, 1),
    LinearFeatureSpec("road_wellbeing_dtc", 0.7, 1),
    LinearFeatureSpec("accessible_environment", 0.2, 1),
    LinearFeatureSpec("public_spaces", 0.5, 1),
    LinearFeatureSpec("road_quality_transit", 0.7, 1),
    LinearFeatureSpec("road_wellbeing_transit", 0.9, 1),
    LinearFeatureSpec("parking_safety", 0.4, 1),
)


class LinearConvolutionIndex:
    """Версия линейной экспертной свёртки Гульдар без утечки test."""

    def __init__(
        self,
        specs: tuple[LinearFeatureSpec, ...] = LINEAR_FEATURE_SPECS,
        *,
        name: str = "linear_expert_index",
    ):
        self.specs = specs
        self.name = name
        self.feature_names = [spec.feature for spec in specs]
        raw_weights = np.asarray([spec.weight for spec in specs], dtype=float)
        if np.any(raw_weights < 0.0) or raw_weights.sum() <= 0.0:
            raise ValueError("Экспертные веса должны быть неотрицательными и иметь положительную сумму")
        self.raw_weights = raw_weights
        self.weights = raw_weights / raw_weights.sum()
        self.directions = np.asarray([spec.direction for spec in specs], dtype=int)
        self.minimum_: pd.Series | None = None
        self.maximum_: pd.Series | None = None

    def fit(self, frame: pd.DataFrame) -> "LinearConvolutionIndex":
        missing = set(self.feature_names) - set(frame.columns)
        if missing:
            raise ValueError(f"В данных отсутствуют признаки линейного индекса: {sorted(missing)}")
        numeric = frame.loc[:, self.feature_names].apply(pd.to_numeric, errors="raise")
        self.minimum_ = numeric.min()
        self.maximum_ = numeric.max()
        return self

    def normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.minimum_ is None or self.maximum_ is None:
            raise RuntimeError("LinearConvolutionIndex ещё не обучен")
        numeric = frame.loc[:, self.feature_names].astype(float)
        span = (self.maximum_ - self.minimum_).replace(0.0, 1.0)
        normalized = ((numeric - self.minimum_) / span).clip(0.0, 1.0)
        for feature, direction in zip(self.feature_names, self.directions, strict=True):
            if direction < 0:
                normalized[feature] = 1.0 - normalized[feature]
        return normalized

    def transform(self, frame: pd.DataFrame) -> pd.Series:
        normalized = self.normalize(frame)
        values = normalized.to_numpy(dtype=float) @ self.weights
        return pd.Series(values, index=frame.index, name=self.name)

    def fit_transform(self, frame: pd.DataFrame) -> pd.Series:
        return self.fit(frame).transform(frame)

    def contributions(self, frame: pd.DataFrame) -> pd.DataFrame:
        normalized = self.normalize(frame)
        contributions = normalized.mul(self.weights, axis=1)
        contributions[self.name] = contributions.sum(axis=1)
        return contributions

    def weights_table(self, labels: Mapping[str, str] | None = None) -> pd.DataFrame:
        labels = labels or {}
        return pd.DataFrame(
            {
                "feature": self.feature_names,
                "label": [labels.get(feature, feature) for feature in self.feature_names],
                "raw_weight": self.raw_weights,
                "weight": self.weights,
                "direction": self.directions,
            }
        )
