"""Evidence bundle builder tests (OS-016). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from open_signal.agents.evidence import EvidenceBundleBuilder


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_market(engine, external_id: str) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM sources WHERE slug = 'os016-source'")).fetchone()
        if row:
            source_uuid = str(row[0])
        else:
            row = conn.execute(
                text(
                    "INSERT INTO sources (slug, name, category, authority_level, "
                    "access_mode, adapter_id, status) "
                    "VALUES ('os016-source', 'OS016', 'prediction_market', "
                    "'licensed_aggregator', 'rest', 'os016', 'active') RETURNING id"
                )
            ).fetchone()
            source_uuid = str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO source_markets (source_id, external_market_id, question, "
                "outcome_labels, token_ids, ends_at, status) "
                "VALUES (:s, :e, 'Q?', ARRAY['Yes','No'], ARRAY['1','2'], "
                "'2027-12-31T00:00:00Z', 'active') RETURNING id"
            ),
            {"s": source_uuid, "e": external_id},
        ).fetchone()
        return str(row[0])


def _seed_series(engine, market_uuid: str, probs: list[float], now: datetime) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for i, p in enumerate(probs):
            t = now - timedelta(minutes=5 * (len(probs) - 1 - i))
            flags = ["stale"] if i == 3 else []
            conn.execute(
                text(
                    "INSERT INTO market_observations (source_market_id, observed_at, "
                    "probability, best_bid, best_ask, midpoint, spread, price_method, "
                    "data_quality_flags) "
                    "VALUES (:m, :t, :p, :b, :a, :p, 0.01, 'source_probability', :flags)"
                ),
                {"m": market_uuid, "t": t, "p": p, "b": max(0.0, p - 0.005), "a": min(1.0, p + 0.005), "flags": flags},
            )


def _cleanup(engine, market_uuid: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_observations WHERE source_market_id = :m"), {"m": market_uuid})
        conn.execute(
            text("DELETE FROM evidence_bundles WHERE source_coverage->>'source_markets' LIKE :m"),
            {"m": f'%{market_uuid}%'},
        )


@pytest.fixture()
def builder(engine) -> EvidenceBundleBuilder:
    return EvidenceBundleBuilder(engine)


def test_build_for_candidate(builder, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()))
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    probs = [0.40 + 0.20 * (i / 39) for i in range(40)]
    _seed_series(engine, mid, probs, now)

    calculation = {
        "delta_24h": 20.0,
        "direction": 1,
        "eligible": True,
        "data_completeness": 0.8,
        "series_size": 40,
    }
    result = builder.build_for_candidate(
        source_market_id=mid,
        calculation=calculation,
        token_budget=4000,
    )
    _cleanup(engine, mid)

    assert result["bundle_id"] is not None
    assert result["primary_items"] == 24  # capped at max_primary
    assert result["historical_items"] >= 0
    assert result["counterexamples"] == 1  # the stale observation
    assert result["token_estimate"] <= result["token_budget"]
    assert len(result["snapshot_hash"]) == 64


def test_snapshot_hash_is_stable(builder, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()))
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    _seed_series(engine, mid, [0.5] * 10, now)

    calc = {"delta_24h": 0.0, "direction": 0, "eligible": False}
    r1 = builder.build_for_candidate(source_market_id=mid, calculation=calc)
    r2 = builder.build_for_candidate(source_market_id=mid, calculation=calc)
    _cleanup(engine, mid)
    assert r1["snapshot_hash"] == r2["snapshot_hash"]


def test_persisted_row_matches(builder, engine) -> None:
    from sqlalchemy import text

    mid = _seed_market(engine, str(uuid.uuid4()))
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    _seed_series(engine, mid, [0.5] * 6, now)

    result = builder.build_for_candidate(source_market_id=mid, calculation={"delta_24h": 0.0})
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT primary_evidence, data_calculation_ids, snapshot_hash "
                "FROM evidence_bundles WHERE id = :id"
            ),
            {"id": result["bundle_id"]},
        ).fetchone()
    assert len(row[0]) == result["primary_items"]
    assert row[1] == []  # no calc record id passed
    assert row[2] == result["snapshot_hash"]
    _cleanup(engine, mid)
