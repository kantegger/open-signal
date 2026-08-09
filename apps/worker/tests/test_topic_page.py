"""Public Topic hub and SEO index integration tests."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.api.topics import SeoIndexPresenter, TopicPagePresenter
from open_signal.orchestration.metadata import ensure_runtime_metadata
from sqlalchemy import create_engine, text


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture()
def topic_context(engine):
    source_id = ensure_runtime_metadata(engine)["polymarket-gamma"]
    market_id = str(uuid.uuid4())
    topic_id = str(uuid.uuid4())
    external_id = f"topic-test-{uuid.uuid4()}"
    now = datetime.now(UTC)
    payload = {
        "id": external_id,
        "slug": "fed-cut-topic-test",
        "eventId": "event-topic-test",
        "eventTitle": "Federal Reserve policy test",
        "eventSlug": "federal-reserve-policy-test",
        "tags": [{"label": "Federal Reserve"}],
    }
    with engine.begin() as conn:
        raw_id = conn.execute(
            text(
                """
                INSERT INTO raw_source_records
                  (source_id, external_id, record_type, mime_type, payload,
                   content_hash, adapter_version, status)
                VALUES
                  (:source, :external, 'market', 'application/json',
                   CAST(:payload AS jsonb), :hash, 'topic-test', 'active')
                RETURNING id
                """
            ),
            {
                "source": source_id,
                "external": external_id,
                "payload": json.dumps(payload),
                "hash": uuid.uuid4().hex,
            },
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO source_markets
                  (id, source_id, external_market_id, external_event_id,
                   question, outcome_labels, token_ids, ends_at, rules_text,
                   liquidity, volume, status, raw_source_record_id)
                VALUES
                  (:id, :source, :external, 'event-topic-test', :question,
                   ARRAY['Yes', 'No'], ARRAY['yes-token'], :ends, :rules,
                   250000, 1800000, 'active', :raw)
                """
            ),
            {
                "id": market_id,
                "source": source_id,
                "external": external_id,
                "question": "Will the Federal Reserve cut rates in the test window?",
                "ends": now + timedelta(days=45),
                "rules": "Resolves Yes after an official target-range reduction.",
                "raw": raw_id,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO canonical_expectations
                  (id, canonical_question, event_type, outcome_type,
                   resolution_deadline_at, resolution_authority,
                   resolution_rule_summary, resolution_rule_hash,
                   source_market_ids, status, canonicalization_version,
                   updated_at)
                VALUES
                  (:id, :question, 'monetary_policy', 'binary', :ends,
                   'Federal Reserve', :rules, :hash,
                   ARRAY[:market]::uuid[], 'active', 'topic-test', now())
                """
            ),
            {
                "id": topic_id,
                "question": "Will the Federal Reserve cut rates in the test window?",
                "ends": now + timedelta(days=45),
                "rules": "Resolves Yes after an official target-range reduction.",
                "hash": uuid.uuid4().hex,
                "market": market_id,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO market_observations
                  (source_market_id, observed_at, probability, price_method,
                   data_quality_flags)
                VALUES
                  (:market, :baseline, 0.60, 'topic-test', ARRAY[]::text[]),
                  (:market, :current, 0.72, 'topic-test', ARRAY[]::text[])
                """
            ),
            {
                "market": market_id,
                "baseline": now - timedelta(hours=23),
                "current": now,
            },
        )

    yield {"topic_id": topic_id, "market_id": market_id, "external_id": external_id}

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM canonical_expectations WHERE id = :id"), {"id": topic_id})
        conn.execute(text("DELETE FROM market_observations WHERE source_market_id = :id"), {"id": market_id})
        conn.execute(text("DELETE FROM source_markets WHERE id = :id"), {"id": market_id})
        conn.execute(
            text("DELETE FROM raw_source_records WHERE external_id = :external"),
            {"external": external_id},
        )


def test_topic_page_exposes_market_state_and_source_context(engine, topic_context) -> None:
    page = TopicPagePresenter(engine).build(topic_context["topic_id"])
    assert page is not None
    assert page["topic"]["status"] == "active"
    assert page["source_event"]["title"] == "Federal Reserve policy test"
    assert page["markets"][0]["current_probability"] == pytest.approx(0.72)
    assert page["markets"][0]["delta_24h_percentage_points"] == pytest.approx(12.0)
    assert page["markets"][0]["source_url"].endswith("/event/federal-reserve-policy-test")


def test_seo_index_includes_active_topic_before_a_claim_exists(engine, topic_context) -> None:
    index = SeoIndexPresenter(engine).build(limit=10)
    topic = next(
        topic for topic in index["topics"] if topic["id"] == topic_context["topic_id"]
    )
    assert topic["event_type"] == "monetary_policy"
    assert topic["status"] == "active"
    assert topic["source_market_count"] == 1
    assert topic["resolution_deadline_at"]
    assert topic["current_probability"] == pytest.approx(0.72)
    assert topic["delta_24h_percentage_points"] == pytest.approx(12.0)
    assert topic["current_observed_at"]
