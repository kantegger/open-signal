"""Edition writer tests (OS-028, OS-029). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import UTC, date, datetime

import pytest
from open_signal.api.editions import FrontPagePresenter
from open_signal.composer.edition_writer import EditionWriter


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def writer(engine) -> EditionWriter:
    return EditionWriter(engine)


CLAIM_UUIDS = [str(uuid.uuid4()) for _ in range(8)]


def _candidate(claim_id: str, section: str = "expectations-moved", **extra) -> dict:
    # claim ids must be uuid-shaped for the uuid[] column
    if "-" not in claim_id:
        idx = int(claim_id[1:]) - 1
        claim_id = CLAIM_UUIDS[idx % len(CLAIM_UUIDS)]
    c = {
        "claim_id": claim_id,
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": "time-series.probability-move",
        "section_id": section,
        "slot_id": "secondary",
        "display_fields": {
            "expectation_title": "Will X happen?",
            "current_probability": 0.6,
            "start_probability": 0.4,
            "delta_percentage_points": 20.0,
            "window": "24h",
            "series": [],
            "source_name": "Polymarket",
            "updated_at": "2026-08-07T12:00:00Z",
        },
    }
    c.update(extra)
    return c


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE daily_editions CASCADE"))
        conn.execute(text("DELETE FROM render_plans"))


# ------------------------------------------------------------------ OS-028


def test_build_edition_with_lead(writer, engine) -> None:
    _cleanup(engine)
    candidates = [
        _candidate(
            "c1",
            slot_id="lead",
            component_id="signal-hero.expectations",
            display_fields={
                "expectation_title": "Hero",
                "current_probability": 0.6,
                "start_probability": 0.4,
                "delta_percentage_points": 20.0,
                "window": "24h",
                "series": [],
                "source_name": "P",
                "updated_at": "t",
                "headline": "Hero headline",
                "primary_observation": "YES 概率上升 20pp",
            },
        ),
        _candidate("c2"),
        _candidate(
            "c3",
            section="rules-moved",
            slot_id="main",
            component_id="state-transition.rule-stage",
            display_fields={
                "rule_title": "Rule",
                "previous_state": "proposed",
                "current_state": "final",
                "transition_date": "2026-08-01",
                "authority": "CPSC",
                "source_url": "https://x",
            },
        ),
    ]
    result = writer.build_edition(candidates, edition_date=date(2026, 8, 7))
    assert result["edition_id"] is not None
    assert result["status"] == "published"
    assert CLAIM_UUIDS[0] in result["claim_ids"]  # c1 -> CLAIM_UUIDS[0]
    assert result["cache_key"].startswith("edition/2026-08-07/")

    payload = writer.edition_json(result["edition_id"])
    assert payload["status"] == "published"
    assert payload["edition_payload"]["lead"]["component_id"] == "signal-hero.expectations"
    _cleanup(engine)


def test_sparse_edition(writer, engine) -> None:
    _cleanup(engine)
    # fewer than threshold items -> sparse
    result = writer.build_edition(
        [_candidate("c1")], edition_date=date(2026, 8, 7), section_maturity="production"
    )
    assert result["status"] == "sparse"
    assert writer.edition_json(result["edition_id"])["status"] == "sparse"
    from sqlalchemy import text

    with engine.connect() as conn:
        audit = conn.execute(
            text(
                "SELECT action, detail FROM audit_events "
                "WHERE target = :target ORDER BY created_at DESC LIMIT 1"
            ),
            {"target": result["edition_id"]},
        ).fetchone()
    assert audit is not None
    assert audit[0] == "publication.snapshot.published"
    assert audit[1]["item_count"] == 1
    _cleanup(engine)


def test_hard_expiry_atomically_publishes_complete_empty_page(writer, engine) -> None:
    _cleanup(engine)
    initial = writer.build_edition(
        [_candidate("c1")],
        edition_date=date(2026, 8, 7),
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
    )

    retired = writer.build_rolling_edition(
        [],
        refreshed_section_ids=set(),
        trigger_type="hard_expiry",
        generated_at=datetime(2026, 8, 10, 13, tzinfo=UTC),
    )

    assert retired["item_count"] == 0
    assert retired["supersedes_edition_id"] == initial["edition_id"]
    assert writer.current_edition_id() == retired["edition_id"]
    from sqlalchemy import text

    with engine.connect() as conn:
        plan_count = conn.execute(
            text("SELECT count(*) FROM render_plans WHERE edition_id = :id"),
            {"id": retired["edition_id"]},
        ).scalar_one()
    assert plan_count == 0

    page = FrontPagePresenter(engine).build()
    assert page is not None
    assert page["snapshot"]["id"] == retired["edition_id"]
    assert [slot["type"] for slot in page["slots"]] == [
        "lead",
        "secondary",
        "live_feed",
        "digest",
        "main",
        "utility",
        "archive",
    ]
    assert all(slot["items"] == [] for slot in page["slots"])
    _cleanup(engine)


def test_freshness_reconcile_is_noop_until_meaning_changes(writer, engine) -> None:
    _cleanup(engine)
    initial = writer.build_edition(
        [_candidate("c1")],
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
    )

    unchanged = writer.reconcile_freshness(
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )
    assert unchanged["published"] is False
    assert writer.current_edition_id() == initial["edition_id"]

    retired = writer.reconcile_freshness(
        generated_at=datetime(2026, 8, 10, 14, tzinfo=UTC)
    )
    assert retired["published"] is True
    assert retired["item_count"] == 0
    assert writer.current_edition_id() == retired["edition_id"]
    _cleanup(engine)


def test_claims_not_modified(writer, engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    # claim ids are placeholders; build must not touch claims table
    before = engine.connect().execute(text("SELECT count(*) FROM claims")).scalar_one()
    writer.build_edition([_candidate("c1"), _candidate("c2")], edition_date=date(2026, 8, 7))
    after = engine.connect().execute(text("SELECT count(*) FROM claims")).scalar_one()
    assert after == before
    _cleanup(engine)


# ------------------------------------------------------------------ OS-029


def test_render_plans_written(writer, engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    result = writer.build_edition(
        [_candidate("c1"), _candidate("c2")], edition_date=date(2026, 8, 7)
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT slot_id, component_id, claim_ids FROM render_plans WHERE edition_id = :id"
            ),
            {"id": result["edition_id"]},
        ).fetchall()
    assert len(rows) >= 1
    assert rows[0][1] == "time-series.probability-move"
    _cleanup(engine)


def test_archive_snapshot(writer, engine) -> None:
    _cleanup(engine)
    result = writer.build_edition([_candidate("c1")], edition_date=date(2026, 8, 7))
    snapshot = writer.snapshot(result["edition_id"])
    assert snapshot["immutable"] is True
    assert snapshot["snapshot"]["id"] == result["edition_id"]
    _cleanup(engine)


def test_correction_creates_new_row(writer, engine) -> None:
    _cleanup(engine)
    result = writer.build_edition([_candidate("c1")], edition_date=date(2026, 8, 7))
    corrected_id = writer.correction(result["edition_id"], {"lead": None}, "fix headline")
    corrected = writer.edition_json(corrected_id)
    assert corrected["correction_count"] == 1
    assert corrected["edition_payload"]["correction_reason"] == "fix headline"
    assert corrected_id != result["edition_id"]
    _cleanup(engine)


def test_rollback_restores_snapshot(writer, engine) -> None:
    _cleanup(engine)
    result = writer.build_edition([_candidate("c1")], edition_date=date(2026, 8, 7))
    original = writer.edition_json(result["edition_id"])
    # rollback to the original snapshot
    rolled = writer.rollback(result["edition_id"], "restore original")
    payload = writer.edition_json(rolled)
    assert payload["edition_payload"]["rollback_from"] == result["edition_id"]
    assert payload["edition_payload"]["edition_date"] == original["edition_payload"]["edition_date"]
    _cleanup(engine)


def test_cache_key_content_addressed(writer, engine) -> None:
    _cleanup(engine)
    a = writer.build_edition([_candidate("c1")], edition_date=date(2026, 8, 7))
    b = writer.build_edition([_candidate("c2")], edition_date=date(2026, 8, 7))
    assert a["cache_key"] != b["cache_key"]  # different generated_at
    assert a["cache_key"].split("/")[1] == "2026-08-07"
    _cleanup(engine)
