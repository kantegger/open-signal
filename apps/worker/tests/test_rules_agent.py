"""Rules charter agent tests (OS-018). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import json
import os

import pytest
from open_signal.agents.rules_agent import RULES_OUTPUT_SCHEMA, RulesCharterAgent
from open_signal.agents.runtime import AgentRuntime, LlmUsage


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, **kw):
        return self.content, LlmUsage(200, 80, 280)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _material_output() -> str:
    return json.dumps(
        {
            "observation": "阈值从 5% 提高到 10%，实质影响供应商合规义务。",
            "materiality": "material",
            "affected_categories": ["consumer_products", "labeling"],
            "limitations": ["仅基于单份文档，未交叉验证其他 CFR 章节"],
            "preferred_component": "rule-change-summary.materiality",
            "reason": "阈值翻倍改变合规要求",
        }
    )


def _agent(engine, output: str) -> RulesCharterAgent:
    runtime = AgentRuntime(engine, client=FakeClient(output))
    return RulesCharterAgent(runtime, engine)


def _change_candidates() -> list[dict]:
    return [
        {
            "paragraph_id": "(a)",
            "kind": "change",
            "candidate_types": ["threshold_change"],
            "text_snippet": "The threshold is 10 percent.",
        }
    ]


def test_schema_shape() -> None:
    assert "materiality" in RULES_OUTPUT_SCHEMA["properties"]
    assert "preferred_component" in RULES_OUTPUT_SCHEMA["properties"]


def test_material_change_creates_claim(engine) -> None:
    from sqlalchemy import text

    agent = _agent(engine, _material_output())
    result = agent.evaluate_change(
        rule_meta={"document_number": "2026-12345", "title": "Labeling"},
        change_candidates=_change_candidates(),
        lineage_id="rules-ml-v1",
    )
    assert result["materiality"] == "material"
    assert result["claim_id"] is not None
    assert result["affected_categories"] == ["consumer_products", "labeling"]
    assert result["preferred_component"] == "rule-change-summary.materiality"

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT claim_type, public_statement, structured_proposition "
                "FROM claims WHERE id = :id"
            ),
            {"id": result["claim_id"]},
        ).fetchone()
    assert row[0] == "rule_change_observation"
    assert row[1] == result["observation"]
    assert row[2]["value"] == "material"


def test_non_material_no_claim(engine) -> None:
    agent = _agent(
        engine,
        json.dumps(
            {
                "observation": "仅生效日期调整",
                "materiality": "non_material",
                "affected_categories": [],
                "limitations": [],
                "preferred_component": "none",
                "reason": "technical date change",
            }
        ),
    )
    result = agent.evaluate_change(
        rule_meta={"document_number": "2026-99999"},
        change_candidates=_change_candidates(),
        lineage_id="rules-ml-v1",
    )
    assert result["materiality"] == "non_material"
    assert result["claim_id"] is None


def test_empty_candidates_short_circuit(engine) -> None:
    agent = _agent(engine, "should not be called")
    result = agent.evaluate_change(
        rule_meta={"document_number": "x"},
        change_candidates=[],
        lineage_id="rules-ml-v1",
    )
    assert result["materiality"] == "non_material"
    assert result["preferred_component"] == "none"


def test_materiality_deferred_to_model(engine) -> None:
    """OS-014 defers materiality to the agent; OS-018 is that agent."""
    agent = _agent(engine, _material_output())
    result = agent.evaluate_change(
        rule_meta={"document_number": "2026-12345"},
        change_candidates=_change_candidates(),
        lineage_id="rules-ml-v1",
    )
    assert result["materiality"] in {"material", "non_material"}
