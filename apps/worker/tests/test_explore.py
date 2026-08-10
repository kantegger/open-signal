"""Event-aware Explore projection integration tests."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from open_signal.api.explore import ExplorePresenter, _select_current_signals
from open_signal.api.topics import SeoIndexPresenter
from open_signal.derived.expectation_selection import (
    ExpectationFact,
    select_expectation_groups,
)
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
def multi_outcome_event(engine):
    now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    source_id = str(uuid.uuid4())
    source_slug = f"event-selection-test-{uuid.uuid4()}"
    event_id = f"f1-{uuid.uuid4()}"
    option_rows = [
        ("Kimi Antonelli", 0.65, 0.63, 9000),
        ("Lewis Hamilton", 0.20, 0.05, 18_000),
        ("Max Verstappen", 0.10, 0.09, 12_000),
        ("Driver Four", 0.01, 0.01, 0),
        ("Driver Five", 0.01, 0.01, 0),
        ("Driver Six", 0.01, 0.01, 0),
        ("Driver Seven", 0.01, 0.01, 0),
        ("Driver Eight", 0.01, 0.01, 0),
    ]
    market_ids: list[str] = []
    topic_ids: list[str] = []
    raw_ids: list[str] = []
    summaries = [
        {
            "id": str(index),
            "groupItemTitle": option,
            "active": True,
            "closed": False,
        }
        for index, (option, *_rest) in enumerate(option_rows)
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sources
                  (id, slug, name, category, authority_level, access_mode,
                   adapter_id, status)
                VALUES
                  (:id, :slug, 'Explore event test', 'prediction_market',
                   'licensed_aggregator', 'rest', 'explore-test', 'active')
                """
            ),
            {"id": source_id, "slug": source_slug},
        )
        conn.execute(
            text(
                """
                INSERT INTO raw_source_records
                  (source_id, external_id, record_type, mime_type, payload,
                   content_hash, adapter_version, status, last_seen_at)
                VALUES
                  (:source, :external, 'event', 'application/json',
                   CAST(:payload AS jsonb), :hash, 'explore-test', 'active', :seen)
                """
            ),
            {
                "source": source_id,
                "external": f"event:{event_id}",
                "payload": json.dumps(
                    {
                        "id": event_id,
                        "title": "2026 F1 Drivers' Champion",
                        "slug": "2026-f1-drivers-champion-test",
                        "negRisk": True,
                        "marketSummaries": summaries,
                    }
                ),
                "hash": uuid.uuid4().hex,
                "seen": now,
            },
        )
        for index, (option, current, baseline, volume_24h) in enumerate(option_rows):
            market_id = str(uuid.uuid4())
            topic_id = str(uuid.uuid4())
            external_market_id = f"{event_id}-{index}"
            raw_payload = {
                "id": external_market_id,
                "eventId": event_id,
                "eventTitle": "2026 F1 Drivers' Champion",
                "eventSlug": "2026-f1-drivers-champion-test",
                "groupItemTitle": option,
                "negRisk": True,
                "negRiskMarketID": event_id,
            }
            raw_id = str(
                conn.execute(
                    text(
                        """
                        INSERT INTO raw_source_records
                          (source_id, external_id, external_parent_id,
                           record_type, mime_type, payload, content_hash,
                           adapter_version, status, last_seen_at)
                        VALUES
                          (:source, :external, :parent, 'market',
                           'application/json', CAST(:payload AS jsonb), :hash,
                           'explore-test', 'active', :seen)
                        RETURNING id
                        """
                    ),
                    {
                        "source": source_id,
                        "external": external_market_id,
                        "parent": f"event:{event_id}",
                        "payload": json.dumps(raw_payload),
                        "hash": uuid.uuid4().hex,
                        "seen": now,
                    },
                ).scalar_one()
            )
            conn.execute(
                text(
                    """
                    INSERT INTO source_markets
                      (id, source_id, external_market_id, external_event_id,
                       question, outcome_labels, token_ids, ends_at, rules_text,
                       liquidity, volume_24h, volume,
                       monitoring_last_seen_at, status, raw_source_record_id,
                       updated_at)
                    VALUES
                      (:id, :source, :external, :event, :question,
                       ARRAY['Yes', 'No'], ARRAY[]::text[], :ends, :rules,
                       50000, :volume_24h, :volume, :seen, 'active', :raw, :seen)
                    """
                ),
                {
                    "id": market_id,
                    "source": source_id,
                    "external": external_market_id,
                    "event": event_id,
                    "question": f"Will {option} be the 2026 F1 Drivers' Champion?",
                    "ends": now + timedelta(days=120),
                    "rules": "Resolves from the official FIA championship result.",
                    "volume_24h": volume_24h,
                    "volume": 13_000_000 - index,
                    "seen": now,
                    "raw": raw_id,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO canonical_expectations
                      (id, canonical_question, event_type, outcome_type,
                       resolution_deadline_at, resolution_rule_summary,
                       resolution_rule_hash, source_market_ids, status,
                       canonicalization_version, updated_at)
                    VALUES
                      (:id, :question, 'sports', 'binary', :ends, :rules,
                       :hash, ARRAY[:market]::uuid[], 'active',
                       'explore-test', :seen)
                    """
                ),
                {
                    "id": topic_id,
                    "question": f"Will {option} be the 2026 F1 Drivers' Champion?",
                    "ends": now + timedelta(days=120),
                    "rules": "Resolves from the official FIA championship result.",
                    "hash": uuid.uuid4().hex,
                    "market": market_id,
                    "seen": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO market_observations
                      (source_market_id, observed_at, probability, price_method,
                       data_quality_flags)
                    VALUES
                      (:market, :baseline_at, :baseline, 'explore-test',
                       ARRAY[]::text[]),
                      (:market, :current_at, :current, 'explore-test',
                       ARRAY[]::text[])
                    """
                ),
                {
                    "market": market_id,
                    "baseline_at": now - timedelta(hours=25),
                    "baseline": baseline,
                    "current_at": now,
                    "current": current,
                },
            )
            market_ids.append(market_id)
            topic_ids.append(topic_id)
            raw_ids.append(raw_id)

    yield {
        "as_of": now + timedelta(minutes=1),
        "event_id": event_id,
        "market_ids": market_ids,
        "topic_ids": topic_ids,
        "source_id": source_id,
    }

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM canonical_expectations WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": topic_ids},
        )
        conn.execute(
            text(
                "DELETE FROM market_observations "
                "WHERE source_market_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": market_ids},
        )
        conn.execute(
            text("DELETE FROM source_markets WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": market_ids},
        )
        conn.execute(
            text("DELETE FROM raw_source_records WHERE source_id = :source"),
            {"source": source_id},
        )
        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})


