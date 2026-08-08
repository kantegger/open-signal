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
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from open_signal.db.models import source_cursors

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DEFAULT_PAGE_SIZE = 100

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
            params={"offset": offset, "limit": limit, "closed": str(closed).lower()},
        )
        resp.raise_for_status()
        return resp.json()

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

    def refresh(self, *, max_pages: int = 3) -> dict[str, int]:
        """Re-read the leading active-market pages without advancing a cursor.

        ``discover`` is useful for a finite historical crawl.  A rolling source
        cannot keep resuming beyond the end of that crawl: it must revisit the
        leading active records so changed prices produce a new content hash and
        a new observation.  Storage remains idempotent.
        """
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
        return {"markets": markets_total, "pages": pages}

    # ------------------------------------------------------------------ storage
    def _load_page(self, offset: int) -> list[dict[str, Any]]:
        """Load one page from fixtures (offline mode) or the live API."""
        fixture = self.fixture_dir / f"markets_offset_{offset}.json"
        if fixture.exists():
            with fixture.open(encoding="utf-8") as f:
                return json.load(f)
        if self.offline:
            return []  # end of fixture data
        return self.client.fetch_markets(offset=offset, limit=self.page_size)

    def _store_raw_markets(self, markets: list[dict[str, Any]]) -> int:
        """Insert raw records idempotently (unique source_id/external_id/hash)."""
        from sqlalchemy import text

        stored = 0
        with self.engine.begin() as conn:
            for market in markets:
                payload = json.dumps(market, ensure_ascii=False, sort_keys=True)
                content_hash = hashlib.sha256(payload.encode()).hexdigest()
                result = conn.execute(
                    text(
                        """
                        INSERT INTO raw_source_records
                          (source_id, external_id, record_type, mime_type, payload,
                           source_created_at, source_updated_at, content_hash,
                           rights_manifest_id, adapter_version, status)
                        VALUES
                          (:sid, :ext, 'market', 'application/json', CAST(:payload AS jsonb),
                           NULL, NULL, :hash, NULL, :ver, 'active')
                        ON CONFLICT (source_id, external_id, content_hash) DO NOTHING
                        """
                    ),
                    {
                        "sid": self.source_id,
                        "ext": str(market.get("id")),
                        "payload": payload,
                        "hash": content_hash,
                        "ver": self.adapter_version,
                    },
                )
                stored += result.rowcount
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
