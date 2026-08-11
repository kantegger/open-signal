"""Deterministic candidate detection (spec §32.5, OS-010).

Computes delta_1h / delta_24h / delta_7d / direction / persistence /
acceleration / reversal / distance_to_resolution / data completeness from
the market_observations series, then applies the first-version eligibility
thresholds. Every evaluation writes a Calculation Record.

First-version thresholds (spec §32.5):
  delta_24h >= 3 percentage points
  and |delta_24h| >= 2 x own quote spread
  and data quality not stale/sparse/unavailable
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

CALCULATION_VERSION = "0.1.0"

MIN_DELTA_24H = 3.0  # percentage points
SPREAD_MULTIPLIER = 2.0
SCANNER_MIN_DELTA_24H = 0.5
SCANNER_SPREAD_MULTIPLIER = 1.0
DATA_QUALITY_BAD = {"stale", "sparse", "unavailable"}


def _recent(rows: list[tuple[Any, ...]], horizon: timedelta, now: datetime) -> list[Any]:
    cutoff = now - horizon
    return [r for r in rows if r[1] >= cutoff]


class CandidateDetector:
    def __init__(self, engine: Any, version: str = CALCULATION_VERSION) -> None:
        self.engine = engine
        self.version = version

    # ------------------------------------------------------------- computation
    def compute_for_market(self, source_market_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Compute metrics for one source market from its observation series."""
        now = now or datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT probability, observed_at, best_bid, best_ask,
                           data_quality_flags
                    FROM market_observations
                    WHERE source_market_id = :m
                    ORDER BY observed_at ASC
                    """
                ),
                {"m": source_market_id},
            ).fetchall()
            deadline = conn.execute(
                text("SELECT ends_at FROM source_markets WHERE id = :m"),
                {"m": source_market_id},
            ).scalar_one_or_none()

        return self.compute_from_series(
            source_market_id,
            [(r[0], r[1], r[2], r[3], r[4]) for r in rows],
            now=now,
            resolution_deadline_at=deadline,
        )

    def compute_from_series(
        self,
        subject_id: str,
        series: list[tuple[Any, ...]],
        now: datetime | None = None,
        resolution_deadline_at: datetime | None = None,
    ) -> dict[str, Any]:
        """series rows: (probability, observed_at, best_bid, best_ask, flags)"""
        now = now or datetime.now(timezone.utc)
        h1 = _recent(series, timedelta(hours=1), now)
        h24 = _recent(series, timedelta(hours=24), now)
        d7 = _recent(series, timedelta(days=7), now)

        current = _latest_probability(series)
        # baseline = earliest observation inside each window (approx. the
        # probability N hours ago, given ~5-min bucket density)
        p_1h = _first_in_window(h1)
        p_24h = _first_in_window(h24)
        p_7d = _first_in_window(d7)

        delta_1h = _pp(current, p_1h)
        delta_24h = _pp(current, p_24h)
        delta_7d = _pp(current, p_7d)

        direction = 1 if delta_24h > 0 else (-1 if delta_24h < 0 else 0)
        persistence = _persistence(series, direction, now)
        acceleration = _acceleration(h24)
        reversal = _reversal(h24)

        spread = _latest_spread(series)
        flags = _latest_flags(series)
        data_quality = "ok" if not (set(flags) & DATA_QUALITY_BAD) else ",".join(sorted(set(flags) & DATA_QUALITY_BAD))
        data_completeness = round(len(h24) / max(1, 24 * 12), 4)  # ~5-min buckets
        distance_to_resolution_days = (
            round((resolution_deadline_at - now).total_seconds() / 86_400, 4)
            if resolution_deadline_at is not None
            else None
        )

        # §32.5 eligibility is the featured-story threshold.  The scanner
        # threshold feeds compact, observation-only surfaces; it does not
        # lower the bar for analytical or editorial treatment.
        eligible = (
            abs(delta_24h) >= MIN_DELTA_24H
            and (spread is None or abs(delta_24h) >= SPREAD_MULTIPLIER * (spread * 100))
            and data_quality == "ok"
        )
        scanner_eligible = (
            len(series) >= 2
            and abs(delta_24h) >= SCANNER_MIN_DELTA_24H
            and (
                spread is None
                or abs(delta_24h)
                >= SCANNER_SPREAD_MULTIPLIER * (spread * 100)
            )
            and data_quality == "ok"
        )
        publication_tier = (
            "featured" if eligible else "scanner" if scanner_eligible else "none"
        )
        signal_score = (
            abs(delta_24h)
            + min(abs(delta_1h), 4.0) * 0.35
            + (1.25 if reversal else 0.0)
            + min(persistence, 1.0) * 0.5
        )

        output = {
            "delta_1h": round(delta_1h, 4),
            "delta_24h": round(delta_24h, 4),
            "delta_7d": round(delta_7d, 4),
            "current_probability": current,
            "direction": direction,
            "persistence": persistence,
            "acceleration": acceleration,
            "reversal": reversal,
            "distance_to_resolution_days": distance_to_resolution_days,
            "data_quality": data_quality,
            "data_completeness": data_completeness,
            "series_size": len(series),
            "eligible": eligible,
            "scanner_eligible": scanner_eligible,
            "publication_tier": publication_tier,
            "signal_score": round(signal_score, 4),
            "thresholds": {
                "min_delta_24h_pp": MIN_DELTA_24H,
                "spread_multiplier": SPREAD_MULTIPLIER,
                "scanner_min_delta_24h_pp": SCANNER_MIN_DELTA_24H,
                "scanner_spread_multiplier": SCANNER_SPREAD_MULTIPLIER,
            },
        }
        return output

    # ------------------------------------------------------------- persistence
    def record_calculation(self, subject_id: str, output: dict[str, Any], input_snapshot: dict[str, Any] | None = None) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO calculation_records
                      (calculation_type, subject_id, subject_type, input_snapshot,
                       output, calculation_version)
                    VALUES ('candidate_detection', :sid, 'source_market',
                            CAST(:input AS jsonb), CAST(:output AS jsonb), :ver)
                    RETURNING id
                    """
                ),
                {
                    "sid": subject_id,
                    "input": json.dumps(input_snapshot or {}),
                    "output": json.dumps(output),
                    "ver": self.version,
                },
            ).fetchone()
        return str(row[0])

    def detect(self, source_market_ids: list[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Run detection over active markets (optionally filtered), writing
        calculation records. Returns the eligible candidates."""
        if source_market_ids is None:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT source_market_id FROM market_observations
                        GROUP BY source_market_id ORDER BY max(observed_at) DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                ).fetchall()
            source_market_ids = [str(r[0]) for r in rows]

        candidates: list[dict[str, Any]] = []
        for mid in source_market_ids:
            output = self.compute_for_market(mid)
            self.record_calculation(mid, output)
            if output["eligible"]:
                candidates.append({"source_market_id": mid, **output})
        return candidates


def _latest_probability(rows: list[tuple[Any, ...]]) -> float | None:
    for r in reversed(rows):
        if r[0] is not None:
            return float(r[0])
    return None


def _first_in_window(rows: list[tuple[Any, ...]]) -> float | None:
    for r in rows:
        if r[0] is not None:
            return float(r[0])
    return None


def _latest_spread(rows: list[tuple[Any, ...]]) -> float | None:
    for r in reversed(rows):
        bid, ask = r[2], r[3]
        if bid is not None and ask is not None:
            return float(ask - bid)
    return None


def _latest_flags(rows: list[tuple[Any, ...]]) -> list[str]:
    for r in reversed(rows):
        if r[4]:
            return list(r[4])
    return []


def _pp(current: float | None, previous: float | None) -> float:
    if current is None or previous is None:
        return 0.0
    return (current - previous) * 100.0  # percentage points


def _persistence(rows: list[tuple[Any, ...]], direction: int, now: datetime) -> float:
    """Share of the last 24h window where direction matched the current trend."""
    if direction == 0:
        return 0.0
    window = _recent(rows, timedelta(hours=24), now)
    if len(window) < 2:
        return 0.0
    aligned = 0
    for prev, cur in itertools.pairwise(window):
        if prev[0] is None or cur[0] is None:
            continue
        step = 1 if cur[0] > prev[0] else (-1 if cur[0] < prev[0] else 0)
        if step == direction:
            aligned += 1
    return round(aligned / max(1, len(window) - 1), 4)


def _acceleration(h24: list[tuple[Any, ...]]) -> float:
    """Recent delta magnitude vs earlier delta magnitude within 24h."""
    if len(h24) < 4:
        return 0.0
    recent = _pp(_latest_probability(h24), _latest_probability(h24[max(0, len(h24) // 2):]))
    earlier = _pp(_latest_probability(h24[: len(h24) // 2]), _latest_probability(h24[:1]))
    if abs(earlier) < 1e-9:
        return 0.0
    return round(recent / abs(earlier), 4)


def _reversal(h24: list[tuple[Any, ...]]) -> bool:
    """True if the 24h series shows a clear direction reversal."""
    if len(h24) < 6:
        return False
    half = len(h24) // 2
    first_half = _pp(_latest_probability(h24[half:]), _latest_probability(h24[:half]))
    if abs(first_half) < 1e-9:
        return False
    # walk the series: sign changes against the dominant move indicate reversal
    dominant = 1 if first_half > 0 else -1
    reversals = 0
    prev = h24[0][0]
    for r in h24[1:]:
        if prev is None or r[0] is None:
            prev = r[0]
            continue
        step = 1 if r[0] > prev else (-1 if r[0] < prev else 0)
        if step == -dominant:
            reversals += 1
        prev = r[0]
    return reversals >= 2
