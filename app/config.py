from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = Path(
    os.getenv(
        "SMOLENSK_DATA_PATH",
        PROJECT_ROOT / "datasets_ready" / "smolensk_dataset_shared.xlsx",
    )
)
STATIC_DIR = PROJECT_ROOT / "app" / "static"
SCENARIO_DIR = PROJECT_ROOT / "runtime" / "scenarios"

TRAIN_START = "2006Q1"
TRAIN_END = "2018Q4"
VALIDATION_START = "2019Q1"
VALIDATION_END = "2022Q4"
TEST_START = "2023Q1"
TEST_END = "2025Q4"

FCM_ALPHA = 0.35
FCM_LAMBDA = 1.3
DEFAULT_HORIZON = 8

