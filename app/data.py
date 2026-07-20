from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .config import DATA_PATH, SHEETS, TEST_END, TRAIN_END, TRAIN_START


FINANCING = "Финансирование программы, млн руб."
BUDGET_EXECUTION = "Исполнение бюджета, %"
REPAIRED_ROADS = "Отремонтированные дороги, км"
ROAD_CONDITION = "Дороги в нормативном состоянии, %"
PASSENGER_FLOW = "Пассажиропоток, тыс. поездок"
REGULARITY = "Рейсы по расписанию, %"
AVERAGE_SPEED = "Средняя скорость на магистралях, км/ч"
ACCIDENTS = "ДТП на 10 тыс. жителей"
STOPS = "Обустроенные остановки, ед."
INFO_PANELS = "Остановки с инфотабло, %"
ACTIVE_INFRA = "Вело- и пешеходная инфраструктура, км"
CROSSINGS = "Регулируемые переходы, ед."
LIGHTING = "Доля освещенных улиц, %"

EXPECTED_PERIODS = [f"{year}Q{quarter}" for year in range(2006, 2026) for quarter in range(1, 5)]


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    kind: str
    unit: str
    description: str


NODE_SPECS = [
    NodeSpec("road_budget", "Финансирование дорог", "controllable", "млн руб.", "Финансирование дорожной программы."),
    NodeSpec("transit_budget", "Финансирование транспорта", "controllable", "млн руб.", "Финансирование городского общественного транспорта."),
    NodeSpec("safety_budget", "Финансирование безопасности", "controllable", "млн руб.", "Ресурсы программы безопасности движения."),
    NodeSpec("active_mobility_budget", "Финансирование активной мобильности", "controllable", "млн руб.", "Ресурсы вело-пешеходной программы."),
    NodeSpec("management_efficiency", "Исполнение программ", "controllable", "%", "Среднее исполнение бюджетов пяти транспортных программ."),
    NodeSpec("road_repair", "Ремонт дорог", "intermediate", "км", "Протяжённость отремонтированных дорог."),
    NodeSpec("road_condition", "Нормативное состояние дорог", "intermediate", "%", "Доля дорог в нормативном состоянии."),
    NodeSpec("lighting", "Освещение улиц", "intermediate", "%", "Доля освещённых улиц."),
    NodeSpec("crossings", "Регулируемые переходы", "intermediate", "ед.", "Количество регулируемых переходов."),
    NodeSpec("stops", "Обустроенные остановки", "intermediate", "ед.", "Количество обустроенных остановок."),
    NodeSpec("digital_mobility", "Цифровая мобильность", "intermediate", "%", "Прокси: доля остановок с информационными табло."),
    NodeSpec("active_mobility", "Вело-пешеходная инфраструктура", "intermediate", "км", "Протяжённость вело-пешеходной инфраструктуры."),
    NodeSpec("passenger_demand", "Пассажиропоток", "external", "тыс. поездок", "Спрос на общественный транспорт."),
    NodeSpec("congestion", "Загруженность дорог", "external", "индекс", "Прокси: обратная нормализованная средняя скорость."),
    NodeSpec("transport_regularity", "Регулярность транспорта", "target", "%", "Доля рейсов, выполненных по расписанию."),
    NodeSpec("traffic_safety", "Безопасность движения", "target", "индекс", "Обратный нормализованный уровень ДТП; больше — безопаснее."),
    NodeSpec("accessibility", "Транспортная доступность", "target", "индекс", "Композитный индекс регулярности, скорости, остановок, переходов и активной мобильности."),
]

NODE_IDS = [node.id for node in NODE_SPECS]


