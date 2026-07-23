from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


DATA_PATH = Path(
    os.getenv(
        "SMOLENSK_DATA_PATH",
        PROJECT_ROOT / "datasets_ready" / "smolensk_dataset_shared.xlsx",
    )
)
STATIC_DIR = PROJECT_ROOT / "app" / "static"
ANFIS_MODEL_DIR = Path(os.getenv("ANFIS_MODEL_DIR", PROJECT_ROOT / "runtime" / "models"))
if not ANFIS_MODEL_DIR.is_absolute():
    ANFIS_MODEL_DIR = PROJECT_ROOT / ANFIS_MODEL_DIR
TRAIN_START = "2006Q1"
TRAIN_END = "2018Q4"
VALIDATION_START = "2019Q1"
VALIDATION_END = "2022Q4"
TEST_START = "2023Q1"
TEST_END = "2025Q4"

FCM_ALPHA = 0.35
FCM_LAMBDA = 1.3
DEFAULT_HORIZON = 8
IMPULSE_LIMIT = 1.0