def test_explore_groups_multi_outcome_event_but_seo_keeps_topics(
    engine,
    multi_outcome_event,
) -> None:
    result = ExplorePresenter(engine).build(
        as_of=multi_outcome_event["as_of"],
        topic_page_size=60,
    )
    group = next(
        item
        for item in result["topics"]["items"]
        if item["external_event_id"] == multi_outcome_event["event_id"]
    )
    seo = SeoIndexPresenter(engine).build(limit=5000)
    seo_topic_ids = {item["id"] for item in seo["topics"]}

    assert group["title"] == "2026 F1 Drivers' Champion"
    assert group["source_member_count"] == 8
    assert len(group["members"]) == 3
    assert group["suppressed_member_count"] == 5
    assert set(multi_outcome_event["topic_ids"]) <= seo_topic_ids


def test_recent_signals_keep_latest_subject_then_one_event_representative() -> None:
    as_of = datetime(2026, 8, 10, 8, tzinfo=UTC)
    facts = [
        _fact("market-one", 0.65, as_of),
        _fact("market-two", 0.25, as_of),
    ]
    groups = select_expectation_groups(facts, as_of=as_of, page_size=12)
    rows = [
        _claim("new-one", "market-one", as_of, 4.0),
        _claim("new-two", "market-two", as_of - timedelta(minutes=1), 8.0),
        _claim("old-one", "market-one", as_of - timedelta(hours=2), 12.0),
    ]

    selected, current_subject_count = _select_current_signals(
        rows,
        facts=facts,
        groups=groups,
    )

    assert current_subject_count == 2
    assert len(selected) == 1
    assert selected[0]["id"] == "new-one"


def _fact(market_id: str, probability: float, as_of: datetime) -> ExpectationFact:
    return ExpectationFact(
        topic_id=f"topic-{market_id}",
        market_id=market_id,
        source_id="source",
        source_slug="polymarket-gamma",
        title=f"Will {market_id} win?",
        event_type="sports",
        deadline_at=as_of + timedelta(days=30),
        canonical_status="active",
        market_status="active",
        external_event_id="same-event",
        event_title="Same event",
        event_slug="same-event",
        group_item_title=market_id,
        neg_risk_market_id="same-event",
        is_exclusive_slate=True,
        source_member_count=2,
        current_probability=probability,
        current_observed_at=as_of - timedelta(minutes=1),
        baseline_probability_24h=probability - 0.05,
        baseline_observed_at=as_of - timedelta(hours=25),
        spread=0.01,
        data_quality_flags=(),
        volume_24h=10_000,
        lifetime_volume=100_000,
        liquidity=50_000,
        monitoring_last_seen_at=as_of,
        source_monitoring_at=as_of,
        recent_claim_id=f"claim-{market_id}",
        recent_claim_at=as_of,
        raw_payload={},
    )


def _claim(
    claim_id: str,
    market_id: str,
    updated_at: datetime,
    move: float,
) -> dict:
    return {
        "id": claim_id,
        "section_id": "expectations-moved",
        "subject_type": "source_market",
        "subject_id": market_id,
        "structured_proposition": {"value": move},
        "updated_at": updated_at,
        "issued_at": updated_at,
    }
