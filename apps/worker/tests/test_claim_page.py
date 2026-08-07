"""Claim page presenter + API tests (OS-030). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid

import pytest
from open_signal.api.presenters import ClaimPagePresenter
from open_signal.claims.ledger import ClaimsLedger


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_context(engine) -> tuple[str, str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                "VALUES ('os030-desk', 'OS030', 't', 'v1', 'shadow') ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                "model_version, charter_id, charter_version, toolset_version, "
                "context_builder_version, status, activated_at) "
                "VALUES ('os030-lineage', 'os030-desk', 'Expectations Observation', "
                "'deepseek-chat', 'v1', 'expectations-desk-charter', 'os-030', 'v1', "
                "'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
            )
        )
        run = conn.execute(
            text(
                "INSERT INTO investigation_runs (desk_id, section_id, capability_id, "
                "agent_lineage_id, model_version, charter_version, status) "
                "VALUES ('os030-desk', 'expectations-moved', 'expectation.persistence', "
                "'os030-lineage', 'deepseek-chat', 'os-030', 'completed') RETURNING id"
            )
        ).fetchone()
        eb = conn.execute(
            text(
                "INSERT INTO evidence_bundles (primary_evidence, supporting_evidence, "
                "counter_evidence, data_calculation_ids, source_coverage, snapshot_hash) "
                "VALUES (CAST(:p AS jsonb), '[]'::jsonb, CAST(:c AS jsonb), "
                "ARRAY[]::uuid[], '{}'::jsonb, :h) RETURNING id"
            ),
            {
                "p": json.dumps([{"observed_at": "2026-08-07T10:00:00Z", "probability": 0.6}]),
                "c": json.dumps([{"observed_at": "2026-08-06T10:00:00Z", "flags": ["stale"]}]),
                "h": uuid.uuid4().hex,
            },
        ).fetchone()
        return str(eb[0]), str(run[0])


def _create_claim(engine) -> str:
    eb, run = _seed_context(engine)
    ledger = ClaimsLedger(engine)
    result = ledger.create_claim(
        desk_id="os030-desk",
        section_id="expectations-moved",
        capability_id="expectation.persistence",
        claim_type="agent_observation",
        public_statement="YES 概率过去 24 小时上升 20 个百分点，方向持续。",
        structured_proposition={"predicate": "price_persistence", "operator": "is", "value": "persistent"},
        confidence=0.85,
        evidence_bundle_id=eb,
        agent_lineage_id="os030-lineage",
        model_version="deepseek-chat",
        charter_version="os-030",
        run_id=run,
        epistemic_status="agent_judgment",
    )
    ledger.update_claim(
        claim_id=result["claim_id"],
        public_statement="YES 概率过去 24 小时上升 25 个百分点（复核修正）。",
        structured_proposition={"predicate": "price_persistence", "operator": "is", "value": "persistent"},
        confidence=0.9,
        evidence_bundle_id=eb,
        change_reason="skeptic 复核",
        actor_type="agent",
        actor_id="skeptic",
    )
    return result["claim_id"]


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM evidence_bundles"))
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))


def test_claim_page_all_blocks(engine) -> None:
    _cleanup(engine)
    cid = _create_claim(engine)
    presenter = ClaimPagePresenter(engine)
    page = presenter.build(cid)
    assert page is not None

    # all eight display blocks present
    assert page["claim"]["id"] == cid
    assert "上升" in page["observation"]
    assert page["analysis"]["operator"] == "is"
    assert page["assessment"]["confidence"] == 0.9
    assert len(page["evidence"]["items"]) == 1
    assert len(page["counterevidence"]["items"]) == 1
    assert page["agent_lineage"]["foundation_model"] == "deepseek-chat"
    assert page["claim"]["claim_type"] == "agent_observation"
    assert len(page["version_history"]) == 2
    _cleanup(engine)


def test_claim_page_missing(engine) -> None:
    presenter = ClaimPagePresenter(engine)
    assert presenter.build(str(uuid.uuid4())) is None


def test_api_endpoints(engine) -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    import apps.api.main as api

    api._engine = lambda: engine  # inject test engine

    _cleanup(engine)
    cid = _create_claim(engine)
    client = TestClient(api.app)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = client.get(f"/api/claims/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["claim"]["id"] == cid
    assert body["agent_lineage"]["name"] == "Expectations Observation"

    r = client.get("/api/claims/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404

    r = client.get("/api/editions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    _cleanup(engine)
