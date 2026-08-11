"""Permanent Edition archive, cursor pagination, and DB immutability."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from open_signal.api.editions import EditionArchivePresenter
from open_signal.composer.edition_writer import EditionWriter
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    return create_engine(url)


@pytest.fixture()
def writer(engine) -> EditionWriter:
    return EditionWriter(engine)


def _cleanup(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE daily_editions CASCADE"))


def _candidate(index: int, *, section: str = "expectations-moved") -> dict:
    return {
        "claim_id": str(uuid.uuid4()),
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": "time-series.probability-move",
        "section_id": section,
        "slot_id": "secondary",
        "display_fields": {
            "expectation_title": f"Will archive fixture {index} resolve?",
            "current_probability": 0.6,
            "start_probability": 0.4,
            "delta_percentage_points": 20.0,
            "window": "24h",
            "series": [],
            "source_name": "Fixture",
            "updated_at": "2026-08-11T00:00:00Z",
        },
    }


def test_writer_classifies_and_hashes_public_snapshot(writer, engine) -> None:
    _cleanup(engine)
    published = writer.build_edition(
        [_candidate(1)],
        generated_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
    )

    snapshot = writer.edition_json(published["edition_id"])
    assert snapshot is not None
    assert snapshot["record_class"] == "public_permanent"
    assert snapshot["first_published_at"] == "2026-08-11T01:00:00+00:00"
    assert len(snapshot["payload_hash"]) == 64
    assert [event["event_type"] for event in snapshot["events"]] == ["published"]
    assert snapshot["events"][0]["sequence_no"] == 1
    _cleanup(engine)


def test_public_editions_render_plans_and_events_reject_mutation(
    writer, engine
) -> None:
    _cleanup(engine)
    published = writer.build_edition(
        [_candidate(1)],
        generated_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
    )
    edition_id = published["edition_id"]
    with engine.connect() as conn:
        render_plan_id = conn.execute(
            text("SELECT id FROM render_plans WHERE edition_id = :edition LIMIT 1"),
            {"edition": edition_id},
        ).scalar_one()
        event_id = conn.execute(
            text("SELECT id FROM edition_events WHERE edition_id = :edition LIMIT 1"),
            {"edition": edition_id},
        ).scalar_one()

    statements = [
        (
            "UPDATE daily_editions SET status = 'corrected' WHERE id = :id",
            edition_id,
        ),
        ("DELETE FROM daily_editions WHERE id = :id", edition_id),
        (
            "UPDATE render_plans SET headline = 'rewritten' WHERE id = :id",
            render_plan_id,
        ),
        ("DELETE FROM render_plans WHERE id = :id", render_plan_id),
        (
            "UPDATE edition_events SET reason = 'rewritten' WHERE id = :id",
            event_id,
        ),
        ("DELETE FROM edition_events WHERE id = :id", event_id),
    ]
    for statement, target_id in statements:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(statement), {"id": target_id})
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO edition_events
                  (edition_id, sequence_no, event_type, actor,
                   previous_event_hash, event_hash)
                VALUES (:edition, 99, 'withdrawn', 'test', NULL, :hash)
                """
            ),
            {"edition": edition_id, "hash": "c" * 64},
        )
    _cleanup(engine)


