"""Source retraction propagation tests (OS-035). Requires real PostgreSQL via
OPEN_SIGNAL_DATABASE_URL (migration 0001 applied).
"""

import json
import os
import uuid
from datetime import date

import pytest

from open_signal.sources.retraction import RetractionHandler


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_chain(engine) -> dict[str, str]:
    """source -> raw record -> market -> canonical -> claim -> edition."""
    from sqlalchemy import text

    with engine.begin() as conn:
        src = conn.execute(
            text(
                "INSERT INTO sources (slug, name, category, authority_level, access_mode, "
                "adapter_id, status) "
                "VALUES ('os035-src', 'OS035', 'other', 'secondary_source', 'rest', 'v1', 'active') "
                "RETURNING id"
            )
        ).fetchone()
        src_id = str(src[0])
        raw = conn.execute(
            text(
                "INSERT INTO raw_source_records (source_id, external_id, record_type, "
                "mime_type, payload, content_hash, adapter_version, status) "
                "VALUES (:s, 'os035-ext', 'market', 'application/json', '{}'::jsonb, :h, 'v1', 'active') "
                "RETURNING id"
            ),
            {"s": src_id, "h": uuid.uuid4().hex},
        ).fetchone()
        market = conn.execute(
            text(
                "INSERT INTO source_markets (source_id, external_market_id, question, "
                "outcome_labels, token_ids, ends_at, status) "
                "VALUES (:s, 'os035-market', 'Q?', ARRAY['Yes','No'], ARRAY['1','2'], "
                "'2027-12-31', 'active') RETURNING id"
            ),
            {"s": src_id},
        ).fetchone()
        market_id = str(market[0])
        canonical = conn.execute(
            text(
                "INSERT INTO canonical_expectations (canonical_question, event_type, "
                "outcome_type, resolution_deadline_at, resolution_rule_summary, "
                "resolution_rule_hash, source_market_ids, status, canonicalization_version) "
                "VALUES ('Q?', 'general', 'binary', '2027-12-31', 'r', 'h', "
                "ARRAY[:m]::uuid[], 'active', '0.1.0') RETURNING id"
            ),
            {"m": market_id},
        ).fetchone()
        canonical_id = str(canonical[0])
        return {"source": src_id, "raw": str(raw[0]), "market": market_id, "canonical": canonical_id}


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE daily_editions CASCADE"))
        conn.execute(text("TRUNCATE claims CASCADE"))
        conn.execute(text("DELETE FROM evidence_bundles"))
        conn.execute(text("DELETE FROM market_observations"))
        conn.execute(text("DELETE FROM canonical_expectations"))
        conn.execute(text("DELETE FROM source_markets"))
        conn.execute(text("DELETE FROM raw_artifacts"))
        conn.execute(text("DELETE FROM raw_source_records"))
        conn.execute(text("DELETE FROM source_cursors"))
        conn.execute(text("DELETE FROM sources"))
        conn.execute(text("DELETE FROM agent_tool_calls"))
        conn.execute(text("DELETE FROM investigation_runs"))


def test_full_retraction_flow(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    ids = _seed_chain(engine)
    handler = RetractionHandler(engine)

    result = handler.run_retraction(ids["source"], "source data invalidated", actor="ops-test")

    assert result["updated"] is True
    assert result["canonical_retired"] == [ids["canonical"]]

    with engine.connect() as conn:
        src_status = conn.execute(
            text("SELECT status FROM sources WHERE id = :id"), {"id": ids["source"]}
        ).scalar_one()
        raw_status = conn.execute(
            text("SELECT status FROM raw_source_records WHERE id = :id"), {"id": ids["raw"]}
        ).scalar_one()
        canonical_status = conn.execute(
            text("SELECT status FROM canonical_expectations WHERE id = :id"),
            {"id": ids["canonical"]},
        ).scalar_one()
    assert src_status == "retracted"
    assert raw_status == "retracted"
    assert canonical_status == "retired"
    assert result["archive_record_id"] is not None
    _cleanup(engine)


def test_retraction_idempotent(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    ids = _seed_chain(engine)
    handler = RetractionHandler(engine)
    first = handler.run_retraction(ids["source"], "reason")
    second = handler.run_retraction(ids["source"], "reason")
    assert first["updated"] is True
    assert second["updated"] is False  # already retracted
    _cleanup(engine)


def test_edition_correction(engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    ids = _seed_chain(engine)
    # build an edition referencing the chain
    from open_signal.composer.edition_writer import EditionWriter

    writer = EditionWriter(engine)
    candidate = {
        "claim_id": str(uuid.uuid4()),
        "claim_status": "verified",
        "claim_type": "derived_observation",
        "component_id": "time-series.probability-move",
        "section_id": "expectations-moved",
        "slot_id": "secondary",
        "display_fields": {
            "expectation_title": "Q", "current_probability": 0.5, "start_probability": 0.4,
            "delta_percentage_points": 10.0, "window": "24h", "series": [],
            "source_name": "Polymarket", "updated_at": "t",
        },
    }
    writer.build_edition([candidate], edition_date=date(2026, 8, 7))

    handler = RetractionHandler(engine)
    result = handler.run_retraction(ids["source"], "retracted")
    assert len(result["editions_corrected"]) >= 1
    _cleanup(engine)
