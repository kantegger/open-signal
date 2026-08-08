"""Serverless database engine configuration tests (no connection required)."""

import pytest
from open_signal.api import database
from open_signal.api.database import clear_engine_cache, get_engine


@pytest.fixture(autouse=True)
def clear_cache():
    clear_engine_cache()
    yield
    clear_engine_cache()


def test_engine_is_reused_with_a_bounded_lifo_pool(monkeypatch) -> None:
    calls = []

    class FakeEngine:
        def dispose(self):
            return None

    def fake_create_engine(url, **kwargs):
        calls.append((url, kwargs))
        return FakeEngine()

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    monkeypatch.setenv(
        "OPEN_SIGNAL_DATABASE_URL",
        "postgresql://open_signal:open_signal@localhost:5432/open_signal",
    )

    first = get_engine()
    second = get_engine()

    assert first is second
    assert len(calls) == 1
    assert calls[0][1] == {
        "pool_pre_ping": True,
        "pool_recycle": 240,
        "pool_size": 1,
        "max_overflow": 1,
        "pool_timeout": 10,
        "pool_use_lifo": True,
    }


def test_invalid_pool_setting_fails_before_connect(monkeypatch) -> None:
    monkeypatch.setenv(
        "OPEN_SIGNAL_DATABASE_URL",
        "postgresql://open_signal:open_signal@localhost:5432/open_signal",
    )
    monkeypatch.setenv("OPEN_SIGNAL_DB_POOL_SIZE", "0")

    with pytest.raises(RuntimeError, match="OPEN_SIGNAL_DB_POOL_SIZE"):
        get_engine()
