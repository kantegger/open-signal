"""Evaluation harness tests (OS-034). Cost report requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid

import pytest

from open_signal.eval.harness import (
    compare_lineages,
    cost_report,
    load_cases,
    load_rubrics,
    score_agent_output,
    score_edition,
)


def test_load_cases() -> None:
    cases = load_cases()
    assert len(cases) >= 2
    assert {c["id"] for c in cases} >= {"expectations-01", "expectations-02"}


def test_load_rubrics() -> None:
    rubrics = load_rubrics()
    assert len(rubrics["rubrics"]) == 4
    assert sum(r["weight"] for r in rubrics["rubrics"]) == pytest.approx(1.0)


def test_golden_output_passes() -> None:
    cases = load_cases()
    case = next(c for c in cases if c["id"] == "expectations-01")
    golden = case["golden_output"]
    result = score_agent_output(golden, case)
    assert result["passed"] is True
    assert result["weighted_score"] >= 0.9
    assert result["scores"]["guardrail_compliance"] == 1.0


def test_abstention_case() -> None:
    cases = load_cases()
    case = next(c for c in cases if c["id"] == "expectations-02")
    output = {"persistence": "abstain", "reason": "数据不足，无法形成判断。"}
    result = score_agent_output(output, case)
    assert result["passed"] is True  # abstain is the expected outcome


def test_guardrail_violation_fails() -> None:
    cases = load_cases()
    case = next(c for c in cases if c["id"] == "expectations-01")
    bad = {"observation": "交易者恐慌导致价格下跌。", "persistence": "persistent", "noise_check": "clean"}
    result = score_agent_output(bad, case)
    assert result["scores"]["guardrail_compliance"] == 0.0
    assert result["passed"] is False


def test_wrong_outcome_fails() -> None:
    cases = load_cases()
    case = next(c for c in cases if c["id"] == "expectations-01")
    wrong = {"observation": "价格下跌。", "persistence": "transient", "noise_check": "noisy"}
    result = score_agent_output(wrong, case)
    assert result["passed"] is False


def test_lineage_comparison() -> None:
    cases = load_cases()
    case = next(c for c in cases if c["id"] == "expectations-01")
    good = {"observation": "过去 24 小时 YES 概率上升。", "persistence": "persistent", "noise_check": "clean"}
    bad = {"observation": "建议买入。", "persistence": "transient", "noise_check": "noisy"}
    result = compare_lineages(good, bad, case)
    assert result["winner"] == "a"


def test_edition_scoring() -> None:
    good = {
        "slots": {"lead": 1, "secondary": 2, "main": 1},
        "lead": {"component_id": "signal-hero.expectations"},
        "sections": ["expectations-moved", "rules-moved"],
    }
    score = score_edition(good)
    assert score["edition_score"] >= 0.8
    assert score["component_score"] == 1.0
    assert score["lead_score"] == 1.0

    sparse = {"slots": {}, "lead": None, "sections": []}
    sparse_score = score_edition(sparse)
    assert sparse_score["edition_score"] == 0.0


# ------------------------------------------------------------- cost report


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def test_cost_report(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os034-desk', 'OS034', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os034-lineage', 'os034-desk', 'OS034', 'deepseek-chat', 'v1', "
                "'c', 'os-034', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        for cost, tokens in ((0.5, 1000), (0.2, 500)):
            conn.execute(
                text(
                    "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                    "agent_lineage_id, model_version, charter_version, status, "
                    "estimated_cost_usd, total_input_tokens, total_output_tokens, started_at) "
                    "VALUES ('os034-desk', 's', 'c', 'os034-lineage', 'deepseek-chat', "
                    "'os-034', 'completed', :cost, :in, 200, now())"
                ),
                {"cost": cost, "in": tokens},
            )

    report = cost_report(engine, days=30)
    assert report["total_cost_usd"] == pytest.approx(0.7)
    assert report["by_desk"]["os034-desk"]["runs"] == 2
    assert report["by_desk"]["os034-desk"]["cost_usd"] == pytest.approx(0.7)
    assert "deepseek-chat" in report["by_desk"]["os034-desk"]["by_model"]

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))
