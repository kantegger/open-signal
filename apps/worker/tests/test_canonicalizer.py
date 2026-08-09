"""Expectation canonicalizer tests (OS-009). Requires a real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid

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
