from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from dataclasses import dataclass
from itertools import product
from pathlib import Path
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


ANFIS_ARTIFACT_VERSION = 1


class ModelArtifactError(ValueError):
    """Артефакт модели отсутствует, повреждён или не соответствует данным."""


class ANFIS:
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

    def training_signature(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_validation: np.ndarray,
        y_validation: np.ndarray,
        *,
        context: str = "",
    ) -> str:
        """Строит воспроизводимый отпечаток входов и настроек модели."""
        digest = hashlib.sha256()
        digest.update(f"anfis-artifact:{ANFIS_ARTIFACT_VERSION}\n".encode())
        digest.update(context.encode("utf-8"))
        digest.update("\0".join(self.feature_names).encode("utf-8"))
        digest.update(repr(self.sigma_candidates).encode())
        digest.update(repr(self.ridge_candidates).encode())
        for values in (x_train, y_train, x_validation, y_validation):
            array = np.ascontiguousarray(values, dtype=np.float64)
            digest.update(str(array.shape).encode())
            digest.update(array.tobytes())
        return digest.hexdigest()

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
    ) -> "ANFIS":
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

    def _validate_fitted_state(self) -> None:
        arrays = {
            "x_min": self.x_min_,
            "x_max": self.x_max_,
            "centers": self.centers_,
            "rules": self.rules_,
            "theta": self.theta_,
        }
        missing = [name for name, value in arrays.items() if value is None]
        if missing or self.sigma_ is None or self.ridge_ is None or self.validation_rmse_ is None:
            raise ModelArtifactError("ANFIS ещё не обучен: артефакт сохранить нельзя.")

        feature_count = len(self.feature_names)
        rule_count = len(self.rules_)
        expected_shapes = {
            "x_min": (feature_count,),
            "x_max": (feature_count,),
            "centers": (feature_count, 2),
            "rules": (rule_count, feature_count),
            "theta": (rule_count * (feature_count + 1),),
        }
        for name, expected in expected_shapes.items():
            value = np.asarray(arrays[name])
            if value.shape != expected or not np.isfinite(value).all():
                raise ModelArtifactError(f"Некорректный параметр ANFIS {name}: ожидалась форма {expected}.")
        if rule_count < 1 or rule_count > 16:
            raise ModelArtifactError("Число правил ANFIS должно быть от 1 до 16.")
        if not np.isin(self.rules_, (0, 1)).all():
            raise ModelArtifactError("Индексы функций принадлежности ANFIS должны быть 0 или 1.")
        if not np.isfinite((self.sigma_, self.ridge_, self.validation_rmse_)).all():
            raise ModelArtifactError("Скалярные параметры ANFIS должны быть конечными.")
        if self.sigma_ <= 0 or self.ridge_ < 0 or self.validation_rmse_ < 0:
            raise ModelArtifactError("Ширина, регуляризация и RMSE ANFIS имеют недопустимое значение.")

    def save(self, path: Path | str, *, training_signature: str) -> Path:
        """Атомарно сохраняет модель без pickle-кода и сторонних зависимостей."""
        self._validate_fitted_state()
        if len(training_signature) != 64:
            raise ValueError("training_signature должен быть SHA-256 отпечатком.")

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                np.savez_compressed(
                    temporary,
                    artifact_version=np.asarray([ANFIS_ARTIFACT_VERSION], dtype=np.int64),
                    model_type=np.asarray(["anfis-sugeno"], dtype=np.str_),
                    feature_names=np.asarray(self.feature_names, dtype=np.str_),
                    training_signature=np.asarray([training_signature], dtype=np.str_),
                    x_min=np.asarray(self.x_min_, dtype=np.float64),
                    x_max=np.asarray(self.x_max_, dtype=np.float64),
                    centers=np.asarray(self.centers_, dtype=np.float64),
                    rules=np.asarray(self.rules_, dtype=np.int64),
                    sigma=np.asarray([self.sigma_], dtype=np.float64),
                    ridge=np.asarray([self.ridge_], dtype=np.float64),
                    theta=np.asarray(self.theta_, dtype=np.float64),
                    validation_rmse=np.asarray([self.validation_rmse_], dtype=np.float64),
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        expected_features: Sequence[str],
        expected_training_signature: str,
    ) -> "ANFIS":
        """Загружает и строго проверяет безопасный ANFIS-артефакт."""
        source = Path(path)
        try:
            with np.load(source, allow_pickle=False) as artifact:
                required = {
                    "artifact_version",
                    "model_type",
                    "feature_names",
                    "training_signature",
                    "x_min",
                    "x_max",
                    "centers",
                    "rules",
                    "sigma",
                    "ridge",
                    "theta",
                    "validation_rmse",
                }
                missing = required.difference(artifact.files)
                if missing:
                    raise ModelArtifactError(f"В артефакте ANFIS нет полей: {', '.join(sorted(missing))}.")
                version = int(np.asarray(artifact["artifact_version"]).item())
                model_type = str(np.asarray(artifact["model_type"]).item())
                features = [str(value) for value in np.asarray(artifact["feature_names"]).tolist()]
                signature = str(np.asarray(artifact["training_signature"]).item())
                if version != ANFIS_ARTIFACT_VERSION or model_type != "anfis-sugeno":
                    raise ModelArtifactError("Версия или тип артефакта ANFIS не поддерживается.")
                if features != list(expected_features):
                    raise ModelArtifactError("Состав или порядок входов ANFIS изменился.")
                if signature != expected_training_signature:
                    raise ModelArtifactError("ANFIS обучен на другой версии данных или настроек.")

                model = cls(features)
                model.x_min_ = np.asarray(artifact["x_min"], dtype=float)
                model.x_max_ = np.asarray(artifact["x_max"], dtype=float)
                model.centers_ = np.asarray(artifact["centers"], dtype=float)
                model.rules_ = np.asarray(artifact["rules"], dtype=int)
                model.sigma_ = float(np.asarray(artifact["sigma"]).item())
                model.ridge_ = float(np.asarray(artifact["ridge"]).item())
                model.theta_ = np.asarray(artifact["theta"], dtype=float)
                model.validation_rmse_ = float(np.asarray(artifact["validation_rmse"]).item())
        except ModelArtifactError:
            raise
        except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile) as error:
            raise ModelArtifactError(f"Не удалось прочитать артефакт ANFIS {source.name}: {error}") from error
        model._validate_fitted_state()
        return model

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


