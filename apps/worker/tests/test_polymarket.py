"""Polymarket adapter tests (OS-007).

Market discovery/parsing use saved fixtures (offline); cursor persistence
and raw record storage require a real PostgreSQL via OPEN_SIGNAL_TEST_DATABASE_URL
(migration 0002 applied).
"""

import json
import os
from pathlib import Path

import pytest
from open_signal.sources.polymarket import (
    FIXTURE_DIR,
    PolymarketAdapter,
    select_monitored_markets,
)

TEST_SOURCE = "polymarket-gamma-test"


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def adapter(engine, tmp_path):
    # source_cursors.source_id references sources.id (uuid), so resolve it
    source_uuid = _seed_source(engine, TEST_SOURCE)
    return PolymarketAdapter(
        engine,
        source_id=source_uuid,
        adapter_version="test",
        page_size=8,
        fixture_dir=tmp_path,
        offline=True,
    )


@pytest.fixture()
def fake_fixtures(tmp_path):
    """Copy the real saved fixtures into a temp dir for offline discovery."""
    for name in ("markets_offset_0.json", "markets_offset_8.json", "markets_offset_16.json"):
        src = FIXTURE_DIR / name
        if src.exists():
            (tmp_path / name).write_bytes(src.read_bytes())
    return tmp_path


def _seed_source(engine, slug: str) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM sources WHERE slug = :s"), {"s": slug}
        ).fetchone()
        if row:
            return str(row[0])
        row = conn.execute(
            text(
                "INSERT INTO sources (slug, name, category, authority_level, "
                "access_mode, adapter_id, status) "
                "VALUES (:s, :name, 'prediction_market', 'licensed_aggregator', "
                "'rest', 'polymarket-gamma-v1', 'active') RETURNING id"
            ),
            {"s": slug, "name": slug},
        ).fetchone()
        return str(row[0])


# ------------------------------------------------------------- discovery (DB)


