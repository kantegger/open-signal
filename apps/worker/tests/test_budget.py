"""Budget guard tests (OS-032). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from open_signal.budget import BudgetGuard


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_desk(engine, desk_id: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES (:id, 'Budget', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": desk_id},
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES (:l, :d, 'Budget', 'deepseek-chat', 'v1', 'c', 'os-032', 'v1', "
                "'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"l": f"{desk_id}-lineage", "d": desk_id},
        )


def _run(engine, desk_id: str, cost: float, age_minutes: int = 10) -> None:
    from sqlalchemy import text

    _seed_desk(engine, desk_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status, "
                "estimated_cost_usd, started_at) "
                "VALUES (:d, 's', 'c', :l, 'deepseek-chat', 'os-032', 'completed', "
                ":cost, now() - make_interval(mins => :age))"
            ),
            {"d": desk_id, "l": f"{desk_id}-lineage", "cost": cost, "age": age_minutes},
        )


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM agent_lineages"))
        conn.execute(text("DELETE FROM agent_desks"))


def test_normal_mode(engine) -> None:
    _cleanup(engine)
    guard = BudgetGuard(engine, desk_day_limit_usd=10.0, month_limit_usd=100.0)
    _run(engine, "budget-desk", 0.5)
    allowed, reason, state = guard.allow_llm_run("budget-desk")
    assert allowed is True
    assert state.mode() == "normal"
    _cleanup(engine)


def test_soft_limit_degraded(engine) -> None:
    _cleanup(engine)
    guard = BudgetGuard(engine, desk_day_limit_usd=1.0, month_limit_usd=100.0)
    _run(engine, "budget-desk", 0.9)  # 90% of desk day limit
    allowed, reason, state = guard.allow_llm_run("budget-desk")
    assert allowed is True
    assert state.soft_exceeded() is True
    assert state.mode() == "degraded"
    assert "soft" in reason
    _cleanup(engine)


def test_hard_limit_deterministic_only(engine) -> None:
    _cleanup(engine)
    guard = BudgetGuard(engine, desk_day_limit_usd=1.0, month_limit_usd=100.0)
    _run(engine, "budget-desk", 1.5)  # exceeds desk day limit
    allowed, reason, state = guard.allow_llm_run("budget-desk")
    assert allowed is False
    assert state.hard_exceeded() is True
    assert state.mode() == "deterministic_only"
    assert "hard" in reason
    _cleanup(engine)


def test_monthly_global_hard_limit(engine) -> None:
    _cleanup(engine)
    guard = BudgetGuard(engine, desk_day_limit_usd=100.0, month_limit_usd=2.0)
    _run(engine, "budget-desk", 2.5)  # exceeds monthly global
    allowed, reason, state = guard.allow_llm_run("budget-desk")
    assert allowed is False
    assert state.mode() == "deterministic_only"
    _cleanup(engine)


def test_other_desk_isolated(engine) -> None:
    _cleanup(engine)
    guard = BudgetGuard(engine, desk_day_limit_usd=1.0, month_limit_usd=100.0)
    _run(engine, "other-desk", 0.9)  # other desk spent 90%
    allowed, _, state = guard.allow_llm_run("fresh-desk")
    assert allowed is True
    assert state.desk_day_cost_usd == 0.0
    _cleanup(engine)
