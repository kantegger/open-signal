"""Small, process-reused SQLAlchemy pool for serverless API instances."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_CREATED_ENGINES: list[Engine] = []


def get_engine() -> Engine:
    database_url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not database_url:
        raise RuntimeError("OPEN_SIGNAL_DATABASE_URL is required")
    return _engine_for_url(database_url)


@lru_cache(maxsize=4)
def _engine_for_url(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=_integer_setting("OPEN_SIGNAL_DB_POOL_RECYCLE", 240, minimum=30),
        pool_size=_integer_setting("OPEN_SIGNAL_DB_POOL_SIZE", 1, minimum=1),
        max_overflow=_integer_setting("OPEN_SIGNAL_DB_MAX_OVERFLOW", 1, minimum=0),
        pool_timeout=_integer_setting("OPEN_SIGNAL_DB_POOL_TIMEOUT", 10, minimum=1),
        pool_use_lifo=True,
    )
    _CREATED_ENGINES.append(engine)
    return engine


def clear_engine_cache() -> None:
    """Dispose cached pools; primarily useful for tests and graceful shutdown."""
    for engine in _CREATED_ENGINES:
        engine.dispose()
    _CREATED_ENGINES.clear()
    _engine_for_url.cache_clear()


def _integer_setting(name: str, default: int, *, minimum: int) -> int:
    raw: Any = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value
