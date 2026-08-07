"""Market observation collector (spec §88.3, §102, OS-008).

Periodically samples current prices from the Gamma API into
``market_observations`` (range-partitioned by observed_at). Observations
are bucketed to ``bucket_minutes`` so a repeated run within the same bucket
is idempotent; data quality flags mark missing or suspicious fields;
rate limiting is handled via httpx retries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from open_signal.sources.polymarket import GammaClient

BUCKET_MINUTES = 5
PRICE_METHOD = "source_probability"


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
        bucket_minutes: int = BUCKET_MINUTES,
        retry_attempts: int = 3,
    ) -> None:
        self.engine = engine
        self.client = client or GammaClient()
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

    def _store_observation(self, market: dict[str, Any], *, external_id: str | None) -> int:
        from sqlalchemy import text

        market_uuid = external_id  # caller resolves Gamma id -> source_markets.uuid
        if market_uuid is None:
            return 0

        observed_at = floor_to_bucket(datetime.now(timezone.utc), self.bucket_minutes)
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

    def close(self) -> None:
        self.client.close()
