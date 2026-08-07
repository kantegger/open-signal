"""Degraded mode tests (OS-037). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migrations 0001-0007 applied).
"""

import os
import pytest

from open_signal.ops.degraded import DegradedModeError, DegradedModeManager


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def manager(engine) -> DegradedModeManager:
    return DegradedModeManager(engine)


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM feature_flags WHERE flag_name LIKE 'ops.mode.%'"))
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))


def test_default_normal(manager, engine) -> None:
    _cleanup(engine)
    assert manager.current_mode() == "normal"
    policy = manager.edition_policy()
    assert policy["generate_editions"] is True
    assert policy["llm_agents"] is True


def test_static_edition_mode(manager, engine) -> None:
    _cleanup(engine)
    manager.set_mode("static_edition", "maintenance")
    assert manager.current_mode() == "static_edition"
    ok, reason = manager.check_edition_generation()
    assert ok is False
    assert "static" in reason
    # LLM agents still allowed in static mode
    assert manager.edition_policy()["llm_agents"] is True
    _cleanup(engine)


def test_archive_only_mode(manager, engine) -> None:
    _cleanup(engine)
    manager.set_mode("archive_only", "full halt")
    policy = manager.edition_policy()
    assert policy["generate_editions"] is False
    assert policy["llm_agents"] is False
    assert policy["serve_archive"] is True
    ok, _ = manager.check_llm_agent()
    assert ok is False
    _cleanup(engine)


def test_deterministic_only_blocks_llm(manager, engine) -> None:
    _cleanup(engine)
    manager.set_mode("deterministic_only", "budget")
    ok, reason = manager.check_llm_agent("desk-x")
    assert ok is False
    assert "deterministic" in reason
    # edition generation still allowed (deterministic path)
    gen_ok, _ = manager.check_edition_generation()
    assert gen_ok is True
    _cleanup(engine)


def test_section_restricted(manager, engine) -> None:
    _cleanup(engine)
    manager.set_mode("section_restricted", "sections:expectations-moved,rules-moved")
    policy = manager.edition_policy()
    assert policy["restricted_sections"] == ["expectations-moved", "rules-moved"]
    assert policy["generate_editions"] is True
    _cleanup(engine)


def test_unknown_mode_rejected(manager, engine) -> None:
    with pytest.raises(DegradedModeError):
        manager.set_mode("not-a-mode")
