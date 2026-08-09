"""Evidence contract for public market-series graphics.

The helpers in this module never interpolate observations.  They classify the
captured window and retain only actual endpoints and bucket extrema when a
series must be reduced for publication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from typing import Any

SERIES_WINDOW = timedelta(days=7)
SERIES_MIN_OBSERVATIONS = 24
SERIES_MIN_SPAN = timedelta(days=6)
SERIES_MAX_RECENCY = timedelta(hours=12)
SERIES_MAX_GAP = timedelta(hours=24)
SERIES_MIN_DISTINCT_VALUES = 3
SERIES_MIN_RANGE = 0.005
SERIES_MAX_POINTS = 48


def market_series_snapshot(
    rows: list[tuple[Any, Any]], *, captured_at: datetime
) -> dict[str, Any]:
    """Describe and safely reduce an observed market series."""

    captured_at = _utc(captured_at)
    by_timestamp: dict[datetime, float] = {}
    for observed_at, raw_probability in rows:
        probability = _number(raw_probability)
        if not isinstance(observed_at, datetime) or probability is None:
            continue
        timestamp = _utc(observed_at)
        if timestamp > captured_at or not 0 <= probability <= 1:
            continue
        by_timestamp[timestamp] = probability

    observations = sorted(by_timestamp.items())
    count = len(observations)
    first_at = observations[0][0] if observations else None
    last_at = observations[-1][0] if observations else None
    span = (last_at - first_at) if first_at and last_at else timedelta(0)
    gaps = [
        current[0] - previous[0]
        for previous, current in pairwise(observations)
    ]
    max_gap = max(gaps, default=timedelta(0))
    probabilities = [point[1] for point in observations]
    probability_range = (
        max(probabilities) - min(probabilities) if probabilities else 0.0
    )
    distinct_values = len({round(value, 4) for value in probabilities})

    if count < SERIES_MIN_OBSERVATIONS:
        coverage_status = "insufficient_observations"
    elif span < SERIES_MIN_SPAN:
        coverage_status = "partial_window"
    elif last_at is None or captured_at - last_at > SERIES_MAX_RECENCY:
        coverage_status = "stale_endpoint"
    elif max_gap > SERIES_MAX_GAP:
        coverage_status = "gapped"
    elif (
        distinct_values < SERIES_MIN_DISTINCT_VALUES
        or probability_range < SERIES_MIN_RANGE
    ):
        coverage_status = "no_material_variation"
    else:
        coverage_status = "complete"

    sampled = _downsample_series(observations)
    return {
        "points": [[point[0].isoformat(), point[1]] for point in sampled],
        "quality": {
            "coverage_status": coverage_status,
            "requested_window_hours": int(SERIES_WINDOW.total_seconds() / 3600),
            "observation_count": count,
            "points_returned": len(sampled),
            "first_observed_at": _iso(first_at),
            "last_observed_at": _iso(last_at),
            "span_hours": round(span.total_seconds() / 3600, 1),
            "max_gap_hours": round(max_gap.total_seconds() / 3600, 1),
            "probability_range_percentage_points": round(
                probability_range * 100, 2
            ),
        },
    }


def _downsample_series(
    observations: list[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    if len(observations) <= SERIES_MAX_POINTS:
        return observations

    selected = {0, len(observations) - 1}
    interior_count = len(observations) - 2
    bucket_count = max(1, (SERIES_MAX_POINTS - 2) // 2)
    for bucket_index in range(bucket_count):
        start = 1 + (bucket_index * interior_count) // bucket_count
        end = 1 + ((bucket_index + 1) * interior_count) // bucket_count
        if start >= end:
            continue
        indices = range(start, end)
        selected.add(min(indices, key=lambda index: observations[index][1]))
        selected.add(max(indices, key=lambda index: observations[index][1]))
    return [observations[index] for index in sorted(selected)]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