class RobustScaler:
    """Минимальный RobustScaler: медиана и межквартильный размах."""

    def __init__(self) -> None:
        self.center_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, values: np.ndarray) -> "RobustScaler":
        array = np.asarray(values, dtype=float)
        self.center_ = np.median(array, axis=0)
        q1, q3 = np.percentile(array, [25, 75], axis=0)
        self.scale_ = np.where(np.abs(q3 - q1) < 1e-12, 1.0, q3 - q1)
        return self

    def transform(self, values: np.ndarray) -> np.ndarray:
        if self.center_ is None or self.scale_ is None:
            raise RuntimeError("RobustScaler ещё не обучен")
        return (np.asarray(values, dtype=float) - self.center_) / self.scale_

    def inverse_transform(self, values: np.ndarray) -> np.ndarray:
        if self.center_ is None or self.scale_ is None:
            raise RuntimeError("RobustScaler ещё не обучен")
        return np.asarray(values, dtype=float) * self.scale_ + self.center_


class PipelineANFIS:
    """NumPy-перенос архитектуры ANFIS из ``Pipeline.ipynb``.

    Шесть гауссовых правил, общий sigma на правило и линейные консеквенты.
    Параметры обучаются Adam с теми же основными гиперпараметрами notebook.
    """

    def __init__(
        self,
        feature_names: Sequence[str],
        *,
        n_rules: int = 6,
        epochs: int = 500,
        learning_rate: float = 0.05,
        patience: int = 70,
        weight_decay: float = 1e-3,
        random_state: int = 42,
    ) -> None:
        self.feature_names = list(feature_names)
        self.n_rules = int(n_rules)
        self.epochs = int(epochs)
        self.learning_rate = float(learning_rate)
        self.patience = int(patience)
        self.weight_decay = float(weight_decay)
        self.random_state = int(random_state)
        self.centers_: np.ndarray | None = None
        self.sigmas_: np.ndarray | None = None
        self.consequents_: np.ndarray | None = None
        self.validation_rmse_: float | None = None
        self.trained_epochs_: int = 0

    @property
    def rule_count(self) -> int:
        return self.n_rules

    @staticmethod
    def _kmeans_plus_plus(array: np.ndarray, clusters: int, rng: np.random.RandomState) -> np.ndarray:
        centers = [array[rng.randint(len(array))].copy()]
        for _ in range(1, clusters):
            squared = np.min(
                np.sum((array[:, None, :] - np.asarray(centers)[None, :, :]) ** 2, axis=2),
                axis=1,
            )
            total = float(squared.sum())
            index = rng.randint(len(array)) if total <= 1e-12 else rng.choice(len(array), p=squared / total)
            centers.append(array[index].copy())
        return np.asarray(centers)

    def _kmeans(self, array: np.ndarray) -> np.ndarray:
        best: tuple[float, np.ndarray] | None = None
        for run in range(10):
            rng = np.random.RandomState(self.random_state + run)
            centers = self._kmeans_plus_plus(array, self.n_rules, rng)
            for _ in range(100):
                distances = np.sum((array[:, None, :] - centers[None, :, :]) ** 2, axis=2)
                labels = np.argmin(distances, axis=1)
                updated = centers.copy()
                for cluster in range(self.n_rules):
                    members = array[labels == cluster]
                    if len(members):
                        updated[cluster] = members.mean(axis=0)
                if np.allclose(updated, centers, atol=1e-7):
                    centers = updated
                    break
                centers = updated
            inertia = float(np.min(np.sum((array[:, None, :] - centers[None, :, :]) ** 2, axis=2), axis=1).sum())
            if best is None or inertia < best[0]:
                best = (inertia, centers.copy())
        assert best is not None
        return best[1]

    def _forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.centers_ is None or self.sigmas_ is None or self.consequents_ is None:
            raise RuntimeError("PipelineANFIS ещё не обучен")
        diff = x[:, None, :] - self.centers_[None, :, :]
        sigma = self.sigmas_[None, :, None]
        memberships = np.exp(-0.5 * (diff / sigma) ** 2)
        firing = np.prod(memberships, axis=2)
        normalized = firing / np.maximum(firing.sum(axis=1, keepdims=True), 1e-8)
        x_bias = np.column_stack([np.ones(len(x)), x])
        rule_outputs = x_bias @ self.consequents_.T
        prediction = np.sum(normalized * rule_outputs, axis=1)
        return prediction, normalized, rule_outputs

    def fit(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_validation: np.ndarray,
        y_validation: np.ndarray,
    ) -> "PipelineANFIS":
        x_train = np.asarray(x_train, dtype=float)
        y_train = np.asarray(y_train, dtype=float).reshape(-1)
        x_validation = np.asarray(x_validation, dtype=float)
        y_validation = np.asarray(y_validation, dtype=float).reshape(-1)
        if x_train.shape[1] != len(self.feature_names):
            raise ValueError("Число входов PipelineANFIS не совпадает с feature_names")
        if len(x_train) < self.n_rules:
            raise ValueError("Для инициализации ANFIS недостаточно строк")

        self.centers_ = self._kmeans(x_train)
        distances = np.linalg.norm(x_train[:, None, :] - self.centers_[None, :, :], axis=2)
        self.sigmas_ = np.clip(distances.mean(axis=0), 0.1, 1.5)
        # Линейная регрессия X(t) -> y(t+1) даёт консеквентам устойчивую стартовую
        # точку; Adam затем уточняет локальные правила по validation без доступа к test.
        x_bias = np.column_stack([np.ones(len(x_train)), x_train])
        linear_consequent = np.linalg.lstsq(x_bias, y_train, rcond=None)[0]
        self.consequents_ = np.tile(linear_consequent, (self.n_rules, 1))

        parameters = [self.centers_, self.sigmas_, self.consequents_]
        first_moments = [np.zeros_like(value) for value in parameters]
        second_moments = [np.zeros_like(value) for value in parameters]
        initial_validation = self.predict(x_validation)
        best_loss = float(np.mean((initial_validation - y_validation) ** 2))
        best_state: tuple[np.ndarray, np.ndarray, np.ndarray] | None = tuple(
            value.copy() for value in parameters
        )
        patience_counter = 0

        for epoch in range(1, self.epochs + 1):
            prediction, normalized, rule_outputs = self._forward(x_train)
            error = prediction - y_train
            common = (2.0 / len(x_train)) * error[:, None] * normalized * (rule_outputs - prediction[:, None])
            diff = x_train[:, None, :] - self.centers_[None, :, :]
            sigma = self.sigmas_[None, :, None]
            grad_centers = np.sum(common[:, :, None] * diff / (sigma**2), axis=0)
            grad_sigmas = np.sum(common * np.sum(diff**2, axis=2) / (self.sigmas_[None, :] ** 3), axis=0)
            x_bias = np.column_stack([np.ones(len(x_train)), x_train])
            grad_consequents = ((2.0 / len(x_train)) * error[:, None] * normalized).T @ x_bias
            gradients = [grad_centers, grad_sigmas, grad_consequents]

            for index, (parameter, gradient) in enumerate(zip(parameters, gradients, strict=True)):
                gradient = gradient + self.weight_decay * parameter
                first_moments[index] = 0.9 * first_moments[index] + 0.1 * gradient
                second_moments[index] = 0.999 * second_moments[index] + 0.001 * gradient**2
                m_hat = first_moments[index] / (1.0 - 0.9**epoch)
                v_hat = second_moments[index] / (1.0 - 0.999**epoch)
                parameter -= self.learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)
            self.sigmas_[:] = np.clip(np.abs(self.sigmas_), 0.05, 2.5)

            validation_prediction = self.predict(x_validation)
            validation_loss = float(np.mean((validation_prediction - y_validation) ** 2))
            if validation_loss < best_loss:
                best_loss = validation_loss
                best_state = tuple(value.copy() for value in parameters)
                patience_counter = 0
            else:
                patience_counter += 1
            self.trained_epochs_ = epoch
            if patience_counter >= self.patience:
                break

        assert best_state is not None
        self.centers_[:], self.sigmas_[:], self.consequents_[:] = best_state
        self.validation_rmse_ = float(np.sqrt(best_loss))
        return self

    def predict(self, values: np.ndarray) -> np.ndarray:
        return self._forward(np.asarray(values, dtype=float))[0]


# Совместимость для внешнего кода предыдущей версии.
ANFISRegressor = ANFIS


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