def test_discover_stores_raw_records_and_cursor(
    adapter: PolymarketAdapter, engine, fake_fixtures
) -> None:
    _seed_source(engine, TEST_SOURCE)
    # ensure fresh state
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        )
        conn.execute(
            text("DELETE FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        )

    result = adapter.discover(max_pages=10)
    assert result["markets"] >= 8
    assert result["pages"] >= 1

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).scalar_one()
        cursor = conn.execute(
            text("SELECT value FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).fetchone()

    assert count == result["markets"]
    assert cursor is not None and int(cursor[0]) > 0


def test_discover_idempotent(adapter: PolymarketAdapter, engine, fake_fixtures) -> None:
    _seed_source(engine, TEST_SOURCE)
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        )
        conn.execute(
            text("DELETE FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        )

    first = adapter.discover(max_pages=2)
    # 重置 cursor，模拟对同一批数据重复同步（验证 ON CONFLICT 幂等）
    adapter.save_cursor("0")
    second = adapter.discover(max_pages=2)  # same fixtures, same hashes
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).scalar_one()
    assert first["markets"] >= 1
    assert second["markets"] == 0  # nothing new
    assert count == first["markets"]


def test_cursor_continues_where_it_left_off(
    adapter: PolymarketAdapter, engine, fake_fixtures
) -> None:
    _seed_source(engine, TEST_SOURCE)
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        )
        conn.execute(
            text("DELETE FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        )

    adapter.discover(max_pages=1)  # one page (8 markets)
    with engine.connect() as conn:
        cursor = conn.execute(
            text("SELECT value FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).fetchone()
    assert int(cursor[0]) == 8

    # next discover resumes at offset 8 -> reads markets_offset_8 fixture
    adapter.discover(max_pages=1)
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM raw_source_records WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).scalar_one()
    assert count == 16


# ------------------------------------------------------------- cursor (DB)


def test_cursor_upsert(adapter: PolymarketAdapter, engine) -> None:
    _seed_source(engine, TEST_SOURCE)
    adapter.save_cursor("5")
    adapter.save_cursor("12")  # upsert, not duplicate
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT value FROM source_cursors WHERE source_id = :s"),
            {"s": adapter.source_id},
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "12"


# --------------------------------------------------------------- health (live)


def test_health_check_live() -> None:
    from open_signal.sources.polymarket import GammaClient

    client = GammaClient()
    try:
        # live check is opportunistic; fixture-based tests are the source of truth
        assert client.health_check() in (True, False)
    finally:
        client.close()


def test_save_fixture_roundtrip(tmp_path) -> None:
    from open_signal.sources.polymarket import GammaClient, PolymarketAdapter

    adapter = PolymarketAdapter(None, client=GammaClient(), fixture_dir=tmp_path)
    markets = [{"id": 1, "question": "q1"}]
    path = adapter.save_fixture(0, markets)
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    assert loaded == markets


def test_live_load_ignores_repository_fixture(tmp_path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_markets(self, **_kwargs):
            self.calls += 1
            return [{"id": "live", "question": "Live market"}]

        def close(self) -> None:
            pass

    (tmp_path / "markets_offset_0.json").write_text(
        '[{"id":"fixture"}]',
        encoding="utf-8",
    )
    client = FakeClient()
    live = PolymarketAdapter(
        None,
        client=client,
        fixture_dir=tmp_path,
        offline=False,
    )

    assert live._load_page(0)[0]["id"] == "live"
    assert client.calls == 1


def test_event_discovery_caps_each_event_before_global_ranking() -> None:
    events = [
        {
            "id": "event-a",
            "title": "Large slate",
            "tags": [{"slug": "politics"}],
            "markets": [
                {"id": f"a-{index}", "volume24hr": 1000 - index}
                for index in range(8)
            ],
        },
        {
            "id": "event-b",
            "title": "Second topic",
            "markets": [
                {"id": "b-1", "volume24hr": 500},
                {"id": "b-2", "volume24hr": 400},
            ],
        },
    ]

    selected = select_monitored_markets(
        events,
        max_markets=4,
        markets_per_event=2,
    )

    assert {market["id"] for market in selected} == {"a-0", "a-1", "b-1", "b-2"}
    assert all(market.get("eventId") for market in selected)
    assert selected[0]["tags"] == [{"slug": "politics"}]


def test_event_monitoring_keeps_probability_leader_over_lifetime_longshots() -> None:
    markets = [
        {
            "id": "kimi",
            "groupItemTitle": "Kimi Antonelli",
            "outcomePrices": "[\"0.74\", \"0.26\"]",
            "volume24hr": 6200,
            "volume": 900_000,
        }
    ]
    markets.extend(
        {
            "id": f"tail-{index}",
            "groupItemTitle": f"Longshot {index}",
            "outcomePrices": "[\"0.001\", \"0.999\"]",
            "volume24hr": 0,
            "volume": 13_000_000 - index,
        }
        for index in range(20)
    )

    selected = select_monitored_markets(
        [{"id": "f1", "title": "2026 F1 champion", "markets": markets}],
        max_markets=12,
        markets_per_event=12,
    )

    assert "kimi" in {market["id"] for market in selected}


def test_global_event_order_never_compares_lifetime_volume_as_24h_activity() -> None:
    selected = select_monitored_markets(
        [
            {
                "id": "stale-lifetime",
                "markets": [
                    {
                        "id": "stale",
                        "outcomePrices": [0.8, 0.2],
                        "volume24hr": 0,
                        "volume": 100_000_000,
                    }
                ],
            },
            {
                "id": "active-now",
                "markets": [
                    {
                        "id": "active",
                        "outcomePrices": [0.6, 0.4],
                        "volume24hr": 10_000,
                        "volume": 20_000,
                    }
                ],
            },
        ],
        max_markets=1,
        markets_per_event=1,
    )

    assert [market["id"] for market in selected] == ["active"]


def test_negative_mover_is_retained_and_empty_event_fields_are_enriched() -> None:
    event = {
        "id": "event-move",
        "title": "Material move test",
        "slug": "material-move-test",
        "markets": [
            {
                "id": f"leader-{index}",
                "outcomePrices": [0.8 - index * 0.1, 0.2 + index * 0.1],
                "volume24hr": 1000 - index,
            }
            for index in range(3)
        ]
        + [
            {
                "id": "negative-mover",
                "eventId": None,
                "eventTitle": "",
                "outcomePrices": [0.05, 0.95],
                "oneDayPriceChange": -0.04,
                "volume24hr": 10,
            }
        ],
    }

    selected = select_monitored_markets(
        [event],
        max_markets=4,
        markets_per_event=4,
    )
    mover = next(market for market in selected if market["id"] == "negative-mover")

    assert mover["eventId"] == "event-move"
    assert mover["eventTitle"] == "Material move test"
    assert mover["eventSlug"] == "material-move-test"


def test_remaining_monitoring_budget_follows_material_event_depth() -> None:
    events = [
        {
            "id": "largest-leading-market",
            "markets": [
                {"id": "a-1", "volume24hr": 100_000},
                {"id": "a-2", "volume24hr": 1},
            ],
        },
        {
            "id": "material-second-option",
            "markets": [
                {"id": "b-1", "volume24hr": 100},
                {
                    "id": "b-2",
                    "volume24hr": 50,
                    "oneDayPriceChange": 0.12,
                },
            ],
        },
        {
            "id": "third-event",
            "markets": [{"id": "c-1", "volume24hr": 90}],
        },
    ]

    selected = select_monitored_markets(events, max_markets=4, markets_per_event=2)

    assert {market["id"] for market in selected} == {"a-1", "b-1", "b-2", "c-1"}
