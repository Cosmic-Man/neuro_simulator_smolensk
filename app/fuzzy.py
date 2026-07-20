from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


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

    def __init__(self, points: int = 501):
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
            return 50.0
        return float(np.dot(x_values, combined) / denominator)


THREE_POSITIVE = ("низкое", "среднее", "высокое")
FIVE_POSITIVE = ("очень_низкое", "низкое", "среднее", "высокое", "очень_высокое")

# Полные таблицы consequents из восьми fuzzy-систем notebook Кирилла.
# Цифры — индексы OUTPUT_TERMS, порядок — декартово произведение входных термов.
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


def _term_names(count: int, negative: bool = False) -> tuple[str, ...]:
    if count == 3:
        return ("плохо", "средне", "хорошо") if not negative else ("медленно", "средне", "быстро")
    if count == 5:
        return ("очень_плохо", "плохо", "средне", "хорошо", "очень_хорошо")
    raise ValueError("Поддерживаются только 3 или 5 входных термов")


def _quality_variable(name: str, terms: Sequence[str]) -> LinguisticVariable:
    variable = LinguisticVariable(name, 0.0, 100.0)
    centers = np.linspace(0.0, 100.0, len(terms))
    step = 100.0 / max(len(terms) - 1, 1)
    for term, center in zip(terms, centers, strict=True):
        variable.add_term(term, "trimf", (center - step, center, center + step))
    return variable


def _output_variable() -> LinguisticVariable:
    return _quality_variable("Индекс качества", OUTPUT_TERMS)


@dataclass(frozen=True)
class FuzzyIndexSpec:
    id: str
    label: str
    features: tuple[str, ...]
    term_counts: tuple[int, ...]
    rule_table: str


FUZZY_INDEX_SPECS = (
    FuzzyIndexSpec(
        "urban_environment",
        "Качество современной городской среды",
        ("бюджет_дворы_pct", "дворы_благоустроено_ед", "удовлетворенность_средой_дворы_pct"),
        (5, 5, 5),
        RULE_A,
    ),
    FuzzyIndexSpec(
        "road_quality_dtc",
        "Качество дорог дорожного комплекса",
        ("дороги_отремонт_км_A", "пассажиропоток_тыс_A", "рейсы_расписание_pct_A", "скорость_магистрали_A_кмч", "дтп_10тыс_A", "срок_устранения_деф_сут_A"),
        (3, 3, 3, 3, 3, 3),
        RULE_B,
    ),
    FuzzyIndexSpec(
        "road_wellbeing_dtc",
        "Благополучие дорог дорожного комплекса",
        ("дороги_норматив_pct_A", "бюджет_трансп_A_pct", "переходы_регулируем_ед_A"),
        (5, 5, 5),
        RULE_C,
    ),
    FuzzyIndexSpec(
        "accessible_environment",
        "Удовлетворённость доступной средой",
        ("бюджет_соцподдержка_pct", "мероприятия_завершено_ед", "получатели_адрподдержки_чел"),
        (5, 5, 5),
        RULE_A,
    ),
    FuzzyIndexSpec(
        "public_spaces",
        "Качество общественных пространств",
        ("бюджет_обществ_территории_pct", "территории_благоустроено_ед", "удовлетворенность_средой_терр_pct"),
        (5, 5, 5),
        RULE_A,
    ),
    FuzzyIndexSpec(
        "road_quality_transit",
        "Качество дорог общественного транспорта",
        ("дороги_отремонт_км_B", "пассажиропоток_тыс_B", "рейсы_расписание_pct_B", "скорость_магистрали_B_кмч", "дтп_10тыс_B", "срок_устранения_деф_сут_B"),
        (3, 3, 3, 3, 3, 3),
        RULE_B,
    ),
    FuzzyIndexSpec(
        "road_wellbeing_transit",
        "Благополучие дорог общественного транспорта",
        ("дороги_норматив_pct_B", "бюджет_трансп_B_pct", "переходы_регулируем_ед_B"),
        (5, 5, 5),
        RULE_C,
    ),
    FuzzyIndexSpec(
        "parking_safety",
        "Качество парковок и безопасности движения",
        ("бюджет_дороги_C_pct", "дороги_отремонт_км_C", "дороги_норматив_pct_C", "срок_устранения_деф_сут_C"),
        (3, 3, 3, 3),
        RULE_D,
    ),
)


def build_fuzzy_system(spec: FuzzyIndexSpec) -> FuzzySystem:
    system = FuzzySystem()
    term_sets: list[tuple[str, ...]] = []
    for feature, count in zip(spec.features, spec.term_counts, strict=True):
        terms = _term_names(count)
        term_sets.append(terms)
        system.add_input(feature, _quality_variable(feature, terms))
    system.set_output(spec.id, _output_variable())
    combinations = list(product(*term_sets))
    if len(combinations) != len(spec.rule_table):
        raise RuntimeError(f"Повреждена таблица правил {spec.id}: {len(spec.rule_table)}")
    for combination, output_index in zip(combinations, spec.rule_table, strict=True):
        premise = dict(zip(spec.features, combination, strict=True))
        system.add_rule(premise, OUTPUT_TERMS[int(output_index)])
    return system


def calculate_fuzzy_indices(quality_frame: pd.DataFrame) -> pd.DataFrame:
    """Рассчитывает восемь Colab-индексов по quality-scaled признакам [0, 100]."""
    result = pd.DataFrame(index=quality_frame.index)
    for spec in FUZZY_INDEX_SPECS:
        missing = set(spec.features) - set(quality_frame.columns)
        if missing:
            raise KeyError(f"Для индекса {spec.id} отсутствуют признаки: {sorted(missing)}")
        system = build_fuzzy_system(spec)
        result[spec.id] = [
            system.compute(row)
            for row in quality_frame.loc[:, spec.features].to_dict(orient="records")
        ]
    return result
