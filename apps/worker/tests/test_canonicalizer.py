"""Expectation canonicalizer tests (OS-009). Requires a real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from open_signal.canonical.canonicalizer import ExpectationCanonicalizer


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def canon(engine) -> ExpectationCanonicalizer:
    return ExpectationCanonicalizer(engine)


def test_binary_eligible_creates(canon, engine) -> None:
    mid = str(uuid.uuid4())
    ce = canon.canonicalize_source_market(
        mid,
        question="Will X happen in 2027?",
        outcome_labels=["Yes", "No"],
        ends_at="2027-12-31T00:00:00Z",
        event_type="politics",
        payload={"id": 1},
    )
    assert ce is not None
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT canonical_question, outcome_type, event_type, "
                "resolution_deadline_at, status, source_market_ids "
                "FROM canonical_expectations WHERE id = :id"
            ),
            {"id": ce},
        ).fetchone()
    assert row[0] == "Will X happen in 2027?"
    assert row[1] == "binary"
    assert row[2] == "politics"
    assert row[4] == "active"
    assert uuid.UUID(mid) in row[5]


def test_idempotent_returns_same(canon, engine) -> None:
    mid = str(uuid.uuid4())
    ce1 = canon.canonicalize_source_market(
        mid, question="Q?", outcome_labels=["Yes", "No"], ends_at="2027-01-01T00:00:00Z"
    )
    ce2 = canon.canonicalize_source_market(
        mid, question="Q?", outcome_labels=["Yes", "No"], ends_at="2027-01-01T00:00:00Z"
    )
    assert ce1 == ce2
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM canonical_expectations WHERE id = :id"), {"id": ce1}).scalar_one()
    assert count == 1


def test_non_binary_skipped(canon) -> None:
    assert (
        canon.canonicalize_source_market(
            str(uuid.uuid4()),
            question="Which party wins?",
            outcome_labels=["A", "B", "C"],
            ends_at="2027-01-01T00:00:00Z",
        )
        is None
    )


def test_no_yes_direction_skipped(canon) -> None:
    assert (
        canon.canonicalize_source_market(
            str(uuid.uuid4()),
            question="Who wins?",
            outcome_labels=["Candidate A", "Candidate B"],
            ends_at="2027-01-01T00:00:00Z",
        )
        is None
    )


def test_missing_deadline_skipped(canon) -> None:
    assert (
        canon.canonicalize_source_market(
            str(uuid.uuid4()),
            question="Q?",
            outcome_labels=["Yes", "No"],
            ends_at=None,
        )
        is None
    )


def test_force_recreates(canon, engine) -> None:
    mid = str(uuid.uuid4())
    ce1 = canon.canonicalize_source_market(
        mid, question="Old?", outcome_labels=["Yes", "No"], ends_at="2027-01-01T00:00:00Z"
    )
    ce2 = canon.canonicalize_source_market(
        mid, question="New?", outcome_labels=["Yes", "No"], ends_at="2027-01-01T00:00:00Z",
        force=True,
    )
    assert ce1 == ce2  # same market -> same expectation (updated, not duplicated)
    from sqlalchemy import text

    with engine.connect() as conn:
        q = conn.execute(
            text("SELECT canonical_question FROM canonical_expectations WHERE id = :id"),
            {"id": ce1},
        ).scalar_one()
    assert q == "New?"


def test_force_does_not_refresh_updated_at_when_meaning_is_unchanged(
    canon,
    engine,
) -> None:
    from sqlalchemy import text

    market_id = str(uuid.uuid4())
    payload = {"id": market_id, "rules": "unchanged"}
    expectation_id = canon.canonicalize_source_market(
        market_id,
        question="Will the unchanged event happen?",
        outcome_labels=["Yes", "No"],
        ends_at="2027-01-01T00:00:00Z",
        event_type="test",
        rules_text="unchanged",
        payload=payload,
    )
    sentinel = datetime(2020, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE canonical_expectations SET updated_at = :sentinel "
                "WHERE id = :id"
            ),
            {"sentinel": sentinel, "id": expectation_id},
        )

    canon.canonicalize_source_market(
        market_id,
        question="Will the unchanged event happen?",
        outcome_labels=["Yes", "No"],
        ends_at="2027-01-01T00:00:00Z",
        event_type="test",
        rules_text="unchanged",
        payload=payload,
        force=True,
    )

    with engine.connect() as conn:
        updated_at = conn.execute(
            text("SELECT updated_at FROM canonical_expectations WHERE id = :id"),
            {"id": expectation_id},
        ).scalar_one()
    assert updated_at == sentinel
