"""Deterministic event-aware selection for public Expectations surfaces.

Canonical Expectations remain proposition-level truth objects.  This module
adds a presentation-only family layer so a source event with many binary
markets cannot monopolise Explore, Current, or an editorial batch.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from open_signal.derived.public_interest import (
    EditorialScopeDecision,
    classify_expectation_scope,
    surface_rank,
)

SELECTION_VERSION = "expectation-selection-1.1.0"
BAD_QUALITY_FLAGS = {"stale", "sparse", "unavailable"}
HARD_OBSERVATION_AGE = timedelta(hours=72)
CURRENT_COHORT_TOLERANCE = timedelta(minutes=10)
MIN_SCANNER_MOVE_PP = 0.5
MIN_FEATURED_MOVE_PP = 3.0
MIN_PUBLIC_VOLUME_24H = 5_000.0
TAIL_MAX_PROBABILITY = 0.05
TAIL_MIN_LOG_ODDS_MOVE = math.log(2)
NEAR_RESOLUTION_DAYS = 7


@dataclass(frozen=True, slots=True)
class ExpectationFact:
    topic_id: str
    market_id: str
    source_id: str
    source_slug: str
    title: str
    event_type: str
    deadline_at: datetime
    canonical_status: str
    market_status: str
    external_event_id: str | None
    event_title: str | None
    event_slug: str | None
    group_item_title: str | None
    neg_risk_market_id: str | None
    is_exclusive_slate: bool
    source_member_count: int
    current_probability: float | None
    current_observed_at: datetime | None
    baseline_probability_24h: float | None
    baseline_observed_at: datetime | None
    spread: float | None
    data_quality_flags: tuple[str, ...]
    volume_24h: float
    lifetime_volume: float
    liquidity: float
    monitoring_last_seen_at: datetime | None
    source_monitoring_at: datetime | None
    recent_claim_id: str | None
    recent_claim_at: datetime | None
    raw_payload: dict[str, Any]
    tags: tuple[str, ...] = ()

    @property
    def event_key(self) -> str:
        if self.external_event_id:
            return f"{self.source_id}:event:{self.external_event_id}"
        return f"{self.source_id}:market:{self.market_id}"

    @property
    def delta_24h_percentage_points(self) -> float | None:
        if (
            self.current_probability is None
            or self.baseline_probability_24h is None
        ):
            return None
        return round(
            (self.current_probability - self.baseline_probability_24h) * 100,
            4,
        )

    @property
    def is_current_monitoring_cohort(self) -> bool:
        if self.source_monitoring_at is None:
            return True
        if self.monitoring_last_seen_at is None:
            return False
        return (
            self.source_monitoring_at - self.monitoring_last_seen_at
            <= CURRENT_COHORT_TOLERANCE
        )


@dataclass(frozen=True, slots=True)
class SelectedExpectationMember:
    fact: ExpectationFact
    selection_reason: str


@dataclass(frozen=True, slots=True)
class ExpectationEventGroup:
    key: str
    title: str
    event_type: str
    external_event_id: str | None
    event_slug: str | None
    source_slug: str
    source_member_count: int
    eligible_member_count: int
    is_exclusive_slate: bool
    members: tuple[SelectedExpectationMember, ...]
    representative: ExpectationFact
    priority_class: int
    selection_reason: str
    volume_24h: float
    largest_move_pp: float | None
    latest_observed_at: datetime
    nearest_deadline_at: datetime
    editorial_scope: EditorialScopeDecision

    @property
    def suppressed_member_count(self) -> int:
        return max(0, self.source_member_count - len(self.members))

    @property
    def unmonitored_member_count(self) -> int:
        return max(0, self.source_member_count - self.eligible_member_count)

    @property
    def folded_eligible_member_count(self) -> int:
        return max(0, self.eligible_member_count - len(self.members))

    @property
    def sort_key(self) -> tuple[Any, ...]:
        return (
            -surface_rank(self.editorial_scope.maximum_surface),
            -self.editorial_scope.importance_score,
            self.priority_class,
            -abs(self.largest_move_pp or 0.0),
            -math.log1p(max(0.0, self.volume_24h)),
            -self.latest_observed_at.timestamp(),
            self.nearest_deadline_at.timestamp(),
            self.key,
        )


def load_expectation_facts(
    conn: Any,
    *,
    as_of: datetime,
    limit: int = 5_000,
) -> list[ExpectationFact]:
    """Load source-backed facts without deciding their presentation."""

    as_of = _utc(as_of)
    rows = conn.execute(
        text(
            """
            WITH monitored AS (
              SELECT sm.*,
                     max(sm.monitoring_last_seen_at)
                       OVER (PARTITION BY sm.source_id) AS source_monitoring_at
              FROM source_markets sm
              WHERE sm.status = 'active'
            )
            SELECT ce.id AS topic_id,
                   ce.canonical_question,
                   ce.event_type,
                   ce.resolution_deadline_at,
                   ce.status AS canonical_status,
                   sm.id AS market_id,
                   sm.source_id,
                   source.slug AS source_slug,
                   sm.external_event_id,
                   sm.status AS market_status,
                   sm.volume_24h,
                   sm.volume AS lifetime_volume,
                   sm.liquidity,
                   sm.monitoring_last_seen_at,
                   sm.source_monitoring_at,
                   raw.payload AS raw_payload,
                   event_raw.payload AS event_payload,
                   latest.probability AS current_probability,
                   latest.observed_at AS current_observed_at,
                   latest.spread,
                   latest.data_quality_flags,
                   baseline.probability AS baseline_probability,
                   baseline.observed_at AS baseline_observed_at,
                   recent_claim.id AS recent_claim_id,
                   recent_claim.claim_at AS recent_claim_at
            FROM canonical_expectations ce
            JOIN LATERAL (
              SELECT candidate.*
              FROM monitored candidate
              WHERE candidate.id = ANY(ce.source_market_ids)
              ORDER BY candidate.monitoring_last_seen_at DESC NULLS LAST,
                       candidate.updated_at DESC,
                       candidate.id
              LIMIT 1
            ) sm ON true
            JOIN sources source ON source.id = sm.source_id
            LEFT JOIN raw_source_records raw ON raw.id = sm.raw_source_record_id
            LEFT JOIN LATERAL (
              SELECT event_record.payload
              FROM raw_source_records event_record
              WHERE event_record.source_id = sm.source_id
                AND event_record.record_type = 'event'
                AND event_record.external_id = 'event:' || sm.external_event_id
              ORDER BY event_record.last_seen_at DESC,
                       event_record.ingested_at DESC
              LIMIT 1
            ) event_raw ON sm.external_event_id IS NOT NULL
            LEFT JOIN LATERAL (
              SELECT mo.probability, mo.observed_at, mo.spread,
                     mo.data_quality_flags
              FROM market_observations mo
              WHERE mo.source_market_id = sm.id
                AND mo.probability IS NOT NULL
                AND mo.observed_at <= :as_of
              ORDER BY mo.observed_at DESC
              LIMIT 1
            ) latest ON true
            LEFT JOIN LATERAL (
              SELECT mo.probability, mo.observed_at
              FROM market_observations mo
              WHERE mo.source_market_id = sm.id
                AND mo.probability IS NOT NULL
                AND mo.observed_at <= :as_of - interval '24 hours'
                AND mo.observed_at >= :as_of - interval '30 hours'
              ORDER BY mo.observed_at DESC
              LIMIT 1
            ) baseline ON true
            LEFT JOIN LATERAL (
              SELECT c.id, COALESCE(c.updated_at, c.issued_at) AS claim_at
              FROM section_instances si
              JOIN claims c ON c.id = si.claim_id
              WHERE si.subject_type = 'source_market'
                AND si.subject_id = sm.id
                AND c.status IN ('verified', 'published', 'active')
                AND c.issued_at <= :as_of
                AND c.issued_at >= :as_of - interval '72 hours'
                AND (c.valid_from IS NULL OR c.valid_from <= :as_of)
                AND (c.valid_until IS NULL OR c.valid_until > :as_of)
              ORDER BY COALESCE(c.updated_at, c.issued_at) DESC, c.id
              LIMIT 1
            ) recent_claim ON true
            WHERE ce.status = 'active'
              AND ce.resolution_deadline_at > :as_of
            ORDER BY latest.observed_at DESC NULLS LAST, ce.id
            LIMIT :limit
            """
        ),
        {"as_of": as_of, "limit": max(1, min(10_000, limit))},
    ).mappings()

    return [_fact_from_row(row) for row in rows]


def select_expectation_groups(
    facts: Iterable[ExpectationFact],
    *,
    as_of: datetime,
    page_size: int = 12,
    minimum_surface: str = "explore",
    member_limit: int = 3,
) -> list[ExpectationEventGroup]:
    """Return a stable, event-diverse ordering of public event groups."""

    as_of = _utc(as_of)
    grouped: dict[str, list[ExpectationFact]] = defaultdict(list)
    for fact in eligible_expectation_facts(facts, as_of=as_of):
        grouped[fact.event_key].append(fact)

    groups: list[ExpectationEventGroup] = []
    for key, members in grouped.items():
        group = _build_group(
            key,
            members,
            as_of=as_of,
            member_limit=member_limit,
        )
        if group is not None and group.editorial_scope.allows(minimum_surface):
            groups.append(group)
    groups.sort(key=lambda item: item.sort_key)
    return _diversify_in_pages(groups, page_size=max(1, page_size))


def eligible_expectation_facts(
    facts: Iterable[ExpectationFact],
    *,
    as_of: datetime,
) -> list[ExpectationFact]:
    """Return the public observation inventory before editorial grouping."""

    as_of = _utc(as_of)
    return [fact for fact in facts if _hard_eligible(fact, as_of=as_of)]


def representative_facts(
    facts: Iterable[ExpectationFact],
    *,
    as_of: datetime,
    limit: int,
    minimum_surface: str = "explore",
) -> list[ExpectationFact]:
    groups = select_expectation_groups(
        facts,
        as_of=as_of,
        page_size=limit,
        minimum_surface=minimum_surface,
    )
    return [group.representative for group in groups[:limit]]


def _build_group(
    key: str,
    facts: list[ExpectationFact],
    *,
    as_of: datetime,
    member_limit: int,
) -> ExpectationEventGroup | None:
    ordered = sorted(facts, key=_member_rank)
    latest_observed_at = max(
        fact.current_observed_at for fact in facts if fact.current_observed_at
    )
    nearest_deadline = min(fact.deadline_at for fact in facts)
    volume_24h = sum(max(0.0, fact.volume_24h) for fact in facts)
    moves = [
        fact.delta_24h_percentage_points
        for fact in facts
        if fact.delta_24h_percentage_points is not None
    ]
    largest_move = max(moves, key=abs) if moves else None
    has_recent_claim = any(fact.recent_claim_id for fact in facts)
    days_to_resolution = max(0.0, (nearest_deadline - as_of).total_seconds() / 86_400)

    if not (
        has_recent_claim
        or abs(largest_move or 0.0) >= MIN_SCANNER_MOVE_PP
        or volume_24h >= MIN_PUBLIC_VOLUME_24H
        or days_to_resolution <= NEAR_RESOLUTION_DAYS
    ):
        return None

    members = _select_members(ordered, limit=member_limit)
    representative = _representative(ordered)
    if has_recent_claim:
        priority_class = 0
        selection_reason = "verified_signal"
    elif abs(largest_move or 0.0) >= MIN_FEATURED_MOVE_PP:
        priority_class = 1
        selection_reason = "material_repricing"
    elif abs(largest_move or 0.0) >= MIN_SCANNER_MOVE_PP:
        priority_class = 2
        selection_reason = "observed_move"
    elif days_to_resolution <= NEAR_RESOLUTION_DAYS:
        priority_class = 3
        selection_reason = "near_resolution"
    else:
        priority_class = 4
        selection_reason = "active_event"

    event_title = next((fact.event_title for fact in facts if fact.event_title), None)
    event_slug = next((fact.event_slug for fact in facts if fact.event_slug), None)
    event_type = _mode(fact.event_type for fact in facts) or "general"
    source_member_count = max(
        len(facts),
        max(max(1, fact.source_member_count) for fact in facts),
    )
    is_exclusive = any(fact.is_exclusive_slate for fact in facts)
    editorial_scope = classify_expectation_scope(
        title=representative.title,
        event_title=event_title,
        event_slug=event_slug,
        event_type=event_type,
        tags=(tag for fact in facts for tag in fact.tags),
        deadline_at=representative.deadline_at,
        current_probability=representative.current_probability,
        delta_24h=representative.delta_24h_percentage_points,
        as_of=as_of,
    )
    return ExpectationEventGroup(
        key=key,
        title=event_title or representative.title,
        event_type=event_type,
        external_event_id=representative.external_event_id,
        event_slug=event_slug,
        source_slug=representative.source_slug,
        source_member_count=source_member_count,
        eligible_member_count=len(facts),
        is_exclusive_slate=is_exclusive,
        members=members,
        representative=representative,
        priority_class=priority_class,
        selection_reason=selection_reason,
        volume_24h=round(volume_24h, 2),
        largest_move_pp=largest_move,
        latest_observed_at=latest_observed_at,
        nearest_deadline_at=nearest_deadline,
        editorial_scope=editorial_scope,
    )


def _select_members(
    ordered: list[ExpectationFact],
    *,
    limit: int = 3,
) -> tuple[SelectedExpectationMember, ...]:
    exclusive = any(fact.is_exclusive_slate for fact in ordered)
    leader = max(
        ordered,
        key=lambda fact: (
            fact.current_probability if fact.current_probability is not None else -1,
            fact.market_id,
        ),
    )
    recent = max(
        (fact for fact in ordered if fact.recent_claim_id),
        key=lambda fact: (fact.recent_claim_at or datetime.min.replace(tzinfo=timezone.utc), fact.market_id),
        default=None,
    )
    mover = max(
        (
            fact
            for fact in ordered
            if abs(fact.delta_24h_percentage_points or 0.0) >= MIN_SCANNER_MOVE_PP
        ),
        key=lambda fact: (abs(fact.delta_24h_percentage_points or 0.0), fact.market_id),
        default=None,
    )
    tail = max(
        (fact for fact in ordered if _is_tail_anomaly(fact)),
        key=lambda fact: (abs(fact.delta_24h_percentage_points or 0.0), fact.market_id),
        default=None,
    )
    challenger = None
    if exclusive:
        challengers = [
            fact
            for fact in ordered
            if fact.market_id != leader.market_id
            and fact.current_probability is not None
            and (
                fact.current_probability >= 0.10
                or (
                    leader.current_probability is not None
                    and leader.current_probability - fact.current_probability <= 0.15
                )
            )
        ]
        challenger = max(
            challengers,
            key=lambda fact: (fact.current_probability or 0.0, fact.market_id),
            default=None,
        )
    activity = max(
        ordered,
        key=lambda fact: (
            fact.volume_24h,
            fact.lifetime_volume,
            fact.liquidity,
            fact.market_id,
        ),
    )

    candidates: list[tuple[ExpectationFact | None, str]] = []
    if exclusive:
        candidates.append((leader, "leader"))
    candidates.extend(
        [
            (recent, "latest_verified_signal"),
            (mover, "largest_material_move"),
            (tail, "qualified_tail_anomaly"),
            (challenger, "credible_challenger"),
            (activity, "highest_24h_activity"),
        ]
    )
    if not exclusive:
        candidates.append((leader, "highest_source_probability"))
    candidates.extend((fact, "ranked_representative") for fact in ordered)

    selected: list[SelectedExpectationMember] = []
    seen: set[str] = set()
    for fact, reason in candidates:
        if fact is None or fact.market_id in seen:
            continue
        selected.append(SelectedExpectationMember(fact=fact, selection_reason=reason))
        seen.add(fact.market_id)
        if len(selected) >= max(1, limit):
            break
    return tuple(selected)


def _representative(ordered: list[ExpectationFact]) -> ExpectationFact:
    recent = [fact for fact in ordered if fact.recent_claim_id]
    if recent:
        return max(
            recent,
            key=lambda fact: (
                fact.recent_claim_at or datetime.min.replace(tzinfo=timezone.utc),
                abs(fact.delta_24h_percentage_points or 0.0),
                fact.market_id,
            ),
        )
    movers = [
        fact
        for fact in ordered
        if abs(fact.delta_24h_percentage_points or 0.0) >= MIN_SCANNER_MOVE_PP
    ]
    if movers:
        return max(
            movers,
            key=lambda fact: (
                abs(fact.delta_24h_percentage_points or 0.0),
                fact.volume_24h,
                fact.market_id,
            ),
        )
    return min(ordered, key=_member_rank)


def _hard_eligible(fact: ExpectationFact, *, as_of: datetime) -> bool:
    if fact.canonical_status != "active" or fact.market_status != "active":
        return False
    if fact.deadline_at <= as_of or not fact.is_current_monitoring_cohort:
        return False
    if fact.current_probability is None or not 0 <= fact.current_probability <= 1:
        return False
    if fact.current_observed_at is None:
        return False
    if as_of - fact.current_observed_at > HARD_OBSERVATION_AGE:
        return False
    return not (set(fact.data_quality_flags) & BAD_QUALITY_FLAGS)


def _member_rank(fact: ExpectationFact) -> tuple[Any, ...]:
    has_claim = 0 if fact.recent_claim_id else 1
    move = -abs(fact.delta_24h_percentage_points or 0.0)
    return (
        has_claim,
        move,
        -fact.volume_24h,
        -(fact.current_probability or 0.0),
        fact.market_id,
    )


def _is_tail_anomaly(fact: ExpectationFact) -> bool:
    current = fact.current_probability
    baseline = fact.baseline_probability_24h
    if current is None or baseline is None:
        return False
    if current > TAIL_MAX_PROBABILITY or fact.volume_24h < MIN_PUBLIC_VOLUME_24H:
        return False
    if abs(fact.delta_24h_percentage_points or 0.0) < MIN_SCANNER_MOVE_PP:
        return False
    return abs(_logit(current) - _logit(baseline)) >= TAIL_MIN_LOG_ODDS_MOVE


def _diversify_in_pages(
    groups: list[ExpectationEventGroup],
    *,
    page_size: int,
) -> list[ExpectationEventGroup]:
    remaining = list(groups)
    ordered: list[ExpectationEventGroup] = []
    soft_cap = max(4, math.ceil(page_size * 0.25))
    while remaining:
        counts: Counter[str] = Counter()
        page: list[ExpectationEventGroup] = []
        while remaining and len(page) < page_size:
            within_cap = [
                group
                for group in remaining
                if counts[group.event_type] < soft_cap
            ]
            pool = within_cap or remaining
            candidate = min(
                pool,
                key=lambda group: (
                    group.sort_key[0],
                    group.sort_key[1],
                    counts[group.event_type],
                    *group.sort_key[2:],
                ),
            )
            remaining.remove(candidate)
            page.append(candidate)
            counts[candidate.event_type] += 1
        ordered.extend(page)
    return ordered


def _fact_from_row(row: Any) -> ExpectationFact:
    raw = _object(row["raw_payload"])
    event = _object(row["event_payload"])
    nested_event = _single_nested_event(raw)
    event_id = _text(row["external_event_id"]) or _text(nested_event.get("id"))
    neg_risk_id = _text(raw.get("negRiskMarketID"))
    is_exclusive = bool(
        neg_risk_id
        and (
            raw.get("negRisk") is True
            or event.get("enableNegRisk") is True
            or event.get("negRisk") is True
        )
    )
    event_title = (
        _text(raw.get("eventTitle"))
        or _text(nested_event.get("title"))
        or _text(event.get("title"))
    )
    event_slug = (
        _text(raw.get("eventSlug"))
        or _text(nested_event.get("slug"))
        or _text(event.get("slug"))
    )
    return ExpectationFact(
        topic_id=str(row["topic_id"]),
        market_id=str(row["market_id"]),
        source_id=str(row["source_id"]),
        source_slug=str(row["source_slug"]),
        title=str(row["canonical_question"]),
        event_type=str(row["event_type"] or "general"),
        deadline_at=_utc(row["resolution_deadline_at"]),
        canonical_status=str(row["canonical_status"]),
        market_status=str(row["market_status"]),
        external_event_id=event_id,
        event_title=event_title,
        event_slug=event_slug,
        group_item_title=_text(raw.get("groupItemTitle")),
        neg_risk_market_id=neg_risk_id,
        is_exclusive_slate=is_exclusive,
        source_member_count=_event_member_count(event),
        current_probability=_number(row["current_probability"]),
        current_observed_at=_datetime(row["current_observed_at"]),
        baseline_probability_24h=_number(row["baseline_probability"]),
        baseline_observed_at=_datetime(row["baseline_observed_at"]),
        spread=_number(row["spread"]),
        data_quality_flags=tuple(str(flag) for flag in row["data_quality_flags"] or []),
        volume_24h=_number(row["volume_24h"]) or 0.0,
        lifetime_volume=_number(row["lifetime_volume"]) or 0.0,
        liquidity=_number(row["liquidity"]) or 0.0,
        monitoring_last_seen_at=_datetime(row["monitoring_last_seen_at"]),
        source_monitoring_at=_datetime(row["source_monitoring_at"]),
        recent_claim_id=_text(row["recent_claim_id"]),
        recent_claim_at=_datetime(row["recent_claim_at"]),
        raw_payload=raw,
        tags=_tag_values(raw, nested_event, event),
    )


def _tag_values(*payloads: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for payload in payloads:
        tags = payload.get("tags")
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, dict):
                values.extend(
                    str(value)
                    for key in ("slug", "label")
                    if (value := tag.get(key)) not in (None, "")
                )
            elif tag not in (None, ""):
                values.append(str(tag))
    return tuple(dict.fromkeys(values))


def _event_member_count(event: dict[str, Any]) -> int:
    summaries = event.get("marketSummaries")
    if isinstance(summaries, list):
        active = [
            item
            for item in summaries
            if isinstance(item, dict)
            and item.get("active") is not False
            and item.get("closed") is not True
            and item.get("archived") is not True
        ]
        if active:
            return len(active)
    market_ids = event.get("marketIds")
    return len(market_ids) if isinstance(market_ids, list) else 1


def _single_nested_event(raw: dict[str, Any]) -> dict[str, Any]:
    events = raw.get("events")
    if not isinstance(events, list) or len(events) != 1:
        return {}
    return _object(events[0])


def _mode(values: Iterable[str]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    return min(counts, key=lambda value: (-counts[value], value))


def _logit(value: float) -> float:
    bounded = min(1 - 1e-6, max(1e-6, value))
    return math.log(bounded / (1 - bounded))


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
