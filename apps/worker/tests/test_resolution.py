"""Resolution MVP tests (OS-036). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from open_signal.resolution.resolver import Resolver


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def resolver(engine) -> Resolver:
    return Resolver(engine)


def _seed_claim_and_contract(engine) -> tuple[str, str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os036-desk', 'OS036', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os036-lineage', 'os036-desk', 'OS036', 'deepseek-chat', 'v1', "
                "'c', 'os-036', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        run = conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status) "
                "VALUES ('os036-desk', 'expectations-moved', 'expectation.probability-change', "
                "'os036-lineage', 'deepseek-chat', 'os-036', 'completed') RETURNING id"
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
        claim = conn.execute(
            text(
                "INSERT INTO claims (institution_id, desk_id, agent_lineage_id, model_version, "
                "charter_version, run_id, section_id, capability_id, claim_type, "
                "public_statement, structured_proposition, confidence, epistemic_status, "
                "evidence_bundle_id, evidence_snapshot_hash, issued_at, status) "
                "VALUES ('open-signal', 'os036-desk', 'os036-lineage', 'deepseek-chat', 'os-036', "
                ":run, 'expectations-moved', 'expectation.probability-change', 'derived_observation', "
                "'YES 概率上升', CAST(:prop AS jsonb), 0.6, 'derived', :eb, :h, now(), 'published') "
                "RETURNING id"
            ),
            {
                "run": str(run[0]),
                "prop": json.dumps({"predicate": "probability", "operator": "increased", "value": 0.6}),
                "eb": str(eb[0]),
                "h": uuid.uuid4().hex,
            },
        ).fetchone()
        conn.execute(
            text(
                "INSERT INTO resolution_templates "
                "(id, version, claim_type, section_ids, description, "
                "required_proposition_fields, default_evaluation_window, "
                "scoring_rule_id, partial_credit_allowed, maturity, activated_at) "
                "VALUES ('binary-resolver', '1.0.0', 'derived_observation', "
                "ARRAY['expectations-moved'], 'binary resolution', "
                "ARRAY['value'], interval '30 days', 'brier', true, 'production', now()) "
                "ON CONFLICT (id, version) DO NOTHING"
            )
        )
        contract = conn.execute(
            text(
                "INSERT INTO resolution_contracts "
                "(claim_id, template_id, template_version, issued_at, "
                "evaluation_start_at, evaluation_deadline, resolution_predicate, "
                "resolution_source_ids, scoring_rule_id, partial_credit_policy, "
                "ambiguity_policy, missing_data_policy, locked_at, lock_hash, status) "
                "VALUES (:claim, 'binary-resolver', '1.0.0', now(), now(), "
                "now() + interval '30 days', CAST('{\"predicate\": \"probability\"}' AS jsonb), "
                "ARRAY[]::uuid[], 'brier', NULL, 'abstain', 'resolve_false', now(), :h, 'locked') "
                "RETURNING id"
            ),
            {"claim": str(claim[0]), "h": uuid.uuid4().hex},
        ).fetchone()
        return str(claim[0]), str(contract[0])


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM resolution_contracts"))
        conn.execute(text("DELETE FROM evidence_bundles"))
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM agent_lineages"))
        conn.execute(text("DELETE FROM agent_desks"))


def test_binary_resolution_yes(resolver, engine) -> None:
    _cleanup(engine)
    claim_id, contract_id = _seed_claim_and_contract(engine)
    result = resolver.resolve_binary_expectation(
        claim_id=claim_id, resolution_contract_id=contract_id, final_probability=0.72
    )
    assert result["outcome"] == "yes"
    assert result["observed"] == 1.0
    # predicted = confidence 0.6 -> brier = (0.6 - 1.0)^2 = 0.16
    assert result["brier"] == pytest.approx(0.16)
    _cleanup(engine)


def test_binary_resolution_no(resolver, engine) -> None:
    _cleanup(engine)
    claim_id, contract_id = _seed_claim_and_contract(engine)
    result = resolver.resolve_binary_expectation(
        claim_id=claim_id, resolution_contract_id=contract_id, final_probability=0.2
    )
    assert result["outcome"] == "no"
    assert result["observed"] == 0.0
    assert result["brier"] == pytest.approx(0.36)
    _cleanup(engine)


def test_resolution_marks_claim_resolved(resolver, engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    claim_id, contract_id = _seed_claim_and_contract(engine)
    resolver.resolve_binary_expectation(claim_id=claim_id, resolution_contract_id=contract_id, final_probability=0.8)
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM claims WHERE id = :id"), {"id": claim_id}
        ).scalar_one()
    assert status == "resolved"
    # idempotent: second resolution is a no-op
    again = resolver.resolve_binary_expectation(claim_id=claim_id, resolution_contract_id=contract_id, final_probability=0.9)
    assert again.get("already_resolved") is True
    _cleanup(engine)


def test_rule_effective_by_date(resolver, engine) -> None:
    _cleanup(engine)
    claim_id, contract_id = _seed_claim_and_contract(engine)
    result = resolver.resolve_rule_effective_by_date(
        rule_id="rule-1", claim_id=claim_id, resolution_contract_id=contract_id,
        effective_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )
    assert result["outcome"] == "effective"
    _cleanup(engine)


def test_recently_resolved_component(resolver, engine) -> None:
    _cleanup(engine)
    claim_id, contract_id = _seed_claim_and_contract(engine)
    resolver.resolve_binary_expectation(claim_id=claim_id, resolution_contract_id=contract_id, final_probability=0.9)
    recent = resolver.recently_resolved()
    assert len(recent) >= 1
    assert recent[0]["claim_id"] if "claim_id" in recent[0] else recent[0]["desk_id"] == "os036-desk"
    assert recent[0]["brier"] is not None
    _cleanup(engine)
