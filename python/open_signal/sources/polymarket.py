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
            compact_events.append(compact)
        return self._store_raw_records(
            compact_events,
            record_type="event",
            external_id=lambda event: f"event:{event.get('id')}",
        )

    def _store_raw_markets(self, markets: list[dict[str, Any]]) -> int:
        """Insert raw records idempotently (unique source_id/external_id/hash)."""
        return self._store_raw_records(
            markets,
            record_type="market",
            external_id=lambda market: str(market.get("id")),
        )

    def _store_raw_records(
        self,
        records: list[dict[str, Any]],
        *,
        record_type: str,
        external_id: Callable[[dict[str, Any]], str],
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
                          (source_id, external_id, record_type, mime_type, payload,
                           source_created_at, source_updated_at, content_hash,
                           rights_manifest_id, adapter_version, status)
                        VALUES
                          (:sid, :ext, :record_type, 'application/json', CAST(:payload AS jsonb),
                           NULL, NULL, :hash, NULL, :ver, 'active')
                        ON CONFLICT (source_id, external_id, content_hash) DO UPDATE SET
                          last_seen_at = now(),
                          adapter_version = EXCLUDED.adapter_version,
                          status = 'active'
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "sid": self.source_id,
                        "ext": external_id(record),
                        "record_type": record_type,
                        "payload": payload,
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
    retained: dict[str, dict[str, Any]] = {}
    for event in events:
        nested = event.get("markets")
        if not isinstance(nested, list):
            continue
        event_markets: list[dict[str, Any]] = []
        for raw_market in nested:
            if not isinstance(raw_market, dict) or raw_market.get("closed") is True:
                continue
            market = dict(raw_market)
            market.setdefault("eventId", event.get("id"))
            market.setdefault("eventTitle", event.get("title"))
            market.setdefault("eventSlug", event.get("slug"))
            if not market.get("tags") and isinstance(event.get("tags"), list):
                market["tags"] = event["tags"]
            event_markets.append(market)
        event_markets.sort(key=_market_activity, reverse=True)
        for market in event_markets[:markets_per_event]:
            market_id = str(market.get("id") or "")
            if market_id:
                retained[market_id] = market

    ranked = sorted(retained.values(), key=_market_activity, reverse=True)
    return ranked[:max_markets]


def _market_activity(market: dict[str, Any]) -> float:
    for field in ("volume24hr", "volume24h", "volume", "liquidity"):
        try:
            value = float(market.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0
