"""Polymarket Gamma API read-only adapter (spec §88.1, OS-007).

Covers market discovery, pagination, cursor persistence (source_cursors),
raw record storage (raw_source_records) and health check. Read-only by
design: no trading, no private keys, no user orders.

The Gamma API is public read-only; fixtures are supported for offline
tests under ``fixtures/polymarket/``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from open_signal.db.models import source_cursors

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MONITORED_MARKETS = 500
DEFAULT_MARKETS_PER_EVENT = 12

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "polymarket"


class GammaClient:
    """Thin read-only client for the Gamma API."""

    def __init__(self, base_url: str = GAMMA_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def fetch_markets(
        self, *, offset: int = 0, limit: int = DEFAULT_PAGE_SIZE, closed: bool = False
    ) -> list[dict[str, Any]]:
        resp = self._client.get(
            "/markets",
            params={
                "offset": offset,
                "limit": limit,
                "active": "true",
                "closed": str(closed).lower(),
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_events(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Return active events with their nested markets.

        Polymarket recommends event-based discovery when callers need the
        complete active market set.  Keeping the event envelope also gives us
        stable topic metadata instead of treating every outcome as unrelated.
        """
        resp = self._client.get(
            "/events",
            params={
                "offset": offset,
                "limit": limit,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, list) else []

    def health_check(self) -> bool:
        try:
            resp = self._client.get("/markets", params={"limit": 1})
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


class PolymarketAdapter:
    """Gamma adapter with cursor persistence and raw record storage.

    ``fixture_dir`` enables offline mode: market pages are read from saved
    fixtures instead of the live API (test use).
    """

    def __init__(
        self,
        engine: Any,
        *,
        client: GammaClient | None = None,
        source_id: str = "polymarket-gamma",
        adapter_version: str = "0.1.0",
        page_size: int = DEFAULT_PAGE_SIZE,
        fixture_dir: Path | None = None,
        offline: bool = False,
    ) -> None:
        self.engine = engine
        self.client = client or GammaClient()
        self.source_id = source_id
        self.adapter_version = adapter_version
        self.page_size = page_size
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
        self.offline = offline

    # ------------------------------------------------------------------ cursors
    def get_cursor(self) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                source_cursors.select()
                .where(source_cursors.c.source_id == self.source_id)
            ).fetchone()
        return row._mapping["value"] if row else None

    def save_cursor(self, value: str, last_seen_source_timestamp: datetime | None = None) -> None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO source_cursors
                      (source_id, cursor_type, value, last_successful_fetch_at,
                       last_seen_source_timestamp, adapter_version, updated_at)
                    VALUES (:sid, 'offset', :value, now(), :seen, :ver, now())
                    ON CONFLICT (source_id) DO UPDATE SET
                      value = EXCLUDED.value,
                      last_successful_fetch_at = now(),
                      last_seen_source_timestamp = EXCLUDED.last_seen_source_timestamp,
                      adapter_version = EXCLUDED.adapter_version,
                      updated_at = now()
                    """
                ),
                {"sid": self.source_id, "value": value, "seen": last_seen_source_timestamp, "ver": self.adapter_version},
            )

    # ----------------------------------------------------------------- discovery
    def discover(self, *, max_pages: int = 200) -> dict[str, int]:
        """Page through markets, storing raw records; commit cursor per page.

        Returns counts {"markets": n, "pages": m}.
        """
        if self.get_cursor() is None:
            offset = 0
        else:
            offset = int(self.get_cursor() or "0")

        markets_total = 0
        pages = 0
        for _ in range(max_pages):
            page = self._load_page(offset)
            if not page:
                break
            stored = self._store_raw_markets(page)
            markets_total += stored
            pages += 1
            next_offset = offset + len(page)
            self.save_cursor(str(next_offset))
            if len(page) < self.page_size:
                break  # last page
            offset = next_offset
        return {"markets": markets_total, "pages": pages}

    def refresh(
        self,
        *,
        max_pages: int = 3,
        max_markets: int = DEFAULT_MONITORED_MARKETS,
        markets_per_event: int = DEFAULT_MARKETS_PER_EVENT,
    ) -> dict[str, int]:
        """Re-read the leading active-market pages without advancing a cursor.

        ``discover`` is useful for a finite historical crawl.  A rolling source
        cannot keep resuming beyond the end of that crawl: it must revisit the
        leading active records so changed prices produce a new content hash and
        a new observation.  Live discovery starts from event envelopes, then
        selects a bounded, activity-ranked and event-diverse monitoring set.
        Storage remains idempotent.
        """
        if not self.offline:
            return self._refresh_live_events(
                max_pages=max_pages,
                max_markets=max_markets,
                markets_per_event=markets_per_event,
            )

        offset = 0
        markets_total = 0
        pages = 0
        for _ in range(max_pages):
            page = self._load_page(offset)
            if not page:
                break
            markets_total += self._store_raw_markets(page)
            pages += 1
            if len(page) < self.page_size:
                break
            offset += len(page)
        return {"events": 0, "markets": markets_total, "pages": pages}

    def _refresh_live_events(
        self,
        *,
        max_pages: int,
        max_markets: int,
        markets_per_event: int,
    ) -> dict[str, int]:
        offset = 0
        pages = 0
        events: list[dict[str, Any]] = []
        for _ in range(max(1, max_pages)):
            page = self.client.fetch_events(offset=offset, limit=self.page_size)
            if not page:
                break
            events.extend(page)
            pages += 1
            if len(page) < self.page_size:
                break
            offset += len(page)

        markets = select_monitored_markets(
            events,
            max_markets=max(1, max_markets),
            markets_per_event=max(1, markets_per_event),
        )
        return {
            "events": self._store_raw_events(events),
            "markets": self._store_raw_markets(markets),
            "pages": pages,
        }

    # ------------------------------------------------------------------ storage
    def _load_page(self, offset: int) -> list[dict[str, Any]]:
        """Load one page from fixtures (offline mode) or the live API."""
        fixture = self.fixture_dir / f"markets_offset_{offset}.json"
        if self.offline:
            if fixture.exists():
                with fixture.open(encoding="utf-8") as f:
                    return json.load(f)
            return []  # end of fixture data
        return self.client.fetch_markets(offset=offset, limit=self.page_size)

    def _store_raw_events(self, events: list[dict[str, Any]]) -> int:
        """Store event envelopes so topic pages retain source context."""
        compact_events = []
        for event in events:
            compact = {key: value for key, value in event.items() if key != "markets"}
            nested = event.get("markets")
            compact["marketIds"] = [
                str(market.get("id"))
                for market in nested
                if isinstance(market, dict) and market.get("id") is not None
            ] if isinstance(nested, list) else []
            compact["marketSummaries"] = [
                {
                    key: market.get(key)
                    for key in (
                        "id",
                        "groupItemTitle",
                        "question",
                        "active",
                        "closed",
                        "archived",
                        "acceptingOrders",
                        "outcomePrices",
                        "volume24hr",
                        "volume",
                        "liquidity",
                        "spread",
                        "oneDayPriceChange",
                        "endDate",
                        "updatedAt",
                        "negRisk",
                        "negRiskOther",
                        "negRiskMarketID",
                    )
                    if key in market
                }
                for market in nested
                if isinstance(market, dict) and market.get("id") is not None
            ] if isinstance(nested, list) else []
            compact_events.append(compact)
        return self._store_raw_records(
            compact_events,
            record_type="event",
            external_id=lambda event: f"event:{event.get('id')}",
            source_created_at=lambda event: _source_timestamp(event.get("createdAt")),
            source_updated_at=lambda event: _source_timestamp(event.get("updatedAt")),
        )

    def _store_raw_markets(self, markets: list[dict[str, Any]]) -> int:
        """Insert raw records idempotently (unique source_id/external_id/hash)."""
        normalized = [_with_event_identity(market) for market in markets]
        return self._store_raw_records(
            normalized,
            record_type="market",
            external_id=lambda market: str(market.get("id")),
            external_parent_id=lambda market: (
                f"event:{market.get('eventId')}" if market.get("eventId") else None
            ),
            source_created_at=lambda market: _source_timestamp(market.get("createdAt")),
            source_updated_at=lambda market: _source_timestamp(market.get("updatedAt")),
        )

    def _store_raw_records(
        self,
        records: list[dict[str, Any]],
        *,
        record_type: str,
        external_id: Callable[[dict[str, Any]], str],
        external_parent_id: Callable[[dict[str, Any]], str | None] | None = None,
        source_created_at: Callable[[dict[str, Any]], datetime | None] | None = None,
        source_updated_at: Callable[[dict[str, Any]], datetime | None] | None = None,
    ) -> int:
        from sqlalchemy import text

        stored = 0
        with self.engine.begin() as conn:
            for record in records:
                payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
                content_hash = hashlib.sha256(payload.encode()).hexdigest()
                result = conn.execute(
                    text(
                        """
                        INSERT INTO raw_source_records
                          (source_id, external_id, external_parent_id,
                           record_type, mime_type, payload,
                           source_created_at, source_updated_at, content_hash,
                           rights_manifest_id, adapter_version, status)
                        VALUES
                          (:sid, :ext, :parent, :record_type, 'application/json',
                           CAST(:payload AS jsonb), :source_created, :source_updated,
                           :hash, NULL, :ver, 'active')
                        ON CONFLICT (source_id, external_id, content_hash) DO UPDATE SET
                          payload = EXCLUDED.payload,
                          retention_state = 'hot',
                          payload_purged_at = NULL,
                          purge_policy_version = NULL,
                          last_seen_at = now(),
                          external_parent_id = EXCLUDED.external_parent_id,
                          source_created_at = COALESCE(
                            EXCLUDED.source_created_at,
                            raw_source_records.source_created_at
                          ),
                          source_updated_at = COALESCE(
                            EXCLUDED.source_updated_at,
                            raw_source_records.source_updated_at
                          ),
                          adapter_version = EXCLUDED.adapter_version,
                          status = 'active'
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "sid": self.source_id,
                        "ext": external_id(record),
                        "parent": (
                            external_parent_id(record) if external_parent_id else None
                        ),
                        "record_type": record_type,
                        "payload": payload,
                        "source_created": (
                            source_created_at(record) if source_created_at else None
                        ),
                        "source_updated": (
                            source_updated_at(record) if source_updated_at else None
                        ),
                        "hash": content_hash,
                        "ver": self.adapter_version,
                    },
                )
                row = result.fetchone()
                stored += int(bool(row and row[0]))
        return stored

    # ------------------------------------------------------------------ health
    def health_check(self) -> bool:
        return self.client.health_check()

    # ------------------------------------------------------------------ fixtures
    def save_fixture(self, offset: int, markets: list[dict[str, Any]]) -> Path:
        """Persist a market page as a fixture for offline tests."""
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self.fixture_dir / f"markets_offset_{offset}.json"
        path.write_text(
            json.dumps(markets, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def close(self) -> None:
        self.client.close()


def select_monitored_markets(
    events: list[dict[str, Any]],
    *,
    max_markets: int = DEFAULT_MONITORED_MARKETS,
    markets_per_event: int = DEFAULT_MARKETS_PER_EVENT,
) -> list[dict[str, Any]]:
    """Flatten active events into a bounded and event-diverse market set.

    A raw global volume sort is easily monopolised by one election slate or a
    single sports match with dozens of derivatives.  We rank markets within
    each event, cap each event, then globally rank the retained set.  This is a
    monitoring-budget decision, not an editorial exclusion: the event envelope
    itself is still stored and can be revisited on the next refresh.
    """
    cohorts: list[tuple[tuple[float, float, float, float], list[dict[str, Any]]]] = []
    for event in events:
        nested = event.get("markets")
        if not isinstance(nested, list):
            continue
        event_markets: list[dict[str, Any]] = []
        for raw_market in nested:
            if (
                not isinstance(raw_market, dict)
                or raw_market.get("closed") is True
                or raw_market.get("archived") is True
                or raw_market.get("active") is False
            ):
                continue
            market = _with_event_identity(raw_market, event=event)
            event_markets.append(market)
        selected = _select_event_monitoring_cohort(
            event_markets,
            limit=markets_per_event,
        )
        if selected:
            cohorts.append((max((_market_rank_key(item) for item in selected)), selected))

    # Round-robin the retained event cohorts.  Every event's leading
    # representative is considered before a second member from any event.
    cohorts.sort(key=lambda item: item[0], reverse=True)
    monitored: list[dict[str, Any]] = []
    maximum_depth = max((len(items) for _, items in cohorts), default=0)
    for position in range(maximum_depth):
        for _, items in cohorts:
            if position < len(items):
                monitored.append(items[position])
                if len(monitored) >= max_markets:
                    return monitored
    return monitored


def _market_activity(market: dict[str, Any]) -> float:
    """Return only same-window activity; never substitute lifetime volume."""
    return _number_field(market, "volume24hr", "volume24h")


def _select_event_monitoring_cohort(
    markets: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not markets or limit <= 0:
        return []

    probability_leaders = sorted(
        markets,
        key=lambda market: (_market_probability(market), *_market_rank_key(market)),
        reverse=True,
    )[:3]
    movers = sorted(
        (market for market in markets if _one_day_move(market) > 0),
        key=lambda market: (_one_day_move(market), *_market_rank_key(market)),
        reverse=True,
    )[:2]
    activity = max(markets, key=_market_rank_key)
    other = next(
        (
            market
            for market in markets
            if market.get("negRiskOther") is True
            or str(market.get("groupItemTitle") or "").strip().casefold() == "other"
        ),
        None,
    )
    ranked = sorted(markets, key=_market_rank_key, reverse=True)
    ordered = [*probability_leaders, *movers, activity]
    if other is not None:
        ordered.append(other)
    ordered.extend(ranked)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for market in ordered:
        market_id = str(market.get("id") or "")
        if not market_id or market_id in seen:
            continue
        selected.append(market)
        seen.add(market_id)
        if len(selected) >= limit:
            break
    return selected


def _market_rank_key(market: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _market_activity(market),
        _number_field(market, "volume"),
        _number_field(market, "liquidity"),
        _market_probability(market),
    )


def _market_probability(market: dict[str, Any]) -> float:
    value: Any = market.get("outcomePrices")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return 0.0
    if not isinstance(value, list) or not value:
        return 0.0
    try:
        return float(value[0])
    except (TypeError, ValueError):
        return 0.0


def _one_day_move(market: dict[str, Any]) -> float:
    return abs(_signed_number_field(market, "oneDayPriceChange"))


def _number_field(market: dict[str, Any], *fields: str) -> float:
    for field in fields:
        try:
            value = float(market.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def _signed_number_field(market: dict[str, Any], *fields: str) -> float:
    for field in fields:
        try:
            return float(market.get(field) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _with_event_identity(
    raw_market: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market = dict(raw_market)
    nested = market.get("events")
    nested_event = (
        nested[0]
        if isinstance(nested, list)
        and len(nested) == 1
        and isinstance(nested[0], dict)
        else {}
    )
    source_event = event or nested_event
    if not market.get("eventId"):
        market["eventId"] = source_event.get("id")
    if not market.get("eventTitle"):
        market["eventTitle"] = source_event.get("title")
    if not market.get("eventSlug"):
        market["eventSlug"] = source_event.get("slug")
    if not market.get("tags") and isinstance(source_event.get("tags"), list):
        market["tags"] = source_event["tags"]
    return market


def _source_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed
