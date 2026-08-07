"""Expectations charter agent tests (OS-019). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid

import pytest

from open_signal.agents.expectations_agent import (
    EXPECTATIONS_OUTPUT_SCHEMA,
    ExpectationsCharterAgent,
)
from open_signal.agents.runtime import Abstention, AgentRuntime, LlmUsage, StructuredOutputError


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, **kw):
        return self.content, LlmUsage(150, 60, 210)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _valid_output() -> str:
    return json.dumps(
        {
            "observation": "过去 24 小时 YES 概率从 0.40 上升至 0.60，成交量同步放大，价差收窄。",
            "persistence": "persistent",
            "noise_check": "clean",
            "no_psychological_attribution": True,
            "no_investment_advice": True,
            "confidence": 0.8,
            "reason": "持续 20 小时同向，persistence 指标 0.93",
        }
    )


def _agent(engine, output: str) -> ExpectationsCharterAgent:
    runtime = AgentRuntime(engine, client=FakeClient(output))
    return ExpectationsCharterAgent(runtime, engine)


def _calc() -> dict:
    return {"delta_24h": 20.0, "persistence": 0.93, "direction": 1, "eligible": True}


def test_schema_has_guardrails() -> None:
    props = EXPECTATIONS_OUTPUT_SCHEMA["properties"]
    assert props["no_psychological_attribution"]["const"] is True
    assert props["no_investment_advice"]["const"] is True


def test_evaluate_creates_claim(engine) -> None:
    from sqlalchemy import text

    agent = _agent(engine, _valid_output())
    result = agent.evaluate_candidate(
        source_market_id=str(uuid.uuid4()),
        canonical_expectation_id=str(uuid.uuid4()),
        calculation=_calc(),
        evidence_bundle_id=None,
        lineage_id="expectations-ml-v1",
    )
    assert result["persistence"] == "persistent"
    assert result["noise_check"] == "clean"
    assert result["claim_id"] is not None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT claim_type, structured_proposition FROM claims WHERE id = :id"),
            {"id": result["claim_id"]},
        ).fetchone()
    assert row[0] == "agent_observation"
    assert row[1]["value"] == "persistent"


def test_guardrail_violation_rejected(engine) -> None:
    bad = json.dumps(
        {
            "observation": "交易者恐慌导致价格下跌。",
            "persistence": "transient",
            "noise_check": "noisy",
            "no_psychological_attribution": False,  # violated
            "no_investment_advice": True,
            "confidence": 0.5,
            "reason": "x",
        }
    )
    agent = _agent(engine, bad)
    with pytest.raises(StructuredOutputError):
        agent.evaluate_candidate(
            source_market_id=str(uuid.uuid4()),
            canonical_expectation_id=str(uuid.uuid4()),
            calculation=_calc(),
            evidence_bundle_id=None,
            lineage_id="expectations-ml-v1",
        )


def test_investment_advice_rejected(engine) -> None:
    bad = json.dumps(
        {
            "observation": "建议买入该合约。",
            "persistence": "persistent",
            "noise_check": "clean",
            "no_psychological_attribution": True,
            "no_investment_advice": False,  # violated
            "confidence": 0.7,
            "reason": "x",
        }
    )
    agent = _agent(engine, bad)
    with pytest.raises(StructuredOutputError):
        agent.evaluate_candidate(
            source_market_id=str(uuid.uuid4()),
            canonical_expectation_id=str(uuid.uuid4()),
            calculation=_calc(),
            evidence_bundle_id=None,
            lineage_id="expectations-ml-v1",
        )


def test_abstention_propagates(engine) -> None:
    abstain = json.dumps(
        {
            "observation": "数据不足，无法判断。",
            "persistence": "abstain",
            "noise_check": "abstain",
            "no_psychological_attribution": True,
            "no_investment_advice": True,
            "confidence": 0.1,
            "reason": "观测序列少于 12 个数据点",
        }
    )
    agent = _agent(engine, abstain)
    with pytest.raises(Abstention):
        agent.evaluate_candidate(
            source_market_id=str(uuid.uuid4()),
            canonical_expectation_id=str(uuid.uuid4()),
            calculation=_calc(),
            evidence_bundle_id=None,
            lineage_id="expectations-ml-v1",
        )
