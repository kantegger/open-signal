"""DeepSeek agent runtime tests (OS-017).

Unit tests use a fake client (no network). Integration test hits the real
DeepSeek API only when DEEPSEEK_API_KEY is set and OPEN_SIGNAL_TEST_DATABASE_URL
is available (migration 0001 applied).
"""

import json
import os

import pytest
from open_signal.agents.runtime import (
    Abstention,
    AgentResult,
    AgentRuntime,
    DeepSeekClient,
    LlmError,
    LlmUsage,
    StructuredOutputError,
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no", "abstain"]},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


class FakeClient:
    def __init__(self, content: str, usage: LlmUsage | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.usage = usage or LlmUsage(100, 50, 150)
        self.error = error
        self.last_messages: list | None = None

    def chat(self, messages, **kw):
        self.last_messages = messages
        if self.error:
            raise self.error
        return self.content, self.usage


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def runtime(engine) -> AgentRuntime:
    return AgentRuntime(engine, client=FakeClient(json.dumps({"verdict": "yes", "reason": "test", "confidence": 0.8})))


def _seed_lineage(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('expectations-desk', 'Expectations', 'test', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os017-lineage', 'expectations-desk', 'OS017', 'deepseek-chat', 'v1', "
                "'expectations-desk-charter', 'os-017', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )


# ------------------------------------------------------------------- charters


def test_charter_loader(runtime) -> None:
    charters = runtime.list_charters()
    assert {"expectations-desk-charter", "rules-desk-charter"} <= set(charters)
    text = runtime.load_charter("expectations-desk-charter")
    assert "Expectations" in text
    with pytest.raises(FileNotFoundError):
        runtime.load_charter("no-such-charter")


# ------------------------------------------------------------ structured output


def test_structured_output_validated(runtime) -> None:
    structured = runtime._parse_structured('{"verdict": "yes", "reason": "ok"}', OUTPUT_SCHEMA)
    assert structured["verdict"] == "yes"


def test_structured_output_schema_violation(runtime) -> None:
    with pytest.raises(StructuredOutputError):
        runtime._parse_structured('{"verdict": "maybe"}', OUTPUT_SCHEMA)


def test_structured_output_non_json(runtime) -> None:
    with pytest.raises(StructuredOutputError):
        runtime._parse_structured("not json at all", OUTPUT_SCHEMA)


class RetryClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, **kw):
        self.calls += 1
        if self.calls == 1:
            return '{"verdict": "yes", "reason": "x"', LlmUsage(10, 5, 15)  # invalid JSON
        return json.dumps({"verdict": "yes", "reason": "ok", "confidence": 0.6}), LlmUsage(20, 10, 30)


def test_schema_failure_triggers_corrective_retry(engine) -> None:
    from sqlalchemy import text

    client = RetryClient()
    rt = AgentRuntime(engine, client=client)
    _seed_lineage(engine)
    result = rt.run(
        lineage_id="os017-lineage",
        desk_id="expectations-desk",
        section_id="expectations-moved",
        capability_id="expectation.probability-change",
        context={},
        output_schema=OUTPUT_SCHEMA,
    )
    assert client.calls == 2
    assert result.structured["verdict"] == "yes"
    with engine.connect() as conn:
        tokens = conn.execute(
            text("SELECT total_input_tokens FROM investigation_runs WHERE id = :id"),
            {"id": result.run_id},
        ).scalar_one()
    assert tokens == 20  # second (retry) usage recorded


# ---------------------------------------------------------------- abstention


def test_abstention_detected(runtime) -> None:
    assert runtime._check_abstention({"verdict": "abstain", "reason": "not enough"}) == (True, "not enough")
    assert runtime._check_abstention({"abstain": True, "reason": "r"}) == (True, "r")
    assert runtime._check_abstention({"verdict": "yes"}) == (False, None)


# ---------------------------------------------------------------------- runs


def test_run_success_writes_tokens(runtime, engine) -> None:
    _seed_lineage(engine)
    result = runtime.run(
        lineage_id="os017-lineage",
        desk_id="expectations-desk",
        section_id="expectations-moved",
        capability_id="expectation.probability-change",
        context={"delta_24h": 20.0},
        output_schema=OUTPUT_SCHEMA,
    )
    assert isinstance(result, AgentResult)
    assert result.structured["verdict"] == "yes"
    assert result.usage.prompt_tokens == 100

    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, total_input_tokens, total_output_tokens, estimated_cost_usd, "
                "output_judgment FROM investigation_runs WHERE id = :id"
            ),
            {"id": result.run_id},
        ).fetchone()
    assert row[0] == "completed"
    assert row[1] == 100
    assert row[2] == 50
    assert float(row[3]) > 0
    assert row[4]["verdict"] == "yes"


def test_run_abstention(engine) -> None:

    _seed_lineage(engine)
    rt = AgentRuntime(
        engine,
        client=FakeClient(json.dumps({"verdict": "abstain", "reason": "insufficient evidence"})),
    )
    with pytest.raises(Abstention) as exc:
        rt.run(
            lineage_id="os017-lineage",
            desk_id="expectations-desk",
            section_id="expectations-moved",
            capability_id="expectation.probability-change",
            context={},
            output_schema=OUTPUT_SCHEMA,
        )
    assert "insufficient evidence" in str(exc.value)
    from sqlalchemy import text

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM investigation_runs WHERE id = :id"),
            {"id": _last_run(engine)},
        ).fetchone()
    assert status is not None
    assert status[0] == "abstained"


def _last_run(engine) -> str:
    from sqlalchemy import text

    with engine.connect() as conn:
        return str(
            conn.execute(text("SELECT id FROM investigation_runs ORDER BY started_at DESC LIMIT 1")).fetchone()[0]
        )


def test_run_error_records(engine) -> None:
    _seed_lineage(engine)
    rt = AgentRuntime(engine, client=FakeClient(content="", error=LlmError("boom")))
    with pytest.raises(LlmError):
        rt.run(
            lineage_id="os017-lineage",
            desk_id="expectations-desk",
            section_id="expectations-moved",
            capability_id="expectation.probability-change",
            context={},
            output_schema=OUTPUT_SCHEMA,
        )
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, error_details FROM investigation_runs WHERE id = :id"),
            {"id": _last_run(engine)},
        ).fetchone()
    assert row[0] == "error"
    assert "boom" in json.dumps(row[1])


def test_client_requires_key() -> None:
    old = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        with pytest.raises(LlmError):
            DeepSeekClient()
    finally:
        if old:
            os.environ["DEEPSEEK_API_KEY"] = old


def test_usage_cost() -> None:
    usage = LlmUsage(prompt_tokens=1000, completion_tokens=1000)
    assert usage.cost_usd("deepseek-chat") > 0
    assert usage.cost_usd("deepseek-reasoner") > usage.cost_usd("deepseek-chat")


# ------------------------------------------------------- live DeepSeek smoke


def test_live_deepseek_chat(engine) -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")
    client = DeepSeekClient()
    content, usage = client.chat(
        [
            {"role": "system", "content": "只输出 JSON。"},
            {"role": "user", "content": '输出 {"verdict": "yes"}'},
        ],
        json_mode=True,
        max_tokens=200,
    )
    client.close()
    data = json.loads(content)
    assert data["verdict"] == "yes"
    assert usage.total_tokens > 0
