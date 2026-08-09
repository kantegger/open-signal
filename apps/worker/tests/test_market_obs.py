"""Market observation collector tests (OS-008).

Bucket/idempotency tests are DB-free; integration tests require a real
PostgreSQL via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import json
import os
from datetime import UTC, datetime

import httpx
import pytest
from open_signal.sources.market_obs import (
    MarketObservationCollector,
    PriceHistoryClient,
    floor_to_bucket,
    history_rows,
)

# ------------------------------------------------------------ bucket (no DB)


def test_floor_to_bucket() -> None:
    now = datetime(2026, 8, 7, 12, 7, 33, tzinfo=UTC)
    floored = floor_to_bucket(now, 5)
    assert floored.minute == 5
    assert floored.second == 0

    floored_15 = floor_to_bucket(now, 15)
    assert floored_15.minute == 0


def test_parse_probability_helpers() -> None:
    from open_signal.sources.market_obs import parse_probability

    assert parse_probability("0.64") == 0.64
    assert parse_probability(None) is None
    assert parse_probability("abc") is None


def test_history_rows_bucket_and_validate_points() -> None:
    rows = history_rows(
        "11111111-1111-1111-1111-111111111111",
        [
            {"t": 1_786_219_224, "p": 0.505},
            {"t": 1_786_219_240, "p": 0.51},
            {"t": "bad", "p": 0.8},
            {"t": 1_786_222_800, "p": 1.2},
        ],
        bucket_minutes=60,
    )

    assert len(rows) == 1
    assert rows[0]["probability"] == 0.51
    assert rows[0]["observed_at"].endswith("+00:00")


def test_price_history_client_posts_official_batch_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"history": {"yes-token": [{"t": 100, "p": 0.6}]}},
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        base_url="https://clob.polymarket.com",
        transport=transport,
    )
    client = PriceHistoryClient(client=http_client)
    try:
        history = client.fetch_batch(
            ["yes-token"],
            start_ts=10,
            end_ts=20,
            fidelity=60,
        )
    finally:
        client.close()

    assert captured == {
        "markets": ["yes-token"],
        "start_ts": 10,
        "end_ts": 20,
        "fidelity": 60,
    }
    assert history["yes-token"][0]["p"] == 0.6


# ------------------------------------------------------------ integration (DB)


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


def _seed_market(engine, external_id: str, question: str) -> str:
    """Insert a source_market row; returns its uuid."""
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM sources WHERE slug = 'os008-source'")
        ).fetchone()
        if row:
            source_uuid = str(row[0])
        else:
            row = conn.execute(
                text(
                    "INSERT INTO sources (slug, name, category, authority_level, "
                    "access_mode, adapter_id, status) "
                    "VALUES ('os008-source', 'OS008', 'prediction_market', "
                    "'licensed_aggregator', 'rest', 'os008', 'active') RETURNING id"
                )
            ).fetchone()
            source_uuid = str(row[0])

        existing = conn.execute(
            text("SELECT id FROM source_markets WHERE external_market_id = :e"),
            {"e": external_id},
        ).fetchone()
        if existing:
            return str(existing[0])

        row = conn.execute(
            text(
                "INSERT INTO source_markets (source_id, external_market_id, question, "
                "outcome_labels, token_ids, ends_at, status, raw_source_record_id) "
                "VALUES (:s, :e, :q, ARRAY['Yes','No'], ARRAY['1','2'], "
                "'2026-12-31T00:00:00Z', 'active', NULL) RETURNING id"
            ),
            {"s": source_uuid, "e": external_id, "q": question},
        ).fetchone()
        return str(row[0])


def _fixture_markets() -> list[dict]:
    with open("fixtures/polymarket/markets_offset_0.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def collector(engine) -> MarketObservationCollector:
    return MarketObservationCollector(engine)


def test_collect_from_records_idempotent(collector, engine) -> None:
    from sqlalchemy import text

    markets = _fixture_markets()
    # map the first two markets
    _seed_market(engine, str(markets[0]["id"]), markets[0]["question"])
    _seed_market(engine, str(markets[1]["id"]), markets[1]["question"])

    # map gamma id -> uuid for the collector
    mapping = {}
    for m in markets[:2]:
        mapping[str(m["id"])] = _seed_market(engine, str(m["id"]), m["question"])

    # 用真实 market 数据模拟（external_id 参数即 uuid）
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_observations"))

    # collect: 传 uuid 作为 market 的 external 标识
    def _collect() -> int:
        stored = 0
        for m in markets[:2]:
            stored += collector._store_observation(m, external_id=mapping[str(m["id"])])
        return stored

    first = _collect()
    second = _collect()  # same bucket -> idempotent
    assert first == 2
    assert second == 0

    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM market_observations")).scalar_one()
        row = conn.execute(
            text(
                "SELECT probability, midpoint, spread, price_method, "
                "data_quality_flags FROM market_observations "
                "WHERE source_market_id = :m"
            ),
            {"m": mapping[str(markets[0]["id"])]},
        ).fetchone()
    assert count == 2
    assert row[0] is not None  # probability present
    assert row[1] is not None  # midpoint computed
    assert row[2] is not None
    assert row[3] == "source_probability"
    assert isinstance(row[4], list)


def test_collect_flags_missing_data(collector, engine) -> None:
    market_uuid = _seed_market(engine, "os008-bad", "Bad market?")
    bad_market = {"id": "os008-bad", "closed": False}  # no prices at all
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("DELETE FROM market_observations"))
    stored = collector._store_observation(bad_market, external_id=market_uuid)
    assert stored == 1
    with engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(
            text(
                "SELECT probability, data_quality_flags FROM market_observations "
                "WHERE source_market_id = :m"
            ),
            {"m": market_uuid},
        ).fetchone()
    assert row[0] is None
    assert "missing_probability" in row[1]
    assert "missing_order_book" in row[1]


def test_collect_skips_market_without_uuid(collector, engine) -> None:
    # external_id None -> cannot map -> skipped
    stored = collector._store_observation({"id": "x"}, external_id=None)
    assert stored == 0
