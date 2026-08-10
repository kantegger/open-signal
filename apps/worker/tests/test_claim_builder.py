"""Deterministic claim construction tests (OS-011). Requires real PostgreSQL
via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0005 applied).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.agents.claim_builder import (
    CAPABILITY_ID,
    DESK_ID,
    LINEAGE_ID,
    SECTION_ID,
    DeterministicClaimBuilder,
)
from open_signal.derived.candidates import CandidateDetector
from open_signal.sources.registry import Registry


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_market(engine, external_id: str, question: str) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM sources WHERE slug = 'os011-source'")).fetchone()
        if row:
            source_uuid = str(row[0])
        else:
            row = conn.execute(
                text(
                    "INSERT INTO sources (slug, name, category, authority_level, "
                    "access_mode, adapter_id, status) "
                    "VALUES ('os011-source', 'OS011', 'prediction_market', "
                    "'licensed_aggregator', 'rest', 'os011', 'active') RETURNING id"
                )
            ).fetchone()
            source_uuid = str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO source_markets (source_id, external_market_id, question, "
                "outcome_labels, token_ids, ends_at, status) "
                "VALUES (:s, :e, :q, ARRAY['Yes','No'], ARRAY['1','2'], "
                "'2027-12-31T00:00:00Z', 'active') RETURNING id"
            ),
            {"s": source_uuid, "e": external_id, "q": question},
        ).fetchone()
        return str(row[0])


def _seed_canonical(engine, market_uuid: str, question: str) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO canonical_expectations "
                "(canonical_question, event_type, outcome_type, resolution_deadline_at, "
                "resolution_rule_summary, resolution_rule_hash, source_market_ids, status, "
                "canonicalization_version) "
                "VALUES (:q, 'politics', 'binary', '2027-12-31T00:00:00Z', :q, 'h', "
                "ARRAY[:m]::uuid[], 'active', '0.1.0') RETURNING id"
            ),
            {"q": question, "m": market_uuid},
        ).fetchone()
        return str(row[0])


def _seed_series(engine, market_uuid: str, probs: list[float], now: datetime) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for i, p in enumerate(probs):
            t = now - timedelta(minutes=5 * (len(probs) - 1 - i))
            conn.execute(
                text(
                    "INSERT INTO market_observations (source_market_id, observed_at, "
                    "probability, best_bid, best_ask, midpoint, price_method, data_quality_flags) "
                    "VALUES (:m, :t, :p, :b, :a, :p, 'source_probability', '{}')"
                ),
                {"m": market_uuid, "t": t, "p": p, "b": max(0.0, p - 0.005), "a": min(1.0, p + 0.005)},
            )


@pytest.fixture()
def builder(engine) -> DeterministicClaimBuilder:
    return DeterministicClaimBuilder(engine)


def _cleanup(engine, market_uuid: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_observations WHERE source_market_id = :m"), {"m": market_uuid})
        # claim_versions / claim_events are append-only (prevent_mutation
        # trigger blocks DELETE); TRUNCATE bypasses row triggers.
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM investigation_runs WHERE candidate_id = :m"), {"m": market_uuid})
        conn.execute(text("DELETE FROM calculation_records WHERE subject_id = :m"), {"m": market_uuid})
        conn.execute(text("DELETE FROM canonical_expectations WHERE source_market_ids @> ARRAY[:m]::uuid[]"), {"m": market_uuid})


def test_full_pipeline(builder, engine) -> None:
    # sync desks first (from registry)
    Registry.load().sync_desks(engine)

    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    market_uuid = _seed_market(engine, str(uuid.uuid4()), "Will X happen?")
    ce_id = _seed_canonical(engine, market_uuid, "Will X happen?")
    _seed_series(engine, market_uuid, [0.40 + 0.20 * (i / 29) for i in range(30)], now)

    detector = CandidateDetector(engine)
    output = detector.compute_for_market(market_uuid, now=now)
    assert output["eligible"] is True
    calc_id = detector.record_calculation(market_uuid, output)
    output["_calc_record_id"] = calc_id

    result = builder.build_from_candidate(
        source_market_id=market_uuid,
        canonical_expectation_id=ce_id,
        calculation=output,
        now=now,
    )
    duplicate = builder.build_from_candidate(
        source_market_id=market_uuid,
        canonical_expectation_id=ce_id,
        calculation=output,
        now=now,
    )
    assert duplicate["created"] is False
    assert duplicate["claim_id"] == result["claim_id"]

    from sqlalchemy import text

    with engine.connect() as conn:
        claim = conn.execute(
            text(
                "SELECT claim_type, desk_id, status, confidence, valid_from, "
                "valid_until FROM claims WHERE id = :id"
            ),
            {"id": result["claim_id"]},
        ).fetchone()
        si = conn.execute(
            text("SELECT section_id, capability_id FROM section_instances WHERE id = :id"),
            {"id": result["section_instance_id"]},
        ).fetchone()
        bundle = conn.execute(
            text("SELECT headline_claim_id FROM claim_bundles WHERE section_instance_id = :id"),
            {"id": result["section_instance_id"]},
        ).fetchone()

    assert claim[0] == "derived_observation"
    assert claim[1] == DESK_ID
    assert claim[2] == "draft"
    assert float(claim[3]) == 0.9
    assert claim[4] == now
    assert claim[5] == now + timedelta(hours=72)
    assert si[0] == SECTION_ID
    assert si[1] == CAPABILITY_ID
    assert str(bundle[0]) == result["claim_id"]

    rc = result["render_candidate"]
    assert rc["component_id"] == "time-series.probability-move"
    assert rc["display_fields"]["delta_percentage_points"] == 20.0
    assert rc["display_fields"]["series_quality"]["observation_count"] == 30
    assert rc["display_fields"]["series_quality"]["coverage_status"] == "partial_window"
    assert rc["slot_id"] == "secondary"

    _cleanup(engine, market_uuid)


def test_lineage_created(builder, engine) -> None:
    builder.ensure_lineage()
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT desk_id, status FROM agent_lineages WHERE id = :id"),
            {"id": LINEAGE_ID},
        ).fetchone()
    assert row is not None
    assert row[0] == DESK_ID
