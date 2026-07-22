"""Автоматические проверки локального прототипа."""

from __future__ import annotations

import os


# API-тесты должны быть полностью автономными и не требовать запущенного PostgreSQL.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
