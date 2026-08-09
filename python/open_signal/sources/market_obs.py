"""Market observation collector (spec §88.3, §102, OS-008).

Periodically samples current prices from the Gamma API into
``market_observations`` (range-partitioned by observed_at). Observations
are bucketed to ``bucket_minutes`` so a repeated run within the same bucket
is idempotent; data quality flags mark missing or suspicious fields;
rate limiting is handled via httpx retries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text

from open_signal.sources.polymarket import GammaClient

BUCKET_MINUTES = 5
PRICE_METHOD = "source_probability"
CLOB_HISTORY_METHOD = "clob_history"
CLOB_BASE_URL = "https://clob.polymarket.com"
HISTORY_BATCH_SIZE = 20
HISTORY_FIDELITY_MINUTES = 60
MIN_HISTORY_POINTS = 24


class PriceHistoryClient:
    """Read-only client for Polymarket's public batch price history."""

    def __init__(
        self,
        base_url: str = CLOB_BASE_URL,
        timeout: float = 30.0,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    def fetch_batch(
        self,
        token_ids: list[str],
        *,
        start_ts: int,
        end_ts: int,
        fidelity: int = HISTORY_FIDELITY_MINUTES,
    ) -> dict[str, list[dict[str, Any]]]:
        if not token_ids or len(token_ids) > HISTORY_BATCH_SIZE:
            raise ValueError("price-history batches must contain 1 to 20 token ids")
        response = self._client.post(
            "/batch-prices-history",
            json={
                "markets": token_ids,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "fidelity": fidelity,
            },
        )
        response.raise_for_status()
        payload = response.json()
        history = payload.get("history") if isinstance(payload, dict) else None
        return history if isinstance(history, dict) else {}

    def close(self) -> None:
        self._client.close()


def floor_to_bucket(now: datetime, bucket_minutes: int) -> datetime:
    """Floor a timestamp to the start of its bucket."""
    seconds = bucket_minutes * 60
    ts = int(now.timestamp())
    return datetime.fromtimestamp(ts - (ts % seconds), tz=timezone.utc)


def parse_probability(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MarketObservationCollector:
    """Samples market prices into market_observations (idempotent)."""

    def __init__(
        self,
        engine: Any,
        *,
        client: GammaClient | None = None,
        history_client: PriceHistoryClient | None = None,
        bucket_minutes: int = BUCKET_MINUTES,
        retry_attempts: int = 3,
    ) -> None:
        self.engine = engine
        self.client = client or GammaClient()
        self.history_client = history_client or PriceHistoryClient()
        self.bucket_minutes = bucket_minutes
        self.retry_attempts = retry_attempts

    # ------------------------------------------------------------------ public
    def collect_from_api(self, source_market_ids: list[str], external_ids: dict[str, str] | None = None) -> int:
        """Fetch current price for each market id from the Gamma API and
        store an observation. Returns the number of new rows written."""
        stored = 0
        for market_id in source_market_ids:
            market = self._fetch_with_retry(market_id)
            if market is None:
                continue
            stored += self._store_observation(market, external_id=external_ids.get(market_id) if external_ids else None)
        return stored

    def collect_from_records(self, engine_conn: Any, markets: list[dict[str, Any]]) -> int:
        """Offline/test path: store observations from already-fetched market
        dicts (e.g. from raw_source_records payloads or fixtures)."""
        stored = 0
        for market in markets:
            stored += self._store_observation(market, external_id=str(market.get("id")))
        return stored

    def backfill_history(
        self,
        markets: list[tuple[str, str]],
        *,
        days: int = 7,
        fidelity: int = HISTORY_FIDELITY_MINUTES,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Backfill hourly YES-token history for newly monitored markets.

        The current Gamma snapshot is still authoritative for order-book
        fields.  CLOB history supplies the missing time dimension so the first
        production run can evaluate 24-hour and 7-day movement instead of
        waiting a full day to accumulate local samples.
        """
        now = now or datetime.now(timezone.utc)
        unique = dict(markets)
        if not unique:
            return {"markets": 0, "batches": 0, "observations": 0, "errors": 0}

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT source_market_id, min(observed_at), count(*)
                    FROM market_observations
                    WHERE source_market_id = ANY(CAST(:market_ids AS uuid[]))
                    GROUP BY source_market_id
                    """
                ),
                {"market_ids": list(unique)},
            ).fetchall()
        stats = {str(row[0]): (row[1], int(row[2])) for row in rows}
        history_cutoff = now - timedelta(hours=25)
        needed = [
            (market_id, token_id)
            for market_id, token_id in unique.items()
            if market_id not in stats
            or stats[market_id][1] < MIN_HISTORY_POINTS
            or stats[market_id][0] > history_cutoff
        ]

        token_to_market = {token_id: market_id for market_id, token_id in needed}
        token_ids = list(token_to_market)
        start_ts = int((now - timedelta(days=max(1, days))).timestamp())
        end_ts = int(now.timestamp())
        stored = batches = errors = 0
        for index in range(0, len(token_ids), HISTORY_BATCH_SIZE):
            batch = token_ids[index : index + HISTORY_BATCH_SIZE]
            batches += 1
            try:
                history = self.history_client.fetch_batch(
                    batch,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    fidelity=fidelity,
                )
            except (httpx.HTTPError, ValueError):
                errors += 1
                continue
            incoming: list[dict[str, Any]] = []
            for token_id in batch:
                market_id = token_to_market[token_id]
                points = history.get(token_id)
                if not isinstance(points, list):
                    continue
                incoming.extend(
                    history_rows(
                        market_id,
                        points,
                        bucket_minutes=fidelity,
                    )
                )
            stored += self._store_history_rows(incoming)
        return {
            "markets": len(needed),
            "batches": batches,
            "observations": stored,
            "errors": errors,
        }

    # ---------------------------------------------------------------- internal
    def _fetch_with_retry(self, market_id: str) -> dict[str, Any] | None:

        # GammaClient is thin; add a simple retry loop here for rate limits.
        attempt = 0
        while attempt < self.retry_attempts:
            try:
                resp = self.client._client.get(f"/markets/{market_id}")
                if resp.status_code == 429:
                    attempt += 1
                    import time

                    time.sleep(2 * attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError:
                attempt += 1
        return None

    def _store_observation(self, market: dict[str, Any], *, external_id: str | None, observed_at_override: datetime | None = None) -> int:
        from sqlalchemy import text

        market_uuid = external_id  # caller resolves Gamma id -> source_markets.uuid
        if market_uuid is None:
            return 0

        observed_at = observed_at_override or floor_to_bucket(datetime.now(timezone.utc), self.bucket_minutes)
        flags: list[str] = []

        prices = market.get("outcomePrices") or []
        if isinstance(prices, str):  # Gamma returns a JSON-encoded string
            try:
                prices = json.loads(prices)
            except (TypeError, ValueError):
                prices = []
        probability = parse_probability(prices[0]) if prices else None
        best_bid = parse_probability(market.get("bestBid"))
        best_ask = parse_probability(market.get("bestAsk"))
        last_trade = parse_probability(market.get("lastTradePrice"))
        spread = parse_probability(market.get("spread"))
        volume = parse_probability(market.get("volume"))
        parse_probability(market.get("liquidity"))

        if probability is None:
            flags.append("missing_probability")
        if best_bid is None or best_ask is None:
            flags.append("missing_order_book")
        if best_bid is not None and best_ask is not None and best_ask <= best_bid:
            flags.append("invalid_order_book")
        if market.get("closed"):
            flags.append("market_closed")

        midpoint: float | None = None
        if best_bid is not None and best_ask is not None:
            midpoint = round((best_bid + best_ask) / 2, 6)

        with self.engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM market_observations "
                    "WHERE source_market_id = :m AND observed_at = :t LIMIT 1"
                ),
                {"m": market_uuid, "t": observed_at},
            ).fetchone()
            if exists:
                return 0  # idempotent within bucket

            conn.execute(
                text(
                    """
                    INSERT INTO market_observations
                      (source_market_id, observed_at, probability,
                       best_bid, best_ask, midpoint, last_trade_price, spread,
                       volume, open_interest, price_method, data_quality_flags)
                    VALUES
                      (:m, :t, :p, :bid, :ask, :mid, :last, :spread,
                       :volume, NULL, :method, :flags)
                    """
                ),
                {
                    "m": market_uuid,
                    "t": observed_at,
                    "p": probability,
                    "bid": best_bid,
                    "ask": best_ask,
                    "mid": midpoint,
                    "last": last_trade,
                    "spread": spread,
                    "volume": volume,
                    "method": PRICE_METHOD,
                    "flags": flags,
                },
            )
        return 1

    def _store_history_rows(self, rows: list[dict[str, Any]]) -> int:
        """Insert a history batch without per-point transactions."""
        if not rows:
            return 0
        from sqlalchemy import text

        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    WITH incoming AS (
                      SELECT DISTINCT ON (source_market_id, observed_at)
                             source_market_id::uuid AS source_market_id,
                             observed_at,
                             probability
                      FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS item(
                        source_market_id text,
                        observed_at timestamptz,
                        probability numeric
                      )
                      ORDER BY source_market_id, observed_at
                    )
                    INSERT INTO market_observations
                      (source_market_id, observed_at, probability,
                       best_bid, best_ask, midpoint, last_trade_price, spread,
                       volume, open_interest, price_method, data_quality_flags)
                    SELECT incoming.source_market_id, incoming.observed_at,
                           incoming.probability, NULL, NULL, NULL, NULL, NULL,
                           NULL, NULL, :method,
                           ARRAY['historical_price_only']::text[]
                    FROM incoming
                    WHERE NOT EXISTS (
                      SELECT 1 FROM market_observations existing
                      WHERE existing.source_market_id = incoming.source_market_id
                        AND existing.observed_at = incoming.observed_at
                    )
                    """
                ),
                {"rows": json.dumps(rows), "method": CLOB_HISTORY_METHOD},
            )
        return max(0, int(result.rowcount or 0))

    def close(self) -> None:
        self.client.close()
        self.history_client.close()


def history_rows(
    source_market_id: str,
    points: list[dict[str, Any]],
    *,
    bucket_minutes: int = HISTORY_FIDELITY_MINUTES,
) -> list[dict[str, Any]]:
    """Normalize CLOB ``{t, p}`` points into deduplicated DB rows."""
    normalized: dict[str, dict[str, Any]] = {}
    for point in points:
        try:
            timestamp = float(point.get("t"))
        except (AttributeError, TypeError, ValueError):
            continue
        probability = parse_probability(point.get("p"))
        if probability is None or not 0 <= probability <= 1:
            continue
        observed_at = floor_to_bucket(
            datetime.fromtimestamp(timestamp, tz=timezone.utc),
            bucket_minutes,
        )
        key = observed_at.isoformat()
        normalized[key] = {
            "source_market_id": source_market_id,
            "observed_at": key,
            "probability": probability,
        }
    return list(normalized.values())
