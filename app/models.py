from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = np.abs(y_true) + np.abs(y_pred)
    denominator = np.where(denominator < 1e-12, 1e-12, denominator)
    return float(np.mean(2.0 * np.abs(y_pred - y_true) / denominator) * 100.0)


def metric_set(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    train_values: np.ndarray,
    previous_actual: np.ndarray,
    seasonal_period: int = 4,
) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    previous_actual = np.asarray(previous_actual, dtype=float)
    if len(y_true) == 0:
        raise ValueError("Нельзя рассчитать метрики на пустой выборке.")

    errors = y_pred - y_true
    seasonal_scale = np.mean(np.abs(train_values[seasonal_period:] - train_values[:-seasonal_period]))
    if not np.isfinite(seasonal_scale) or seasonal_scale < 1e-12:
        seasonal_scale = 1.0
    actual_direction = np.sign(y_true - previous_actual)
    predicted_direction = np.sign(y_pred - previous_actual)
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "smape": smape(y_true, y_pred),
        "mase": float(np.mean(np.abs(errors)) / seasonal_scale),
        "directional_accuracy": float(np.mean(actual_direction == predicted_direction)),
    }


class RidgeRegressor:
    """Минимальная Ridge-регрессия без зависимости от scikit-learn."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = float(alpha)
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.coef_: np.ndarray | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RidgeRegressor":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self.mean_ = x.mean(axis=0)
        self.scale_ = x.std(axis=0)
        self.scale_ = np.where(self.scale_ < 1e-12, 1.0, self.scale_)
        normalized = (x - self.mean_) / self.scale_
        design = np.column_stack([np.ones(len(normalized)), normalized])
        penalty = np.eye(design.shape[1]) * self.alpha
        penalty[0, 0] = 0.0
        self.coef_ = np.linalg.solve(design.T @ design + penalty, design.T @ y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None or self.coef_ is None:
            raise RuntimeError("RidgeRegressor ещё не обучен.")
        x = np.asarray(x, dtype=float)
        normalized = (x - self.mean_) / self.scale_
        design = np.column_stack([np.ones(len(normalized)), normalized])
        return design @ self.coef_


class ANFISRegressor:
    """
    Компактная модель Сугено: две гауссовы функции принадлежности на вход,
    до 16 правил и линейные консеквенты, обучаемые Ridge-методом.
    Ширина функций и регуляризация выбираются по валидационной RMSE.
    """

    def __init__(
        self,
        feature_names: Sequence[str],
        sigma_candidates: Iterable[float] = (0.20, 0.35, 0.50),
        ridge_candidates: Iterable[float] = (0.001, 0.01, 0.1),
    ):
        if not 1 <= len(feature_names) <= 4:
            raise ValueError("ANFIS поддерживает от одного до четырёх входов.")
        self.feature_names = list(feature_names)
        self.sigma_candidates = tuple(float(value) for value in sigma_candidates)
        self.ridge_candidates = tuple(float(value) for value in ridge_candidates)
        self.x_min_: np.ndarray | None = None
        self.x_max_: np.ndarray | None = None
        self.centers_: np.ndarray | None = None
        self.rules_: np.ndarray | None = None
        self.sigma_: float | None = None
        self.ridge_: float | None = None
        self.theta_: np.ndarray | None = None
        self.validation_rmse_: float | None = None

    @property
    def rule_count(self) -> int:
        return 0 if self.rules_ is None else int(len(self.rules_))

    def _scale(self, x: np.ndarray) -> np.ndarray:
        if self.x_min_ is None or self.x_max_ is None:
            raise RuntimeError("ANFIS ещё не обучен.")
        span = np.where(np.abs(self.x_max_ - self.x_min_) < 1e-12, 1.0, self.x_max_ - self.x_min_)
        return np.clip((np.asarray(x, dtype=float) - self.x_min_) / span, 0.0, 1.0)

    def _design(self, scaled_x: np.ndarray, sigma: float) -> np.ndarray:
        if self.centers_ is None or self.rules_ is None:
            raise RuntimeError("Не инициализированы нечёткие правила.")
        memberships = np.exp(
            -0.5 * ((scaled_x[:, :, None] - self.centers_[None, :, :]) / sigma) ** 2
        )
        firing = np.ones((len(scaled_x), len(self.rules_)), dtype=float)
        for rule_index, rule in enumerate(self.rules_):
            for feature_index, membership_index in enumerate(rule):
                firing[:, rule_index] *= memberships[:, feature_index, membership_index]
        firing /= np.maximum(firing.sum(axis=1, keepdims=True), 1e-12)
        consequent_inputs = np.column_stack([np.ones(len(scaled_x)), scaled_x])
        return np.concatenate(
            [firing[:, rule_index, None] * consequent_inputs for rule_index in range(len(self.rules_))],
            axis=1,
        )

    @staticmethod
    def _solve(design: np.ndarray, y: np.ndarray, ridge: float) -> np.ndarray:
        penalty = np.eye(design.shape[1], dtype=float) * ridge
        return np.linalg.solve(design.T @ design + penalty, design.T @ y)

    def fit(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_validation: np.ndarray,
        y_validation: np.ndarray,
    ) -> "ANFISRegressor":
        x_train = np.asarray(x_train, dtype=float)
        y_train = np.asarray(y_train, dtype=float)
        x_validation = np.asarray(x_validation, dtype=float)
        y_validation = np.asarray(y_validation, dtype=float)
        self.x_min_ = x_train.min(axis=0)
        self.x_max_ = x_train.max(axis=0)
        scaled_train = self._scale(x_train)
        scaled_validation = self._scale(x_validation)
        self.centers_ = np.column_stack(
            [np.quantile(scaled_train, 0.30, axis=0), np.quantile(scaled_train, 0.70, axis=0)]
        )
        self.rules_ = np.asarray(list(product((0, 1), repeat=x_train.shape[1])), dtype=int)
        if len(self.rules_) > 16:
            raise RuntimeError("Число нечётких правил превысило 16.")

        best: tuple[float, float, float, np.ndarray] | None = None
        for sigma in self.sigma_candidates:
            train_design = self._design(scaled_train, sigma)
            validation_design = self._design(scaled_validation, sigma)
            for ridge in self.ridge_candidates:
                theta = self._solve(train_design, y_train, ridge)
                prediction = validation_design @ theta
                rmse = float(np.sqrt(np.mean((prediction - y_validation) ** 2)))
                candidate = (rmse, sigma, ridge, theta)
                if best is None or candidate[0] < best[0]:
                    best = candidate

        assert best is not None
        self.validation_rmse_, self.sigma_, self.ridge_, self.theta_ = best
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self.sigma_ is None or self.theta_ is None:
            raise RuntimeError("ANFIS ещё не обучен.")
        return self._design(self._scale(np.asarray(x, dtype=float)), self.sigma_) @ self.theta_

    def feature_effects(self, x_reference: np.ndarray, delta: float = 0.05) -> dict[str, float]:
        scaled = self._scale(np.asarray(x_reference, dtype=float))
        effects: dict[str, float] = {}
        for index, name in enumerate(self.feature_names):
            lower = scaled.copy()
            upper = scaled.copy()
            lower[:, index] = np.clip(lower[:, index] - delta, 0.0, 1.0)
            upper[:, index] = np.clip(upper[:, index] + delta, 0.0, 1.0)
            lower_raw = lower * (self.x_max_ - self.x_min_) + self.x_min_
            upper_raw = upper * (self.x_max_ - self.x_min_) + self.x_min_
            effects[name] = float(np.mean(self.predict(upper_raw) - self.predict(lower_raw)) / (2 * delta))
        return effects


@dataclass
class SampleSet:
    x: np.ndarray
    y: np.ndarray
    periods: np.ndarray
    previous_actual: np.ndarray


def build_lag_samples(series: pd.Series, lags: int = 4) -> SampleSet:
    values = series.to_numpy(dtype=float)
    periods = series.index.to_numpy(dtype=str)
    x, y, sample_periods, previous = [], [], [], []
    for index in range(lags, len(values)):
        x.append([values[index - lag] for lag in range(1, lags + 1)])
        y.append(values[index])
        sample_periods.append(periods[index])
        previous.append(values[index - 1])
    return SampleSet(np.asarray(x), np.asarray(y), np.asarray(sample_periods), np.asarray(previous))


def build_one_step_samples(frame: pd.DataFrame, features: Sequence[str], target: str) -> SampleSet:
    x = frame.loc[:, features].iloc[:-1].to_numpy(dtype=float)
    y = frame[target].iloc[1:].to_numpy(dtype=float)
    periods = frame.index.to_numpy(dtype=str)[1:]
    previous = frame[target].iloc[:-1].to_numpy(dtype=float)
    return SampleSet(x, y, periods, previous)


def split_mask(periods: np.ndarray, split: str) -> np.ndarray:
    periods = np.asarray(periods, dtype=str)
    if split == "train":
        return periods <= "2018Q4"
    if split == "validation":
        return (periods >= "2019Q1") & (periods <= "2022Q4")
    if split == "test":
        return (periods >= "2023Q1") & (periods <= "2025Q4")
    raise ValueError(f"Неизвестная выборка: {split}")

