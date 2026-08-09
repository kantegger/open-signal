"""Claims ledger tests (OS-023). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid

import pytest
from open_signal.claims.ledger import ClaimsLedger


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def ledger(engine) -> ClaimsLedger:
    return ClaimsLedger(engine)


def _seed_context(engine) -> tuple[str, str]:
    """Returns (evidence_bundle_id, run_id)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os023-desk', 'OS023', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os023-lineage', 'os023-desk', 'OS023', 'deepseek-chat', 'v1', "
                "'c', 'os-023', 'v1', 'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        run = conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status) "
                "VALUES ('os023-desk', 'expectations-moved', 'expectation.probability-change', "
                "'os023-lineage', 'deepseek-chat', 'os-023', 'completed') RETURNING id"
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


def _cleanup(engine, claim_id: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM evidence_bundles"))


def _base_kwargs(engine) -> dict:
    eb, run = _seed_context(engine)
    return {
        "desk_id": "os023-desk",
        "section_id": "expectations-moved",
        "capability_id": "expectation.probability-change",
        "claim_type": "derived_observation",
        "public_statement": "YES 概率 24h 上升 20 个百分点",
        "structured_proposition": {"predicate": "probability", "operator": "increased", "value": 20.0},
        "confidence": 0.9,
        "evidence_bundle_id": eb,
        "agent_lineage_id": "os023-lineage",
        "model_version": "deepseek-chat",
        "charter_version": "os-023",
        "run_id": run,
    }


def test_create_claim_initial_chain(ledger, engine) -> None:
    result = ledger.create_claim(**_base_kwargs(engine))
    assert result["claim_id"] is not None
    assert result["event_hash"]

    page = ledger.get_claim_page(result["claim_id"])
    assert page is not None
    assert page["claim"]["status"] == "draft"
    assert len(page["versions"]) == 1
    assert page["versions"][0]["version_number"] == 1
    assert len(page["events"]) == 1
    assert page["events"][0]["event_type"] == "claim.created"
    assert ledger.verify_hash_chain(result["claim_id"]) is True
    _cleanup(engine, result["claim_id"])


def test_update_appends_version_and_event(ledger, engine) -> None:
    created = ledger.create_claim(**_base_kwargs(engine))
    updated = ledger.update_claim(
        claim_id=created["claim_id"],
        public_statement="YES 概率 24h 上升 25 个百分点（修正）",
        structured_proposition={"predicate": "probability", "operator": "increased", "value": 25.0},
        confidence=0.85,
        evidence_bundle_id=_base_kwargs(engine)["evidence_bundle_id"],
        change_reason="复核修正",
        actor_type="agent",
        actor_id="verifier",
    )
    assert updated["version_number"] == 2

    page = ledger.get_claim_page(created["claim_id"])
    assert len(page["versions"]) == 2
    assert page["versions"][1]["change_type"] == "update"
    assert len(page["events"]) == 2
    assert page["events"][1]["event_type"] == "claim.updated"
    assert ledger.verify_hash_chain(created["claim_id"]) is True
    _cleanup(engine, created["claim_id"])


def test_status_transition_event(ledger, engine) -> None:
    created = ledger.create_claim(**_base_kwargs(engine))
    transition = ledger.transition_status(
        claim_id=created["claim_id"], new_status="verified", reason="verification passed",
        actor_type="agent", actor_id="skeptic",
    )
    assert transition["to"] == "verified"
    page = ledger.get_claim_page(created["claim_id"])
    assert page["claim"]["status"] == "verified"
    assert page["events"][-1]["event_type"] == "claim.status_changed"
    assert page["events"][-1]["payload"]["to"] == "verified"
    assert ledger.verify_hash_chain(created["claim_id"]) is True
    _cleanup(engine, created["claim_id"])


def test_hash_chain_detects_tampering(ledger, engine) -> None:
    from sqlalchemy import text

    created = ledger.create_claim(**_base_kwargs(engine))
    ledger.update_claim(
        claim_id=created["claim_id"],
        public_statement="v2",
        structured_proposition={"v": 2},
        confidence=0.8,
        evidence_bundle_id=_base_kwargs(engine)["evidence_bundle_id"],
        change_reason="r", actor_type="agent", actor_id="a",
    )
    assert ledger.verify_hash_chain(created["claim_id"]) is True

    # tampering is blocked by the append-only trigger; chain stays intact
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE claim_events SET payload = payload || '{\"tampered\": true}'::jsonb WHERE claim_id = :id"),
                {"id": created["claim_id"]},
            )
    assert ledger.verify_hash_chain(created["claim_id"]) is True
    with engine.connect() as conn:
        tampered = conn.execute(
            text("SELECT payload FROM claim_events WHERE claim_id = :id ORDER BY occurred_at ASC LIMIT 1"),
            {"id": created["claim_id"]},
        ).fetchone()[0]
    assert tampered.get("tampered") is None  # mutation was rejected
    _cleanup(engine, created["claim_id"])


def test_append_only_enforced(ledger, engine) -> None:
    from sqlalchemy import text

    created = ledger.create_claim(**_base_kwargs(engine))
    with pytest.raises(Exception), engine.begin() as conn:
        conn.execute(
            text("DELETE FROM claim_events WHERE claim_id = :id"),
            {"id": created["claim_id"]},
        )
    with pytest.raises(Exception), engine.begin() as conn:
        conn.execute(
            text("UPDATE claim_versions SET public_statement = 'hacked' WHERE claim_id = :id"),
            {"id": created["claim_id"]},
        )
    _cleanup(engine, created["claim_id"])


def test_read_api_missing_claim(ledger) -> None:
    assert ledger.get_claim_page(str(uuid.uuid4())) is None
