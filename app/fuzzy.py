from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_RULE_DIR = Path(
    os.getenv("PIPELINE_RULE_DIR", PROJECT_ROOT / "colab" / "colab_kirill")
)
if not PIPELINE_RULE_DIR.is_absolute():
    PIPELINE_RULE_DIR = PROJECT_ROOT / PIPELINE_RULE_DIR


OUTPUT_TERMS = (
    "катастрофа",
    "плохое",
    "удовлетворительное",
    "хорошее",
    "отличное",
    "превосходное",
)


def trimf(x: float, a: float, b: float, c: float) -> float:
    """Треугольная функция принадлежности с корректными плечами."""
    value = float(x)
    if value <= a or value >= c:
        return 0.0
    if value == b:
        return 1.0
    if value < b:
        return 1.0 if b == a else (value - a) / (b - a)
    return 1.0 if c == b else (c - value) / (c - b)


def trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    """Трапециевидная функция принадлежности."""
    value = float(x)
    if value <= a or value >= d:
        return 0.0
    if b <= value <= c:
        return 1.0
    if value < b:
        return 1.0 if b == a else (value - a) / (b - a)
    return 1.0 if d == c else (d - value) / (d - c)


class LinguisticVariable:
    """Лингвистическая переменная из notebook Кирилла."""

    def __init__(self, name: str, universe_min: float, universe_max: float):
        self.name = name
        self.universe_min = float(universe_min)
        self.universe_max = float(universe_max)
        self.terms: dict[str, tuple[str, tuple[float, ...]]] = {}

    def add_term(self, term_name: str, mf_type: str, params: Sequence[float]) -> None:
        if mf_type not in {"trimf", "trapmf"}:
            raise ValueError(f"Неизвестный тип функции принадлежности: {mf_type}")
        expected = 3 if mf_type == "trimf" else 4
        if len(params) != expected:
            raise ValueError(f"{mf_type} ожидает {expected} параметра")
        self.terms[term_name] = (mf_type, tuple(float(value) for value in params))

    def fuzzify(self, x: float, term_name: str) -> float:
        try:
            mf_type, params = self.terms[term_name]
        except KeyError as error:
            raise ValueError(f"Терм «{term_name}» не найден") from error
        return trimf(x, *params) if mf_type == "trimf" else trapmf(x, *params)

    def get_all_memberships(self, x: float) -> dict[str, float]:
        return {term: self.fuzzify(x, term) for term in self.terms}


class FuzzySystem:
    """Mamdani-свёртка: min-активация, max-агрегация, centroid."""

    def __init__(self, points: int = 1000):
        self.inputs: dict[str, LinguisticVariable] = {}
        self.output: tuple[str, LinguisticVariable] | None = None
        self.rules: list[tuple[dict[str, str], str]] = []
        self.points = int(points)

    def add_input(self, name: str, variable: LinguisticVariable) -> None:
        self.inputs[name] = variable

    def set_output(self, name: str, variable: LinguisticVariable) -> None:
        self.output = (name, variable)

    def add_rule(self, premise: Mapping[str, str], consequent: str) -> None:
        self.rules.append((dict(premise), consequent))

    def compute(self, inputs_values: Mapping[str, float]) -> float:
        if self.output is None:
            raise ValueError("Выходная переменная не установлена")
        missing = set(self.inputs) - set(inputs_values)
        if missing:
            raise ValueError(f"Не заданы входы нечёткой системы: {sorted(missing)}")

        memberships = {
            name: variable.get_all_memberships(float(inputs_values[name]))
            for name, variable in self.inputs.items()
        }
        _, output_var = self.output
        aggregated = {term: 0.0 for term in output_var.terms}
        for premise, consequent in self.rules:
            strength = min(memberships[name].get(term, 0.0) for name, term in premise.items())
            aggregated[consequent] = max(aggregated[consequent], strength)
        return self._defuzzify(aggregated, output_var)

    def _defuzzify(
        self,
        aggregated: Mapping[str, float],
        output_var: LinguisticVariable,
    ) -> float:
        x_values = np.linspace(output_var.universe_min, output_var.universe_max, self.points)
        combined = np.zeros_like(x_values)
        for term_name, strength in aggregated.items():
            if strength <= 0.0:
                continue
            membership = np.asarray(
                [output_var.fuzzify(value, term_name) for value in x_values], dtype=float
            )
            combined = np.maximum(combined, np.minimum(strength, membership))
        denominator = float(combined.sum())
        if denominator <= 1e-12:
            return 0.0
        return float(np.dot(x_values, combined) / denominator)


