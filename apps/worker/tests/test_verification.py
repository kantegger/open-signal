"""Claim verification checks tests (OS-024). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from open_signal.claims.verification import ClaimVerifier


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def verifier(engine) -> ClaimVerifier:
    return ClaimVerifier(engine)


def _seed_context(engine) -> tuple[str, str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os024-desk', 'OS024', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os024-lineage', 'os024-desk', 'OS024', 'deepseek-chat', 'v1', "
                "'c', 'os-024', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        run = conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status) "
                "VALUES ('os024-desk', 'expectations-moved', 'expectation.probability-change', "
                "'os024-lineage', 'deepseek-chat', 'os-024', 'completed') RETURNING id"
            )
        ).fetchone()
        eb = conn.execute(
            text(
                "INSERT INTO evidence_bundles (primary_evidence, supporting_evidence, "
                "counter_evidence, data_calculation_ids, source_coverage, snapshot_hash) "
                "VALUES ('[]'::jsonb, '[]'::jsonb, '[]'::jsonb, ARRAY[]::uuid[], "
                "'{}'::jsonb, :h) RETURNING id"
            ),
            {"h": uuid.uuid4().hex},
        ).fetchone()
        return str(eb[0]), str(run[0])


def _create_claim(engine, *, statement: str, claim_type: str = "derived_observation", prop: dict | None = None) -> str:
    from sqlalchemy import text

    eb, run = _seed_context(engine)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO claims (institution_id, desk_id, agent_lineage_id, model_version, "
                "charter_version, run_id, section_id, capability_id, claim_type, "
                "public_statement, structured_proposition, confidence, epistemic_status, "
                "evidence_bundle_id, evidence_snapshot_hash, issued_at, status) "
                "VALUES ('open-signal', 'os024-desk', 'os024-lineage', 'deepseek-chat', 'os-024', "
                ":run, 'expectations-moved', 'expectation.probability-change', :type, :statement, "
                "CAST(:prop AS jsonb), 0.85, 'derived', :eb, :h, now(), 'draft') RETURNING id"
            ),
            {
                "run": run,
                "type": claim_type,
                "statement": statement,
                "prop": __import__("json").dumps(prop or {"subject_ids": [str(uuid.uuid4())], "value": 0.2}),
                "eb": eb,
                "h": uuid.uuid4().hex,
            },
        ).fetchone()
        return str(row[0])


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM evidence_bundles"))


def test_clean_claim_passes_all(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="YES 概率过去 24 小时上升 20 个百分点。")
    result = verifier.verify(cid)
    assert result.passed is True, result.to_dict()
    assert set(result.checks.keys()) == {
        "source", "citation", "number", "date", "rights",
        "claim_type", "component_fields", "prohibited_language",
    }
    _cleanup(engine)


def test_investment_advice_rejected(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="建议买入该合约，预期年化收益率 30%。")
    result = verifier.verify(cid)
    assert result.passed is False
    assert result.checks["prohibited_language"]["passed"] is False
    _cleanup(engine)


def test_psychological_attribution_rejected(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="交易者恐慌导致价格下跌。")
    result = verifier.verify(cid)
    assert result.passed is False
    assert result.checks["prohibited_language"]["passed"] is False
    _cleanup(engine)


def test_disallowed_claim_type_rejected(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="正常观察。", claim_type="hack_type")
    result = verifier.verify(cid)
    assert result.passed is False
    assert result.checks["claim_type"]["passed"] is False
    _cleanup(engine)


def test_missing_subject_rejected(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="观察。", prop={"other": 1})
    result = verifier.verify(cid)
    assert result.passed is False
    assert result.checks["citation"]["passed"] is False
    _cleanup(engine)


def test_bad_number_rejected(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="观察。", prop={"subject_ids": ["x"], "value": "not-a-number"})
    result = verifier.verify(cid)
    assert result.passed is False
    assert result.checks["number"]["passed"] is False
    _cleanup(engine)


def test_component_fields_gate(verifier, engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine, statement="正常观察。")
    good = verifier.verify(cid, render_candidate={"component_id": "c1", "headline": "h", "display_fields": {}})
    assert good.checks["component_fields"]["passed"] is True
    bad = verifier.verify(cid, render_candidate={"component_id": "c1"})
    assert bad.checks["component_fields"]["passed"] is False
    _cleanup(engine)


def test_composer_gate_updates_status(verifier, engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    good_cid = _create_claim(engine, statement="正常观察。")
    bad_cid = _create_claim(engine, statement="建议买入。")

    assert verifier.gate_for_composer(good_cid) is True
    assert verifier.gate_for_composer(bad_cid) is False

    with engine.connect() as conn:
        good_status = conn.execute(text("SELECT status FROM claims WHERE id = :id"), {"id": good_cid}).scalar_one()
        bad_status = conn.execute(text("SELECT status FROM claims WHERE id = :id"), {"id": bad_cid}).scalar_one()
    assert good_status == "verified"
    assert bad_status == "rejected"
    _cleanup(engine)
