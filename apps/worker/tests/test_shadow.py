"""Shadow environment tests (OS-033). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid

import pytest

from open_signal.ops.shadow import (
    SHADOW_SCHEMA,
    ShadowEnvironment,
    shadow_edition_url,
    shadow_id,
    shadow_mode,
    shadow_store_dir,
)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _drop_shadow(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SHADOW_SCHEMA}" CASCADE'))


def test_shadow_id_prefix(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_SIGNAL_SHADOW", "1")
    assert shadow_mode() is True
    assert shadow_id("lineage-v1") == "shadow-lineage-v1"
    assert shadow_edition_url("ed-1") == "/shadow/editions/ed-1"


def test_shadow_id_off(monkeypatch) -> None:
    monkeypatch.delenv("OPEN_SIGNAL_SHADOW", raising=False)
    assert shadow_mode() is False
    assert shadow_id("lineage-v1") == "lineage-v1"
    assert shadow_edition_url("ed-1") == "/editions/ed-1"


def test_store_dir_default(monkeypatch) -> None:
    monkeypatch.delenv("OPEN_SIGNAL_SHADOW_STORE", raising=False)
    d = shadow_store_dir()
    assert d.name == ".shadow-objects"


def test_store_dir_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPEN_SIGNAL_SHADOW_STORE", str(tmp_path / "store"))
    assert shadow_store_dir() == tmp_path / "store"


def test_ensure_schema(engine) -> None:
    _drop_shadow(engine)
    env = ShadowEnvironment(engine)
    env.ensure_schema()
    tables = env.tables()
    assert len(tables) >= 30  # core tables cloned
    assert env.is_isolated() is True
    _drop_shadow(engine)


def test_shadow_schema_is_writable(engine) -> None:
    from sqlalchemy import text

    _drop_shadow(engine)
    env = ShadowEnvironment(engine)
    env.ensure_schema()
    with engine.begin() as conn:
        conn.execute(text(f'INSERT INTO "{SHADOW_SCHEMA}".sources '
                          "(slug, name, category, authority_level, access_mode, adapter_id, status) "
                          "VALUES ('shadow-src', 'S', 'other', 'secondary_source', 'rest', 'v1', 'active')"))
    with engine.connect() as conn:
        count = conn.execute(
            text(f'SELECT count(*) FROM "{SHADOW_SCHEMA}".sources')
        ).scalar_one()
    assert count >= 1
    _drop_shadow(engine)
