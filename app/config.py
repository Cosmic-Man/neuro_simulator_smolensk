from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = Path(
    os.getenv("SMOLENSK_DATA_PATH", PROJECT_ROOT / "data" / "smolensk_development.xlsx")
)
STATIC_DIR = PROJECT_ROOT / "app" / "static"

TRAIN_START = "2006Q1"
TRAIN_END = "2018Q4"
VALIDATION_START = "2019Q1"
VALIDATION_END = "2022Q4"
TEST_START = "2023Q1"
TEST_END = "2025Q4"

RETENTION = 0.65
GAIN = 2.0
DEFAULT_HORIZON = 8

SHEETS = {
    "roads": "03_Дорожно-транспортный_комплек",
    "lighting": "32_Наружное_освещение",
    "transit": "34_Городской_общественный_транс",
    "safety": "35_Парковки_и_безопасность_движ",
    "active": "36_Вело-пешеходная_инфраструкту",
}