@dataclass
class TrainMinMaxScaler:
    minimum: float
    maximum: float
    direction: str = "positive"
    fitted_until: str = TRAIN_END

    @classmethod
    def fit(cls, values: pd.Series, direction: str = "positive") -> "TrainMinMaxScaler":
        numeric = pd.to_numeric(values, errors="coerce").astype(float)
        if numeric.isna().any():
            numeric = numeric.interpolate(limit_direction="both").fillna(numeric.median())
        return cls(float(numeric.min()), float(numeric.max()), direction)

    def transform(self, values: pd.Series | np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        span = self.maximum - self.minimum
        scaled = np.full_like(array, 0.5, dtype=float) if np.isclose(span, 0.0) else (array - self.minimum) / span
        if self.direction == "negative":
            scaled = 1.0 - scaled
        return np.clip(scaled, 0.0, 1.0)

    def inverse(self, values: pd.Series | np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=float)
        if self.direction == "negative":
            array = 1.0 - array
        return self.minimum + array * (self.maximum - self.minimum)


@dataclass
class DataBundle:
    raw: pd.DataFrame
    factors: pd.DataFrame
    scalers: Dict[str, TrainMinMaxScaler]
    sheets: Dict[str, pd.DataFrame]
    source_path: Path


def _load_sheets(path: Path) -> Dict[str, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл данных: {path}")

    loaded = pd.read_excel(path, sheet_name=list(SHEETS.values()), engine="openpyxl")
    result: Dict[str, pd.DataFrame] = {}
    for key, sheet_name in SHEETS.items():
        frame = loaded[sheet_name].copy()
        frame["period"] = frame["period"].astype(str)
        frame = frame.sort_values("period_index").reset_index(drop=True)
        if frame["period"].tolist() != EXPECTED_PERIODS:
            raise ValueError(f"Лист {sheet_name} должен содержать кварталы 2006Q1–2025Q4 без пропусков.")
        if frame.isna().any().any():
            raise ValueError(f"На листе {sheet_name} обнаружены пустые значения.")
        result[key] = frame
    return result


def _series(sheets: Dict[str, pd.DataFrame], sheet: str, column: str) -> pd.Series:
    frame = sheets[sheet]
    if column not in frame.columns:
        raise KeyError(f"На листе {SHEETS[sheet]} отсутствует колонка «{column}».")
    return pd.to_numeric(frame[column], errors="raise").astype(float)


def load_problem_b_data(path: Path = DATA_PATH) -> DataBundle:
    sheets = _load_sheets(path)
    periods = sheets["roads"]["period"].astype(str)
    raw = pd.DataFrame(index=pd.Index(periods, name="period"))

    raw["road_budget"] = _series(sheets, "roads", FINANCING).to_numpy()
    raw["transit_budget"] = _series(sheets, "transit", FINANCING).to_numpy()
    raw["safety_budget"] = _series(sheets, "safety", FINANCING).to_numpy()
    raw["active_mobility_budget"] = _series(sheets, "active", FINANCING).to_numpy()
    raw["management_efficiency"] = np.mean(
        np.column_stack([_series(sheets, key, BUDGET_EXECUTION) for key in SHEETS]), axis=1
    )
    raw["road_repair"] = _series(sheets, "roads", REPAIRED_ROADS).to_numpy()
    raw["road_condition"] = _series(sheets, "roads", ROAD_CONDITION).to_numpy()
    raw["lighting"] = _series(sheets, "lighting", LIGHTING).to_numpy()
    raw["crossings"] = _series(sheets, "safety", CROSSINGS).to_numpy()
    raw["stops"] = _series(sheets, "transit", STOPS).to_numpy()
    raw["digital_mobility"] = _series(sheets, "transit", INFO_PANELS).to_numpy()
    raw["active_mobility"] = _series(sheets, "active", ACTIVE_INFRA).to_numpy()
    raw["passenger_demand"] = _series(sheets, "transit", PASSENGER_FLOW).to_numpy()
    raw["avg_speed"] = _series(sheets, "roads", AVERAGE_SPEED).to_numpy()
    raw["regularity"] = _series(sheets, "transit", REGULARITY).to_numpy()
    raw["accidents"] = _series(sheets, "safety", ACCIDENTS).to_numpy()

    train_mask = (raw.index >= TRAIN_START) & (raw.index <= TRAIN_END)
    directions = {column: "positive" for column in raw.columns}
    directions["avg_speed"] = "negative"
    directions["accidents"] = "negative"
    scalers = {
        column: TrainMinMaxScaler.fit(raw.loc[train_mask, column], directions[column])
        for column in raw.columns
    }

    factors = pd.DataFrame(index=raw.index)
    direct_map = [
        "road_budget", "transit_budget", "safety_budget", "active_mobility_budget",
        "management_efficiency", "road_repair", "road_condition", "lighting", "crossings",
        "stops", "digital_mobility", "active_mobility", "passenger_demand",
    ]
    for column in direct_map:
        factors[column] = scalers[column].transform(raw[column])

    factors["congestion"] = scalers["avg_speed"].transform(raw["avg_speed"])
    factors["transport_regularity"] = scalers["regularity"].transform(raw["regularity"])
    factors["traffic_safety"] = scalers["accidents"].transform(raw["accidents"])

    speed_access = 1.0 - factors["congestion"]
    factors["accessibility"] = (
        0.30 * factors["transport_regularity"]
        + 0.20 * speed_access
        + 0.15 * factors["stops"]
        + 0.15 * factors["crossings"]
        + 0.20 * factors["active_mobility"]
    ).clip(0.0, 1.0)

    raw["congestion"] = factors["congestion"] * 100.0
    raw["accessibility"] = factors["accessibility"] * 100.0

    if list(factors.columns) != NODE_IDS:
        raise RuntimeError("Порядок факторов не совпадает с порядком узлов FCM.")
    if not np.isfinite(factors.to_numpy()).all():
        raise ValueError("После подготовки факторов обнаружены бесконечные или пустые значения.")
    if factors.min().min() < 0.0 or factors.max().max() > 1.0:
        raise ValueError("Факторы FCM должны находиться в диапазоне [0, 1].")
    if raw.index[0] != TRAIN_START or raw.index[-1] != TEST_END:
        raise ValueError("Диапазон данных не совпадает с 2006Q1–2025Q4.")

    return DataBundle(raw=raw, factors=factors, scalers=scalers, sheets=sheets, source_path=path)

