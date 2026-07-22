"""Автоматические проверки локального прототипа."""

from __future__ import annotations

import os


# API-тесты должны быть полностью автономными и никогда не использовать рабочую БД из .env.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["SESSION_COOKIE_SECURE"] = "false"