# Исторические строки consequents оставлены только для чтения старых коммитов.
# Runtime их не использует: канонические правила загружаются из *_rules.json.
RULE_A = (
    "0001100111011121112211223001110111211122112231223301112112221222322233223340"
    "1112112232223322334233440112211223223342334433445"
)
RULE_B = (
    "000011112011112122112122223011112122112122223122223233112122223122223233223233334"
    "011112122112122223122223233112122223122223233223233334122223233223233334233334344"
    "112122223122223233223233334122223233223233334233334344223233334233334344334344455"
    "011112122112122223122223233112122223122223233223233334122223233223233334233334344"
    "112122223122223233223233334122223233223233334233334344223233334233334344334344455"
    "122223233223233334233334344223233334233334344334344455233334344334344455344445455"
    "112122223122223233223233334122223233223233334233334344223233334233334344334344455"
    "223233334233334344334344455233334344334344455344445455334344455344445455445455555"
    "233334344334344455344445455334344455344445455445455555344445455445455555455555555"
)
RULE_C = (
    "0001101111011121112211223001110111211122112231223301112112221222322233223341"
    "1122122332233423344334451122322334233443344534455"
)
RULE_D = (
    "001112122011122223112223233112122223122223233223233334122223233223233334233334345"
)


@dataclass(frozen=True)
class MembershipTermSpec:
    name: str
    mf_type: str
    params: tuple[float, ...]


@dataclass(frozen=True)
class LinguisticVariableSpec:
    name: str
    universe_min: float
    universe_max: float
    terms: tuple[MembershipTermSpec, ...]


def _term(name: str, params: Sequence[float], mf_type: str = "trimf") -> MembershipTermSpec:
    return MembershipTermSpec(name, mf_type, tuple(float(value) for value in params))


def _variable(
    name: str,
    universe_min: float,
    universe_max: float,
    *terms: MembershipTermSpec,
) -> LinguisticVariableSpec:
    return LinguisticVariableSpec(name, float(universe_min), float(universe_max), tuple(terms))


def _build_variable(spec: LinguisticVariableSpec) -> LinguisticVariable:
    variable = LinguisticVariable(spec.name, spec.universe_min, spec.universe_max)
    for term in spec.terms:
        variable.add_term(term.name, term.mf_type, term.params)
    return variable


STANDARD_OUTPUT = _variable(
    "Индекс качества", 1, 100,
    _term("катастрофа", (1, 5, 20)),
    _term("плохое", (15, 28, 40)),
    _term("удовлетворительное", (35, 50, 65)),
    _term("хорошее", (60, 72, 84)),
    _term("отличное", (78, 88, 95)),
    _term("превосходное", (90, 97, 100)),
)

TRANSIT_WELLBEING_OUTPUT = _variable(
    "Индекс благополучия дорог", 1, 100,
    _term("катастрофа", (1, 15, 25)),
    _term("плохое", (15, 30, 45)),
    _term("удовлетворительное", (35, 50, 65)),
    _term("хорошее", (55, 70, 85)),
    _term("отличное", (75, 85, 95)),
    _term("превосходное", (85, 100, 100)),
)

PARKING_OUTPUT = _variable(
    "Индекс качества парковок и безопасности движения", 10, 100,
    _term("катастрофа", (10, 15, 28)),
    _term("плохое", (23, 35, 48)),
    _term("удовлетворительное", (43, 55, 68)),
    _term("хорошее", (63, 73, 84)),
    _term("отличное", (78, 87, 95)),
    _term("превосходное", (90, 96, 100)),
)


@dataclass(frozen=True)
class FuzzyIndexSpec:
    id: str
    label: str
    features: tuple[str, ...]
    variables: tuple[LinguisticVariableSpec, ...]
    output: LinguisticVariableSpec
    rule_inputs: tuple[str, ...]
    rule_filename: str

    @property
    def term_counts(self) -> tuple[int, ...]:
        return tuple(len(variable.terms) for variable in self.variables)

    @property
    def rule_count(self) -> int:
        return len(load_rule_definitions(self))