def test_non_public_operational_row_remains_mutable(engine) -> None:
    _cleanup(engine)
    edition_id = uuid.uuid4()
    generated_at = datetime(2026, 8, 11, 3, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO daily_editions
                  (id, edition_date, generated_at, status,
                   included_section_ids, included_claim_ids, composer_version,
                   component_versions, edition_payload)
                VALUES
                  (:id, :edition_date, :generated_at, 'draft',
                   ARRAY[]::text[], ARRAY[]::uuid[], 'test', '{}'::jsonb,
                   '{"draft": true}'::jsonb)
                """
            ),
            {
                "id": edition_id,
                "edition_date": date(2026, 8, 11),
                "generated_at": generated_at,
            },
        )
        conn.execute(
            text("UPDATE daily_editions SET trigger_type = 'manual' WHERE id = :id"),
            {"id": edition_id},
        )
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT record_class, first_published_at, trigger_type, payload_hash "
                "FROM daily_editions WHERE id = :id"
            ),
            {"id": edition_id},
        ).one()
    assert row[0] == "operational_ttl"
    assert row[1] is None
    assert row[2] == "manual"
    assert len(row[3]) == 64

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_editions WHERE id = :id"), {"id": edition_id})


def test_operational_row_cannot_be_published_in_place(engine) -> None:
    _cleanup(engine)
    edition_id = uuid.uuid4()
    generated_at = datetime(2026, 8, 11, 4, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO daily_editions
                  (id, edition_date, generated_at, status,
                   included_section_ids, included_claim_ids, composer_version,
                   component_versions, edition_payload)
                VALUES
                  (:id, :edition_date, :generated_at, 'draft',
                   ARRAY[]::text[], ARRAY[]::uuid[], 'test', '{}'::jsonb,
                   '{}'::jsonb)
                """
            ),
            {
                "id": edition_id,
                "edition_date": date(2026, 8, 11),
                "generated_at": generated_at,
            },
        )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE daily_editions "
                "SET status = 'published', published_at = :published "
                "WHERE id = :id"
            ),
            {"id": edition_id, "published": generated_at},
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_editions WHERE id = :id"), {"id": edition_id})


def test_archive_cursor_walks_all_rows_without_duplicates(writer, engine) -> None:
    _cleanup(engine)
    start = datetime(2026, 8, 11, 5, tzinfo=UTC)
    expected: list[str] = []
    for index in range(5):
        result = writer.build_edition(
            [_candidate(index, section="rules-moved" if index == 0 else "expectations-moved")],
            generated_at=start + timedelta(minutes=index),
        )
        expected.append(result["edition_id"])

    presenter = EditionArchivePresenter(engine)
    first_page = presenter.build(limit=2)
    assert first_page["total_count"] == 5
    assert first_page["has_more"] is True
    assert first_page["facets"]["years"] == [2026]
    assert set(first_page["facets"]["sections"]) == {
        "expectations-moved",
        "rules-moved",
    }

    seen: list[str] = []
    page = first_page
    while True:
        seen.extend(item["id"] for item in page["items"])
        if not page["has_more"]:
            break
        page = presenter.build(cursor=page["next_cursor"], limit=2)

    assert seen == list(reversed(expected))
    assert len(seen) == len(set(seen)) == 5
    assert presenter.build(year=2025)["items"] == []
    assert presenter.build(section="rules-moved")["total_count"] == 1
    assert presenter.build(status="sparse")["total_count"] == 5
    with pytest.raises(ValueError, match="invalid archive cursor"):
        presenter.build(cursor="not-a-cursor")
    _cleanup(engine)


def test_correction_appends_events_without_mutating_source(writer, engine) -> None:
    _cleanup(engine)
    original = writer.build_edition(
        [_candidate(1)],
        generated_at=datetime(2026, 8, 11, 6, tzinfo=UTC),
    )
    original_before = writer.edition_json(original["edition_id"])

    corrected_id = writer.correction(
        original["edition_id"],
        {"correction_note": "clarified"},
        "Clarify wording",
    )
    original_after = writer.edition_json(original["edition_id"])
    corrected = writer.edition_json(corrected_id)

    assert original_after["edition_payload"] == original_before["edition_payload"]
    assert [event["event_type"] for event in original_after["events"]] == [
        "published",
        "superseded",
    ]
    assert [event["event_type"] for event in corrected["events"]] == [
        "published",
        "corrected",
    ]
    assert corrected["events"][1]["previous_event_hash"] == corrected["events"][0][
        "event_hash"
    ]
    _cleanup(engine)
