"""Edition writer tests (OS-028, OS-029). Requires real PostgreSQL via
OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from open_signal.api.editions import FrontPagePresenter
from open_signal.composer.edition_writer import (
    EditionWriter,
    _continuity_source_is_live,
)


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
    result = writer.build_edition(
        candidates,
        edition_date=date(2026, 8, 7),
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
    )
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
        [_candidate("c1")],
        edition_date=date(2026, 8, 7),
        section_maturity="production",
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
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


def test_snapshot_captures_typed_publication_context(writer, engine) -> None:
    _cleanup(engine)
    result = writer.build_edition(
        [_candidate("c1")],
        generated_at=datetime.now(UTC),
        section_maturity="beta",
    )

    stored = writer.edition_json(result["edition_id"])
    context = stored["edition_payload"]["publication_context"]
    assert context["snapshot_bound"] is True
    assert context["version"] == "1.7.0"
    assert len(context["research_fingerprint"]) == 64
    assert set(context) >= {
        "counts",
        "claims",
        "expectations",
        "expectation_events",
        "rules",
        "research",
        "coverage",
    }

    page = FrontPagePresenter(engine).build()
    assert page is not None
    assert page["publication_context"] == context
    _cleanup(engine)


def test_scanner_refresh_retains_current_featured_item(writer, engine) -> None:
    _cleanup(engine)
    old_lead = _candidate(
        "c1",
        slot_id="lead",
        component_id="signal-hero.expectations",
        display_fields={
            "expectation_title": "Durable featured signal",
            "current_probability": 0.72,
            "start_probability": 0.61,
            "delta_percentage_points": 11.0,
            "window": "24h",
            "series": [],
            "source_name": "Polymarket",
            "updated_at": "2026-08-07T12:00:00Z",
            "headline": "Durable featured signal",
            "primary_observation": "The featured move remains valid.",
        },
        headline="Durable featured signal",
        priority=10,
    )
    initial = writer.build_edition(
        [old_lead],
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
        section_maturity="beta",
    )
    scanner = _candidate(
        "c2",
        slot_id="live_feed",
        component_id="signal-feed.compact-change",
        component_variant="compact",
        display_fields={
            "change_title": "A second market moved",
            "change_value": "+1.2pp · 58%",
            "claim_type": "derived_observation",
            "source_name": "Polymarket",
            "updated_at": "2026-08-07T13:30:00Z",
        },
        headline="A second market moved",
        priority=100,
    )

    refreshed = writer.build_rolling_edition(
        [scanner],
        refreshed_section_ids={"expectations-moved"},
        retain_refreshed_items=True,
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC),
        section_maturity="beta",
    )

    assert refreshed["supersedes_edition_id"] == initial["edition_id"]
    assert set(refreshed["claim_ids"]) == {CLAIM_UUIDS[0], CLAIM_UUIDS[1]}
    from sqlalchemy import text

    with engine.connect() as conn:
        slots = conn.execute(
            text(
                "SELECT slot_id FROM render_plans WHERE edition_id = :edition "
                "ORDER BY slot_id"
            ),
            {"edition": refreshed["edition_id"]},
        ).scalars().all()
    assert slots == ["lead", "live_feed"]
    _cleanup(engine)


def test_refresh_replaces_old_editorial_surfaces_before_section_cap(
    writer, engine, monkeypatch
) -> None:
    _cleanup(engine)
    old_lead = _candidate(
        "c1",
        slot_id="lead",
        component_id="signal-hero.expectations",
        display_fields={
            **_candidate("c1")["display_fields"],
            "headline": "Old lead",
            "primary_observation": "Old lead observation.",
        },
        headline="Old lead",
    )
    old_feed = _candidate(
        "c4",
        slot_id="live_feed",
        component_id="signal-feed.compact-change",
        component_variant="compact",
        display_fields={
            "change_title": "Still-current scanner item",
            "change_value": "+2.0pp · 62%",
            "claim_type": "derived_observation",
            "source_name": "Polymarket",
            "updated_at": "2026-08-07T12:00:00Z",
        },
        headline="Still-current scanner item",
    )
    monkeypatch.setattr(
        writer,
        "_current_candidates",
        lambda: [
            old_lead,
            _candidate("c2", slot_id="secondary"),
            _candidate("c3", slot_id="main"),
            old_feed,
        ],
    )

    new_lead = _candidate(
        "c5",
        slot_id="lead",
        component_id="signal-hero.expectations",
        display_fields={
            **_candidate("c5")["display_fields"],
            "headline": "New lead",
            "primary_observation": "New lead observation.",
        },
        headline="New lead",
        priority=10,
    )
    refreshed = writer.build_rolling_edition(
        [
            new_lead,
            _candidate("c6", slot_id="secondary", priority=20),
            _candidate("c7", slot_id="main", priority=30),
        ],
        refreshed_section_ids={"expectations-moved"},
        retain_refreshed_items=True,
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC),
        section_maturity="beta",
    )

    # New featured output consumes all three full editorial surfaces. The old
    # scanner row remains useful and does not count against Section diversity.
    assert set(refreshed["claim_ids"]) == {
        CLAIM_UUIDS[3],
        CLAIM_UUIDS[4],
        CLAIM_UUIDS[5],
        CLAIM_UUIDS[6],
    }
    assert refreshed["item_count"] == 4
    _cleanup(engine)


def test_continuity_reserve_backfills_secondary_and_preserves_age(
    writer, engine
) -> None:
    _cleanup(engine)
    observed_at = "2026-08-10T09:00:00+00:00"
    historical_rules = [
        _candidate(
            "c1",
            section="rules-moved",
            slot_id="secondary",
            component_id="signal-hero.rules",
            headline="Durable rule hero",
            data_as_of=observed_at,
            materially_updated_at=observed_at,
            display_fields={
                "rule_title": "Durable rule hero",
                "previous_state": "proposed",
                "current_state": "final",
                "transition_date": "2026-08-10",
                "authority": "Test authority",
                "source_url": "https://example.com/rule-hero",
                "headline": "Durable rule hero",
                "primary_observation": "The authoritative state changed.",
            },
        ),
        _candidate(
            "c2",
            section="rules-moved",
            slot_id="secondary",
            component_id="state-transition.rule-stage",
            headline="Durable rule transition",
            data_as_of=observed_at,
            materially_updated_at=observed_at,
            display_fields={
                "rule_title": "Durable rule transition",
                "previous_state": "proposed",
                "current_state": "final",
                "transition_date": "2026-08-10",
                "authority": "Test authority",
                "source_url": "https://example.com/rule-transition",
            },
        ),
    ]
    historical = writer.build_edition(
        historical_rules,
        generated_at=datetime(2026, 8, 10, 9, tzinfo=UTC),
        section_maturity="beta",
    )

    fresh_at = "2026-08-10T12:00:00+00:00"
    lead_fields = {
        **_candidate("c3")["display_fields"],
        "updated_at": fresh_at,
        "headline": "Fresh expectation lead",
        "primary_observation": "A newly verified expectation moved.",
    }
    current = writer.build_edition(
        [
            _candidate(
                "c3",
                slot_id="lead",
                component_id="signal-hero.expectations",
                headline="Fresh expectation lead",
                display_fields=lead_fields,
                data_as_of=fresh_at,
                materially_updated_at=fresh_at,
            ),
            _candidate(
                "c4",
                slot_id="secondary",
                headline="Fresh expectation secondary",
                display_fields={
                    **_candidate("c4")["display_fields"],
                    "expectation_title": "Fresh expectation secondary",
                    "updated_at": fresh_at,
                },
                data_as_of=fresh_at,
                materially_updated_at=fresh_at,
            ),
            _candidate(
                "c5",
                slot_id="main",
                headline="Fresh expectation main",
                display_fields={
                    **_candidate("c5")["display_fields"],
                    "expectation_title": "Fresh expectation main",
                    "updated_at": fresh_at,
                },
                data_as_of=fresh_at,
                materially_updated_at=fresh_at,
            ),
        ],
        generated_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        section_maturity="beta",
    )

    refreshed = writer.build_rolling_edition(
        [],
        refreshed_section_ids=set(),
        generated_at=datetime(2026, 8, 10, 13, tzinfo=UTC),
        section_maturity="beta",
    )

    assert refreshed["supersedes_edition_id"] == current["edition_id"]
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT headline, data_as_of, hidden_detail_fields "
                "FROM render_plans "
                "WHERE edition_id = :edition AND slot_id = 'secondary' "
                "ORDER BY position"
            ),
            {"edition": refreshed["edition_id"]},
        ).fetchall()
    assert len(rows) == 3
    carried = [row for row in rows if row[2].get("publication_continuity")]
    assert {row[0] for row in carried} == {
        "Durable rule hero",
        "Durable rule transition",
    }
    assert all(row[1].isoformat() == observed_at for row in carried)
    assert all(
        row[2]["publication_continuity"]["source_edition_id"]
        == historical["edition_id"]
        for row in carried
    )
    payload = writer.edition_json(refreshed["edition_id"])["edition_payload"]
    assert payload["continuity"]["carried_items"] == 2
    assert payload["continuity"]["source_edition_ids"] == [historical["edition_id"]]
    _cleanup(engine)


def test_continuity_reserve_rejects_past_expectation_deadline() -> None:
    candidate = _candidate(
        "c1",
        source_status="active",
        topic_status="active",
        resolution_deadline_at="2026-08-10T11:59:59+00:00",
    )

    assert not _continuity_source_is_live(
        candidate,
        now=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )
    candidate["resolution_deadline_at"] = "2026-08-10T12:00:01+00:00"
    assert _continuity_source_is_live(
        candidate,
        now=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )


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
        [_candidate("c1"), _candidate("c2")],
        edition_date=date(2026, 8, 7),
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
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


def test_freshness_reconcile_backfills_publication_context(writer, engine) -> None:
    _cleanup(engine)
    with patch.object(writer.context_builder, "capture", return_value={}):
        writer.build_edition(
            [_candidate("c1")],
            generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
        )

    refreshed = writer.reconcile_freshness(
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )

    assert refreshed["published"] is True
    assert any(
        transition["reason"] == "publication context version changed"
        for transition in refreshed["transitions"]
    )
    payload = writer.edition_json(refreshed["edition_id"])
    assert payload["edition_payload"]["publication_context"]["version"] == "1.7.0"
    _cleanup(engine)


def test_freshness_reconcile_applies_new_composer_version(
    writer, engine, monkeypatch
) -> None:
    import open_signal.composer.edition_writer as edition_writer_module

    _cleanup(engine)
    monkeypatch.setattr(edition_writer_module, "COMPOSER_VERSION", "os-048")
    writer.build_edition(
        [_candidate("c1")],
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
    )
    monkeypatch.setattr(edition_writer_module, "COMPOSER_VERSION", "os-052")

    refreshed = writer.reconcile_freshness(
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )

    assert refreshed["published"] is True
    assert any(
        transition["reason"] == "edition composer version changed"
        for transition in refreshed["transitions"]
    )
    assert writer.edition_json(refreshed["edition_id"])["composer_version"] == "os-052"
    _cleanup(engine)


def test_freshness_reconcile_publishes_when_research_screening_changes(
    writer, engine
) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM research_signal_candidates"))
    initial = writer.build_edition(
        [_candidate("c1")],
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
    )
    initial_context = writer.edition_json(initial["edition_id"])["edition_payload"][
        "publication_context"
    ]
    assert initial_context["research"] == []

    metrics = {
        "sponsor": "Sponsor A",
        "portfolio_scope": "sponsor",
        "topic_id": "oncology-immunotherapy",
        "topic_label": "Oncology immunotherapy",
        "phases": ["PHASE1", "PHASE2"],
        "phase_labels": ["Phase 1", "Phase 2"],
        "representative_studies": [
            {"id": "NCT00000001", "title": "Phase one study"},
            {"id": "NCT00000002", "title": "Phase two study"},
        ],
        "study_count": 2,
        "evidence_count": 2,
        "window_label": "Registry portfolio as of Aug 2026",
        "baseline_label": "Cross-sectional phase coverage",
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO research_signal_candidates
                  (candidate_type, subject_ids, observation_window_start,
                   observation_window_end, baseline_definition, derived_metrics,
                   evidence_relation_ids, candidate_generator_version, status,
                   idempotency_key, created_at)
                VALUES
                  ('stage_transition', CAST('{}' AS uuid[]), :window_start,
                   :window_end, :baseline, CAST(:metrics AS jsonb),
                   CAST('{}' AS uuid[]), 'os-021.3', 'shadow_investigation', :key,
                   :created_at)
                """
            ),
            {
                "window_start": datetime(2026, 1, 1, tzinfo=UTC),
                "window_end": datetime(2026, 8, 7, 13, 30, tzinfo=UTC),
                "baseline": (
                    "registered topic portfolio phase distribution across sponsors"
                ),
                "metrics": json.dumps(metrics),
                "key": f"research-test:{uuid.uuid4()}",
                "created_at": datetime(2026, 8, 7, 13, 30, tzinfo=UTC),
            },
        )

    refreshed = writer.reconcile_freshness(
        generated_at=datetime(2026, 8, 7, 14, tzinfo=UTC)
    )

    assert refreshed["published"] is True
    assert any(
        transition["reason"] == "public research screening changed"
        for transition in refreshed["transitions"]
    )
    refreshed_context = writer.edition_json(refreshed["edition_id"])[
        "edition_payload"
    ]["publication_context"]
    assert len(refreshed_context["research"]) == 1
    assert (
        refreshed_context["research_fingerprint"]
        != initial_context["research_fingerprint"]
    )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM research_signal_candidates"))
    _cleanup(engine)


def test_historical_front_page_marks_snapshot_non_current(writer, engine) -> None:
    _cleanup(engine)
    historical = writer.build_edition(
        [_candidate("c1")],
        generated_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        section_maturity="beta",
    )
    current = writer.build_edition(
        [_candidate("c2")],
        generated_at=datetime(2026, 8, 7, 13, tzinfo=UTC),
        section_maturity="beta",
    )

    historical_page = FrontPagePresenter(engine).build(
        edition_id=historical["edition_id"]
    )
    current_page = FrontPagePresenter(engine).build()
    assert historical_page is not None
    assert historical_page["snapshot"]["id"] == historical["edition_id"]
    assert historical_page["snapshot"]["is_current"] is False
    assert current_page is not None
    assert current_page["snapshot"]["id"] == current["edition_id"]
    assert current_page["snapshot"]["is_current"] is True
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