FUZZY_INDEX_SPECS = (
    FuzzyIndexSpec(
        "urban_environment",
        "Качество современной городской среды",
        ("бюджет_дворы_pct", "дворы_благоустроено_ед", "удовлетворенность_средой_дворы_pct"),
        (
            _variable("Исполнение бюджета, %", 60, 100,
                _term("очень_низкое", (60, 63, 68)), _term("низкое", (65, 70, 75)),
                _term("среднее", (72, 78, 84)), _term("высокое", (80, 86, 92)),
                _term("очень_высокое", (88, 94, 100))),
            _variable("Благоустроенные дворы, ед. (log1p)", np.log1p(10), np.log1p(70),
                _term("очень_мало", np.log1p([10, 15, 22])), _term("мало", np.log1p([18, 25, 32])),
                _term("средне", np.log1p([28, 35, 42])), _term("много", np.log1p([38, 45, 52])),
                _term("очень_много", np.log1p([48, 55, 70]))),
            _variable("Удовлетворённость городской средой, %", 30, 60,
                _term("очень_низкая", (30, 33, 37)), _term("низкая", (34, 38, 42)),
                _term("средняя", (39, 43, 47)), _term("высокая", (44, 48, 52)),
                _term("очень_высокая", (49, 53, 60))),
        ),
        STANDARD_OUTPUT,
        ("budget", "yards", "satisfaction"),
        "urban_city_area_rules.json",
    ),
    FuzzyIndexSpec(
        "road_quality_dtc",
        "Качество дорог дорожного комплекса",
        ("дороги_отремонт_км_A", "пассажиропоток_тыс_A", "рейсы_расписание_pct_A", "скорость_магистрали_A_кмч", "дтп_10тыс_A", "срок_устранения_деф_сут_A"),
        (
            _variable("Отремонтированные дороги, км", 15, 75,
                _term("мало", (15, 25, 45)), _term("средне", (35, 55, 65)), _term("много", (50, 65, 75))),
            _variable("Пассажиропоток, тыс. поездок (log1p)", np.log1p(80), np.log1p(245),
                _term("низкий", np.log1p([80, 95, 130])), _term("средний", np.log1p([115, 150, 185])),
                _term("высокий", np.log1p([165, 200, 245]))),
            _variable("Рейсы по расписанию, %", 48, 73,
                _term("низкое", (48, 52, 57)), _term("среднее", (55, 60, 65)), _term("высокое", (63, 68, 73))),
            _variable("Средняя скорость, км/ч", 13, 27,
                _term("низкая", (13, 16, 19)), _term("средняя", (18, 20, 22)), _term("высокая", (21, 24, 27))),
            _variable("ДТП на 10 тыс. жителей", 22, 44,
                _term("низкое", (22, 25, 29)), _term("среднее", (27, 32, 37)), _term("высокое", (34, 39, 44))),
            _variable("Срок устранения дефектов, сут.", 20, 46,
                _term("быстро", (20, 24, 30)), _term("средне", (28, 33, 38)), _term("медленно", (35, 41, 46))),
        ),
        STANDARD_OUTPUT,
        ("roads", "passenger", "schedule", "speed", "accident", "defect"),
        "transport_r1_rules.json",
    ),
    FuzzyIndexSpec(
        "road_wellbeing_dtc",
        "Благополучие дорог дорожного комплекса",
        ("дороги_норматив_pct_A", "бюджет_трансп_A_pct", "переходы_регулируем_ед_A"),
        (
            _variable("Дороги в нормативном состоянии, %", 40, 53,
                _term("очень_низкое", (40, 41.5, 43.5)), _term("низкое", (42, 44, 46)),
                _term("среднее", (44.5, 46.5, 48.5)), _term("высокое", (47, 49, 51)),
                _term("очень_высокое", (49.5, 51.5, 53))),
            _variable("Исполнение бюджета, %", 68, 96,
                _term("очень_низкий", (68, 70.5, 75)), _term("низкий", (73, 77, 81)),
                _term("средний", (79, 83, 87)), _term("высокий", (85, 88.5, 92)),
                _term("очень_высокий", (90, 93, 96))),
            _variable("Регулируемые переходы, ед.", 10, 40,
                _term("очень_мало", (10, 13, 18)), _term("мало", (15, 20, 25)),
                _term("средне", (22, 27, 32)), _term("много", (28, 33, 36)),
                _term("очень_много", (34, 37, 40))),
        ),
        STANDARD_OUTPUT,
        ("norm", "budget", "crossing"),
        "transport_r2_rules.json",
    ),
    FuzzyIndexSpec(
        "accessible_environment",
        "Удовлетворённость доступной средой",
        ("бюджет_соцподдержка_pct", "мероприятия_завершено_ед", "получатели_адрподдержки_чел"),
        (
            _variable("Исполнение бюджета, %", 64, 97,
                _term("очень_низкое", (64, 67, 72)), _term("низкое", (70, 74.5, 79)),
                _term("среднее", (77, 81.5, 86)), _term("высокое", (84, 88.5, 93)),
                _term("очень_высокое", (90.5, 94, 97))),
            _variable("Завершённые мероприятия, ед. (log1p)", np.log1p(3), np.log1p(17),
                _term("очень_мало", np.log1p([3, 4.5, 6.5])), _term("мало", np.log1p([5.5, 7.5, 9.5])),
                _term("средне", np.log1p([8, 10, 12])), _term("много", np.log1p([10.5, 12.5, 14.5])),
                _term("очень_много", np.log1p([13, 15, 17]))),
            _variable("Получатели адресной поддержки, чел.", 3000, 5300,
                _term("очень_мало", (3000, 3150, 3450)), _term("мало", (3350, 3650, 3950)),
                _term("средне", (3850, 4150, 4450)), _term("много", (4350, 4650, 4950)),
                _term("очень_много", (4850, 5050, 5300))),
        ),
        STANDARD_OUTPUT,
        ("budget", "events", "support"),
        "available_area_rules.json",
    ),
    FuzzyIndexSpec(
        "public_spaces",
        "Качество общественных пространств",
        ("бюджет_обществ_территории_pct", "территории_благоустроено_ед", "удовлетворенность_средой_терр_pct"),
        (
            _variable("Исполнение бюджета, %", 65, 98,
                _term("очень_низкое", (65, 68, 73)), _term("низкое", (71, 75.5, 80)),
                _term("среднее", (78, 82.5, 87)), _term("высокое", (85, 89.5, 94)),
                _term("очень_высокое", (91.5, 95, 98))),
            _variable("Благоустроенные территории, ед.", 7, 24,
                _term("очень_мало", (7, 8.5, 11)), _term("мало", (10, 12.5, 15)),
                _term("средне", (13.5, 16, 18.5)), _term("много", (17, 19.5, 22)),
                _term("очень_много", (20.5, 22.5, 24))),
            _variable("Удовлетворённость, %", 51, 65,
                _term("очень_низкая", (51, 52.5, 54.5)), _term("низкая", (53.5, 55.5, 57.5)),
                _term("средняя", (56.5, 58.5, 60.5)), _term("высокая", (59.5, 61.5, 63.5)),
                _term("очень_высокая", (62.5, 64.5, 65))),
        ),
        STANDARD_OUTPUT,
        ("budget", "territory", "satisfaction"),
        "public_spaces_rules.json",
    ),
    FuzzyIndexSpec(
        "road_quality_transit",
        "Качество дорог общественного транспорта",
        ("дороги_отремонт_км_B", "пассажиропоток_тыс_B", "рейсы_расписание_pct_B", "скорость_магистрали_B_кмч", "дтп_10тыс_B", "срок_устранения_деф_сут_B"),
        (
            _variable("Отремонтированные дороги, км", 10, 48,
                _term("мало", (10, 15, 25)), _term("средне", (20, 30, 40)), _term("много", (35, 42, 48))),
            _variable("Пассажиропоток, тыс. поездок (log1p)", np.log1p(30), np.log1p(115),
                _term("низкий", np.log1p([30, 45, 65])), _term("средний", np.log1p([55, 75, 95])),
                _term("высокий", np.log1p([85, 100, 115]))),
            _variable("Рейсы по расписанию, %", 55, 72,
                _term("низкое", (55, 57, 60)), _term("среднее", (58, 62, 66)), _term("высокое", (64, 68, 72))),
            _variable("Средняя скорость, км/ч", 22, 31.5,
                _term("низкая", (22, 23.5, 25.5)), _term("средняя", (24.5, 26.5, 28.5)),
                _term("высокая", (27.5, 29.5, 31.5))),
            _variable("ДТП на 10 тыс. жителей (log1p)", np.log1p(8), np.log1p(27),
                _term("низкое", np.log1p([8, 10, 13])), _term("среднее", np.log1p([12, 15, 18])),
                _term("высокое", np.log1p([16, 20, 27]))),
            _variable("Срок устранения дефектов, сут.", 3, 6.8,
                _term("быстро", (3, 3.5, 4.2)), _term("средне", (3.8, 4.5, 5.2)),
                _term("медленно", (4.8, 5.5, 6.8))),
        ),
        STANDARD_OUTPUT,
        ("roads", "passenger", "schedule", "speed", "accident", "defect"),
        "transport_r1_rules.json",
    ),
    FuzzyIndexSpec(
        "road_wellbeing_transit",
        "Благополучие дорог общественного транспорта",
        ("дороги_норматив_pct_B", "бюджет_трансп_B_pct", "переходы_регулируем_ед_B"),
        (
            _variable("Дороги в нормативном состоянии, %", 50, 66,
                _term("очень_низкое", (50, 52, 55)), _term("низкое", (53, 56, 58.5)),
                _term("среднее", (56, 58.5, 61)), _term("высокое", (59, 62, 64.5)),
                _term("очень_высокое", (62, 64.5, 66))),
            _variable("Исполнение бюджета, %", 68, 96,
                _term("очень_низкий", (68, 71, 76)), _term("низкий", (73, 78, 81.5)),
                _term("средний", (78, 81.7, 85.5)), _term("высокий", (83, 88, 92)),
                _term("очень_высокий", (89, 93, 96))),
            _variable("Регулируемые переходы, ед. (log1p)", 2.7, 4.2,
                _term("очень_мало", (2.7, 2.9, 3.2)), _term("мало", (3.0, 3.25, 3.46)),
                _term("средне", (3.25, 3.47, 3.71)), _term("много", (3.5, 3.8, 4.0)),
                _term("очень_много", (3.8, 4.1, 4.2))),
        ),
        TRANSIT_WELLBEING_OUTPUT,
        ("norm", "budget", "crossing"),
        "transport_r2_rules.json",
    ),
    FuzzyIndexSpec(
        "parking_safety",
        "Качество парковок и безопасности движения",
        ("бюджет_дороги_C_pct", "дороги_отремонт_км_C", "дороги_норматив_pct_C", "срок_устранения_деф_сут_C"),
        (
            _variable("Бюджет, %", 60, 100,
                _term("низкий", (60, 68, 76)), _term("средний", (74, 82, 90)), _term("высокий", (86, 94, 100))),
            _variable("Дороги, км", 1, 5.5,
                _term("мало", (1, 1.8, 2.8)), _term("средне", (2.4, 3.2, 4.2)), _term("много", (3.8, 4.6, 5.5))),
            _variable("Нормативность, %", 57, 68,
                _term("низкая", (57, 58.8, 61)), _term("средняя", (59.5, 62, 64.5)), _term("высокая", (63, 65.5, 68))),
            _variable("Срок устранения, сут.", 16, 42,
                _term("быстро", (16, 19, 24)), _term("средне", (22, 28, 34)), _term("медленно", (32, 38, 42))),
        ),
        PARKING_OUTPUT,
        ("budget", "roads", "norm", "defect"),
        "parking_and_security_rules.json",
    ),
)


