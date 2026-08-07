"""Agent tool registry tests (OS-015). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0006 applied).
"""

import os
import uuid

import pytest
from open_signal.agents.tools import (
    ToolArgumentError,
    ToolPermissionError,
    ToolRegistry,
    ToolResultTooLarge,
    ToolSpec,
    register_readonly_tools,
)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def registry(engine) -> ToolRegistry:
    reg = ToolRegistry(engine)
    register_readonly_tools(reg)
    return reg


def _run_id(engine) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        # seed a desk + lineage so investigation_runs FK holds
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os015-desk', 'OS015', 'test', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os015-lineage', 'os015-desk', 'OS015', 'deepseek-chat', 'v1', "
                "'os-015', 'v1', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        row = conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status) "
                "VALUES ('os015-desk', 'expectations-moved', 'expectation.probability-change', "
                "'os015-lineage', 'deepseek-chat', 'os-015', 'running') RETURNING id"
            )
        ).fetchone()
        return str(row[0])


# ------------------------------------------------------------------- registry


def test_register_and_list(registry) -> None:
    tools = {t["id"] for t in registry.list_tools()}
    assert {"get_market_price", "get_calculation", "search_raw_records", "get_rule_changes"} <= tools


def test_duplicate_register_rejected(registry) -> None:
    spec = ToolSpec(
        id="get_market_price", name="dup", description="", permission="readonly",
        parameters={"type": "object", "properties": {}},
    )
    with pytest.raises(ValueError):
        registry.register(spec)


def test_unknown_tool(registry) -> None:
    with pytest.raises(ToolArgumentError):
        registry.call("no_such_tool", {}, run_id=str(uuid.uuid4()))


# --------------------------------------------------------------- validation


def test_schema_validation_missing_required(registry) -> None:
    with pytest.raises(ToolArgumentError):
        registry.call("get_market_price", {}, run_id=str(uuid.uuid4()))


def test_schema_validation_wrong_type(registry) -> None:
    with pytest.raises(ToolArgumentError):
        registry.call("get_market_price", {"market_id": 123}, run_id=str(uuid.uuid4()))


def test_schema_validation_additional_properties(registry) -> None:
    with pytest.raises(ToolArgumentError):
        registry.call(
            "get_market_price",
            {"market_id": str(uuid.uuid4()), "evil": "inject"},
            run_id=str(uuid.uuid4()),
        )


# --------------------------------------------------------------- permission


def test_permission_check_denied(registry) -> None:
    spec = ToolSpec(
        id="secret_tool", name="secret", description="", permission="desk:admin",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"secret": True},
    )
    registry.register(spec)
    with pytest.raises(ToolPermissionError):
        registry.call("secret_tool", {}, run_id=str(uuid.uuid4()), permission_scope="desk:expectations-desk")


def test_readonly_tools_need_no_scope(registry, engine) -> None:
    # readonly tools are callable with the default scope
    spec = ToolSpec(
        id="ro_tool", name="ro", description="", permission="readonly",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
    )
    registry.register(spec)
    result = registry.call("ro_tool", {}, run_id=_run_id(engine))
    assert result.ok


# ------------------------------------------------------------------ size/cost


def test_result_size_limit(registry, engine) -> None:
    spec = ToolSpec(
        id="big_tool", name="big", description="", permission="readonly",
        parameters={"type": "object", "properties": {}},
        max_result_bytes=100,
        handler=lambda args: {"data": "x" * 500},
    )
    registry.register(spec)
    with pytest.raises(ToolResultTooLarge):
        registry.call("big_tool", {}, run_id=_run_id(engine))


def test_cost_tracking(registry, engine) -> None:
    spec = ToolSpec(
        id="costly_tool", name="cost", description="", permission="readonly",
        cost_class="high", parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
    )
    registry.register(spec)
    result = registry.call("costly_tool", {}, run_id=_run_id(engine))
    assert result.cost_usd == 0.005
    assert result.ok


# ----------------------------------------------------------------------- log


def test_tool_call_logged(registry, engine) -> None:
    from sqlalchemy import text

    run = _run_id(engine)
    result = registry.call(
        "get_market_price",
        {"market_id": str(uuid.uuid4()), "limit": 3},
        run_id=run,
        agent_lineage_id="os015-lineage",
    )
    assert result.ok  # no rows is a valid read

    calls = registry.recent_calls(run_id=run)
    assert any(c["tool_id"] == "get_market_price" for c in calls)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, cost_usd, result_size_bytes FROM agent_tool_calls "
                "WHERE run_id = :run AND tool_id = 'get_market_price'"
            ),
            {"run": run},
        ).fetchone()
    assert row[0] == "ok"
    assert float(row[1]) > 0


def test_failed_call_logged(registry, engine) -> None:

    run = _run_id(engine)
    spec = ToolSpec(
        id="boom_tool", name="boom", description="", permission="readonly",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: (_ for _ in ()).throw(RuntimeError("exploded")),
    )
    registry.register(spec)
    result = registry.call("boom_tool", {}, run_id=run)
    assert result.ok is False
    assert "exploded" in result.error
    calls = registry.recent_calls(run_id=run)
    assert any(c["tool_id"] == "boom_tool" and c["status"] == "error" for c in calls)
