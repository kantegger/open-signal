"""Candidate detection tests (OS-010). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0004 applied).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.derived.candidates import CandidateDetector
from open_signal.sources.market_obs import floor_to_bucket


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def detector(engine) -> CandidateDetector:
    return CandidateDetector(engine)


def _seed_market(engine, external_id: str, question: str) -> str:
    """Insert a source_market row; returns its uuid."""
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM sources WHERE slug = 'os010-source'")
        ).fetchone()
        if row:
            source_uuid = str(row[0])
        else:
            row = conn.execute(
                text(
                    "INSERT INTO sources (slug, name, category, authority_level, "
                    "access_mode, adapter_id, status) "
                    "VALUES ('os010-source', 'OS010', 'prediction_market', "
                    "'licensed_aggregator', 'rest', 'os010', 'active') RETURNING id"
                )
            ).fetchone()
            source_uuid = str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO source_markets (source_id, external_market_id, question, "
                "outcome_labels, token_ids, ends_at, status, raw_source_record_id) "
                "VALUES (:s, :e, :q, ARRAY['Yes','No'], ARRAY['1','2'], "
                "'2027-12-31T00:00:00Z', 'active', NULL) RETURNING id"
            ),
            {"s": source_uuid, "e": external_id, "q": question},
        ).fetchone()
        return str(row[0])


def _seed_series(engine, market_uuid: str, probabilities: list[float], now: datetime) -> None:
    """Insert bucket observations at 5-minute intervals ending at ``now``."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for i, p in enumerate(probabilities):
            t = floor_to_bucket(now - timedelta(minutes=5 * (len(probabilities) - 1 - i)), 5)
            conn.execute(
                text(
                    """
                    INSERT INTO market_observations
                      (source_market_id, observed_at, probability,
                       best_bid, best_ask, midpoint, price_method, data_quality_flags)
                    VALUES (:m, :t, :p, :bid, :ask, :mid, 'source_probability', '{}')
                    """
                ),
                {
                    "m": market_uuid,
                    "t": t,
                    "p": p,
                    "bid": max(0.0, p - 0.005),
                    "ask": min(1.0, p + 0.005),
                    "mid": p,
                },
            )


def _cleanup(engine, market_uuid: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_observations WHERE source_market_id = :m"), {"m": market_uuid})
        conn.execute(text("DELETE FROM calculation_records WHERE subject_id = :m"), {"m": market_uuid})


# ----------------------------------------------------------------- tests


def test_compute_metrics_flat_series(detector, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    _seed_series(engine, mid, [0.5] * 30, now)  # flat
    output = detector.compute_for_market(mid, now=now)
    _cleanup(engine, mid)
    assert output["delta_24h"] == 0.0
    assert output["direction"] == 0
    assert output["eligible"] is False


def test_compute_delta_and_eligible(detector, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    # steady rise from 0.40 -> 0.60 over 24h: delta_24h = +20pp
    probs = [0.40 + 0.20 * (i / 29) for i in range(30)]
    _seed_series(engine, mid, probs, now)
    output = detector.compute_for_market(mid, now=now)
    _cleanup(engine, mid)
    assert output["delta_24h"] == 20.0
    assert output["direction"] == 1
    assert output["persistence"] > 0.9
    assert output["eligible"] is True


def test_candidate_rejected_when_below_threshold(detector, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    # small move 0.50 -> 0.52 (+2pp < 3pp)
    probs = [0.50 + 0.02 * (i / 29) for i in range(30)]
    _seed_series(engine, mid, probs, now)
    output = detector.compute_for_market(mid, now=now)
    _cleanup(engine, mid)
    assert output["delta_24h"] == 2.0
    assert output["eligible"] is False


def test_candidate_rejected_on_bad_data_quality(detector, engine) -> None:
    from sqlalchemy import text

    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    _seed_series(engine, mid, [0.40 + 0.20 * (i / 29) for i in range(30)], now)
    # mark last observation as stale
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE market_observations SET data_quality_flags = ARRAY['stale'] WHERE source_market_id = :m"),
            {"m": mid},
        )
    output = detector.compute_for_market(mid, now=now)
    _cleanup(engine, mid)
    assert output["data_quality"] != "ok"
    assert output["eligible"] is False


def test_reversal_detected(detector, engine) -> None:
    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    _cleanup(engine, mid)
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    # up then down sharply: 0.40 -> 0.80 -> 0.55
    probs = [0.40 + 0.40 * (i / 14) for i in range(15)] + [0.80 - 0.25 * (i / 14) for i in range(15)]
    _seed_series(engine, mid, probs, now)
    output = detector.compute_for_market(mid, now=now)
    _cleanup(engine, mid)
    assert output["reversal"] is True


def test_record_calculation_writes_row(detector, engine) -> None:
    from sqlalchemy import text

    mid = _seed_market(engine, str(uuid.uuid4()), "Q?")
    output = {"delta_24h": 5.0, "eligible": True}
    calc_id = detector.record_calculation(mid, output, {"n": 1})
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT calculation_type, subject_type, output FROM calculation_records WHERE id = :id"),
            {"id": calc_id},
        ).fetchone()
    assert row[0] == "candidate_detection"
    assert row[1] == "source_market"
    assert row[2]["eligible"] is True
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM calculation_records WHERE id = :id"), {"id": calc_id})