def load_rule_definitions(
    spec: FuzzyIndexSpec,
) -> tuple[tuple[dict[str, str], str], ...]:
    path = PIPELINE_RULE_DIR / spec.rule_filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Не найден канонический файл правил Pipeline: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать правила {path.name}: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Файл {path.name} должен содержать непустой список правил")

    input_mapping = dict(zip(spec.rule_inputs, spec.features, strict=True))
    allowed_terms = {
        rule_input: {term.name for term in variable.terms}
        for rule_input, variable in zip(spec.rule_inputs, spec.variables, strict=True)
    }
    allowed_outputs = {term.name for term in spec.output.terms}
    output: list[tuple[dict[str, str], str]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], dict):
            raise ValueError(f"Некорректное правило {index} в {path.name}")
        premise, consequent = item
        if set(premise) != set(spec.rule_inputs):
            raise ValueError(f"Правило {index} в {path.name} содержит неверный набор входов")
        for name, term in premise.items():
            if term not in allowed_terms[name]:
                raise ValueError(f"Неизвестный терм {name}={term} в правиле {index} файла {path.name}")
        if consequent not in allowed_outputs:
            raise ValueError(f"Неизвестный выход {consequent} в правиле {index} файла {path.name}")
        output.append(
            ({input_mapping[name]: str(term) for name, term in premise.items()}, str(consequent))
        )
    return tuple(output)


def build_fuzzy_system(spec: FuzzyIndexSpec) -> FuzzySystem:
    system = FuzzySystem()
    for feature, variable_spec in zip(spec.features, spec.variables, strict=True):
        system.add_input(feature, _build_variable(variable_spec))
    system.set_output(spec.id, _build_variable(spec.output))
    for premise, consequent in load_rule_definitions(spec):
        system.add_rule(premise, consequent)
    return system


def calculate_fuzzy_indices(prepared_frame: pd.DataFrame) -> pd.DataFrame:
    """Рассчитывает восемь индексов строго по параметрам ``Pipeline.ipynb``."""
    result = pd.DataFrame(index=prepared_frame.index)
    for spec in FUZZY_INDEX_SPECS:
        missing = set(spec.features) - set(prepared_frame.columns)
        if missing:
            raise KeyError(f"Для индекса {spec.id} отсутствуют признаки: {sorted(missing)}")
        system = build_fuzzy_system(spec)
        result[spec.id] = [
            system.compute(row)
            for row in prepared_frame.loc[:, spec.features].to_dict(orient="records")
        ]
    return result
