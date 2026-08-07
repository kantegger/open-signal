"""Research domain agent tests (OS-022). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os

import pytest
from open_signal.agents.runtime import Abstention, AgentRuntime, LlmUsage
from open_signal.research.agent import ResearchDomainAgent


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, **kw):
        return self.content, LlmUsage(180, 70, 250)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _investigate_output() -> str:
    return json.dumps(
        {
            "verdict": "investigate",
            "hypothesis": "New Lab 在合成生物学领域近两年发表量突增，可能代表新的机构进入者。",
            "historical_context": "此前该机构在语料中仅 1 篇，近 2 年 5 篇。",
            "skeptic_concerns": ["语料窗口选择可能偏斜", "机构名称消歧未验证"],
            "verification_note": "候选的 derived_metrics 字段完整，relation id 可追溯。",
            "confidence": 0.7,
            "reason": "增长幅度超过 3 倍且样本量足够",
        }
    )


def _agent(engine, output: str) -> ResearchDomainAgent:
    runtime = AgentRuntime(engine, client=FakeClient(output))
    return ResearchDomainAgent(runtime, engine)


def _seed_candidate(engine) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO research_signal_candidates "
                "(candidate_type, subject_ids, observation_window_start, "
                "observation_window_end, baseline_definition, derived_metrics, "
                "evidence_relation_ids, candidate_generator_version, status) "
                "VALUES ('institution_entry', ARRAY[]::uuid[], '2024-01-01', '2025-12-31', "
                "'prior-year works 1', CAST('{\"institution\": \"New Lab\"}' AS jsonb), "
                "ARRAY[]::uuid[], 'os-021', 'generated') RETURNING id"
            )
        ).fetchone()
        return str(row[0])


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM research_signal_candidates"))


def test_investigate_updates_shadow_ledger(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    candidate_id = _seed_candidate(engine)
    agent = _agent(engine, _investigate_output())
    result = agent.evaluate_candidate(
        candidate_id=candidate_id,
        candidate={
            "candidate_type": "institution_entry",
            "baseline_definition": "prior-year works 1",
            "derived_metrics": {"institution": "New Lab", "recent_works": 5, "prior_works": 1},
        },
        lineage_id="research-ml-v1",
    )
    assert result["verdict"] == "investigate"
    assert result["status"] == "shadow_investigation"

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, derived_metrics FROM research_signal_candidates WHERE id = :id"),
            {"id": candidate_id},
        ).fetchone()
    assert row[0] == "shadow_investigation"
    assert row[1]["hypothesis"].startswith("New Lab")
    _cleanup(engine)


def test_no_claims_created(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    candidate_id = _seed_candidate(engine)
    claims_before = engine.connect().execute(text("SELECT count(*) FROM claims")).scalar_one()
    agent = _agent(engine, _investigate_output())
    agent.evaluate_candidate(
        candidate_id=candidate_id,
        candidate={"candidate_type": "institution_entry"},
        lineage_id="research-ml-v1",
    )
    claims_after = engine.connect().execute(text("SELECT count(*) FROM claims")).scalar_one()
    assert claims_after == claims_before
    _cleanup(engine)


def test_skip_updates_rejected(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    candidate_id = _seed_candidate(engine)
    skip = json.dumps(
        {
            "verdict": "skip",
            "hypothesis": "信号不足以支持调查。",
            "historical_context": "基线无显著差异。",
            "skeptic_concerns": ["样本量过小"],
            "verification_note": "已核对候选字段完整性。",
            "confidence": 0.3,
            "reason": "增长未超过阈值",
        }
    )
    agent = _agent(engine, skip)
    result = agent.evaluate_candidate(
        candidate_id=candidate_id,
        candidate={"candidate_type": "institution_entry"},
        lineage_id="research-ml-v1",
    )
    assert result["status"] == "rejected"
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM research_signal_candidates WHERE id = :id"),
            {"id": candidate_id},
        ).fetchone()[0]
    assert status == "rejected"
    _cleanup(engine)


def test_abstention_marks_abstained(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    candidate_id = _seed_candidate(engine)
    abstain = json.dumps(
        {
            "verdict": "abstain",
            "hypothesis": "候选数据不足，无法形成可验证的研究假设。",
            "historical_context": "基线缺失。",
            "skeptic_concerns": ["无法排除反证"],
            "verification_note": "未完成验证，候选字段不完整。",
            "confidence": 0.1,
            "reason": "候选缺少必要字段",
        }
    )
    agent = _agent(engine, abstain)
    with pytest.raises(Abstention):
        agent.evaluate_candidate(
            candidate_id=candidate_id,
            candidate={"candidate_type": "institution_entry"},
            lineage_id="research-ml-v1",
        )
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM research_signal_candidates WHERE id = :id"),
            {"id": candidate_id},
        ).fetchone()[0]
    assert status == "abstained"
    _cleanup(engine)
