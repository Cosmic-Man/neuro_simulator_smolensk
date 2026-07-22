from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DATA_PATH = Path(
    os.getenv(
        "SMOLENSK_DATA_PATH",
        PROJECT_ROOT / "datasets_ready" / "smolensk_dataset_shared.xlsx",
    )
)
STATIC_DIR = PROJECT_ROOT / "app" / "static"
SCENARIO_DIR = PROJECT_ROOT / "runtime" / "scenarios"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://neuro_simulator:neuro_simulator_dev@127.0.0.1:5432/neuro_simulator",
)
DATABASE_ECHO = _env_bool("DATABASE_ECHO")
AUTO_CREATE_SCHEMA = _env_bool("AUTO_CREATE_SCHEMA")

SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "neuro_session")
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))

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
