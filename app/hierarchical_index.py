from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HierarchicalFeatureSpec:
    feature: str
    weight: float


HIERARCHICAL_FUZZY_SPECS = (
    HierarchicalFeatureSpec("urban_environment", 0.6),
    HierarchicalFeatureSpec("road_quality_dtc", 0.6),
    HierarchicalFeatureSpec("road_wellbeing_dtc", 0.7),
    HierarchicalFeatureSpec("accessible_environment", 0.2),
    HierarchicalFeatureSpec("public_spaces", 0.5),
    HierarchicalFeatureSpec("road_quality_transit", 0.7),
    HierarchicalFeatureSpec("road_wellbeing_transit", 0.9),
    HierarchicalFeatureSpec("parking_safety", 0.4),
)


class HierarchicalFuzzyIndex:
    """Линейная свёртка восьми индексов из ``Pipeline.ipynb``."""

    name = "hierarchical_fuzzy_index"

    def __init__(
        self,
        specs: tuple[HierarchicalFeatureSpec, ...] = HIERARCHICAL_FUZZY_SPECS,
    ):
        self.specs = specs
        self.feature_names = [spec.feature for spec in specs]
        raw_weights = np.asarray([spec.weight for spec in specs], dtype=float)
        if np.any(raw_weights < 0.0) or raw_weights.sum() <= 0.0:
            raise ValueError("Экспертные веса должны быть неотрицательными и иметь положительную сумму")
        self.raw_weights = raw_weights
        self.weights = raw_weights / raw_weights.sum()
        self.minimum_: pd.Series | None = None
        self.maximum_: pd.Series | None = None

    def fit(self, frame: pd.DataFrame) -> "HierarchicalFuzzyIndex":
        missing = set(self.feature_names) - set(frame.columns)
        if missing:
            raise ValueError(f"В данных отсутствуют признаки иерархического индекса: {sorted(missing)}")
        numeric = frame.loc[:, self.feature_names].apply(pd.to_numeric, errors="raise")
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError("Индексы Pipeline должны быть конечными")
        # Сохраняются только для диагностической совместимости. В отличие от
        # прежней реализации Pipeline не нормализует восемь индексов повторно.
        self.minimum_ = numeric.min()
        self.maximum_ = numeric.max()
        return self

    def normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.minimum_ is None or self.maximum_ is None:
            raise RuntimeError("HierarchicalFuzzyIndex ещё не обучен")
        return frame.loc[:, self.feature_names].astype(float)

    def transform(self, frame: pd.DataFrame) -> pd.Series:
        values = self.normalize(frame).to_numpy(dtype=float) @ self.weights
        return pd.Series(values, index=frame.index, name=self.name)

    def contributions(self, frame: pd.DataFrame) -> pd.DataFrame:
        contributions = self.normalize(frame).mul(self.weights, axis=1)
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
            }
        )
