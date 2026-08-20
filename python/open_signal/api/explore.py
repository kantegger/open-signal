"""Curated, event-aware public discovery projection.

The SEO index answers which durable public URLs exist.  Explore answers which
current signals deserve attention.  Keeping these read models separate avoids
using crawlability, ingestion recency, or raw market count as editorial rank.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from open_signal.derived.expectation_selection import (
    SELECTION_VERSION,
    ExpectationEventGroup,
    ExpectationFact,
    eligible_expectation_facts,
    load_expectation_facts,
    select_expectation_groups,
)
from sqlalchemy import text

PUBLIC_CLAIM_STATUSES = ("verified", "published", "active")
DEFAULT_TOPIC_PAGE_SIZE = 12
DEFAULT_SIGNAL_PAGE_SIZE = 24
MAX_PAGE_SIZE = 60
RECENT_SIGNAL_WINDOW = timedelta(days=30)


class ExplorePresenter:
    """Build the bounded discovery surface from public truth objects."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(
        self,
        *,
        as_of: datetime | None = None,
        topic_page: int = 1,
        signal_page: int = 1,
        topic_page_size: int = DEFAULT_TOPIC_PAGE_SIZE,
        signal_page_size: int = DEFAULT_SIGNAL_PAGE_SIZE,
    ) -> dict[str, Any]:
        ranking_as_of = _ranking_time(as_of)
        topic_page_size = _page_size(topic_page_size, DEFAULT_TOPIC_PAGE_SIZE)
        signal_page_size = _page_size(signal_page_size, DEFAULT_SIGNAL_PAGE_SIZE)

        with self.engine.connect() as conn:
            facts = load_expectation_facts(conn, as_of=ranking_as_of)
            public_facts = eligible_expectation_facts(
                facts,
                as_of=ranking_as_of,
            )
            groups = select_expectation_groups(
                public_facts,
                as_of=ranking_as_of,
                page_size=topic_page_size,
            )
            claim_rows, public_record_count = self._claim_rows(
                conn,
                as_of=ranking_as_of,
            )

        topic_slice, topic_meta = _paginate(
            groups,
            page=topic_page,
            page_size=topic_page_size,
        )
        current_signals, current_subject_count = _select_current_signals(
            claim_rows,
            facts=public_facts,
            groups=groups,
        )
        signal_slice, signal_meta = _paginate(
            current_signals,
            page=signal_page,
            page_size=signal_page_size,
        )
        represented = sum(len(group.members) for group in groups)

        return {
            "selection_version": SELECTION_VERSION,
            "ranking_as_of": ranking_as_of.isoformat(),
            "topics": {
                "items": [_serialize_group(group) for group in topic_slice],
                **topic_meta,
                "public_inventory_count": len(public_facts),
                "selected_group_count": len(groups),
                "represented_proposition_count": represented,
                "suppressed_proposition_count": max(
                    0,
                    len(public_facts) - represented,
                ),
            },
            "signals": {
                "items": [_serialize_signal(item) for item in signal_slice],
                **signal_meta,
                "public_record_count": public_record_count,
                "current_record_count": len(claim_rows),
                "current_subject_count": current_subject_count,
                "suppressed_snapshot_count": max(
                    0,
                    len(claim_rows) - len(current_signals),
                ),
            },
        }

    @staticmethod
    def _claim_rows(
        conn: Any,
        *,
        as_of: datetime,
    ) -> tuple[list[dict[str, Any]], int]:
        public_record_count = int(
            conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM claims
                    WHERE status = ANY(CAST(:statuses AS text[]))
                      AND issued_at <= :as_of
                    """
                ),
                {"statuses": list(PUBLIC_CLAIM_STATUSES), "as_of": as_of},
            ).scalar_one()
        )
        rows = conn.execute(
            text(
                """
                SELECT c.id, c.public_statement, c.claim_type, c.desk_id,
                       c.section_id, c.confidence_label, c.epistemic_status,
                       c.status, c.issued_at, c.updated_at, c.valid_until,
                       c.structured_proposition,
                       subject.subject_type, subject.subject_id
                FROM claims c
                LEFT JOIN LATERAL (
                  SELECT si.subject_type, si.subject_id
                  FROM section_instances si
                  WHERE si.claim_id = c.id
                  ORDER BY si.created_at DESC, si.id
                  LIMIT 1
                ) subject ON true
                WHERE c.status = ANY(CAST(:statuses AS text[]))
                  AND c.issued_at <= :as_of
                  AND c.issued_at >= :window_start
                  AND (c.valid_from IS NULL OR c.valid_from <= :as_of)
                  AND (c.valid_until IS NULL OR c.valid_until > :as_of)
                ORDER BY COALESCE(c.updated_at, c.issued_at) DESC, c.id
                LIMIT 5000
                """
            ),
            {
                "statuses": list(PUBLIC_CLAIM_STATUSES),
                "as_of": as_of,
                "window_start": as_of - RECENT_SIGNAL_WINDOW,
            },
        ).mappings()
        return [dict(row) for row in rows], public_record_count


def _select_current_signals(
    rows: list[dict[str, Any]],
    *,
    facts: list[ExpectationFact],
    groups: list[ExpectationEventGroup],
) -> tuple[list[dict[str, Any]], int]:
    latest_by_subject: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _subject_key(row)
        if key not in latest_by_subject:
            latest_by_subject[key] = row

    facts_by_market = {fact.market_id: fact for fact in facts}
    groups_by_key = {group.key: group for group in groups}
    event_signals: dict[str, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []
    for row in latest_by_subject.values():
        if row.get("subject_type") != "source_market":
            selected.append(row)
            continue
        market_id = _text(row.get("subject_id"))
        fact = facts_by_market.get(market_id or "")
        if fact is None or fact.event_key not in groups_by_key:
            continue
        enriched = dict(row)
        enriched["expectation_fact"] = fact
        enriched["expectation_group"] = groups_by_key[fact.event_key]
        current = event_signals.get(fact.event_key)
        if current is None or _signal_rank(enriched) < _signal_rank(current):
            event_signals[fact.event_key] = enriched

    selected.extend(event_signals.values())
    selected.sort(key=_signal_rank)
    return selected, len(latest_by_subject)


def _signal_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    proposition = _object(row.get("structured_proposition"))
    value = _number(proposition.get("value")) or 0.0
    updated = _datetime(row.get("updated_at")) or _datetime(row.get("issued_at"))
    timestamp = updated.timestamp() if updated else 0.0
    return (-timestamp, -abs(value), str(row.get("id") or ""))


def _serialize_group(group: ExpectationEventGroup) -> dict[str, Any]:
    source_url = (
        f"https://polymarket.com/event/{group.event_slug}"
        if group.source_slug == "polymarket-gamma" and group.event_slug
        else None
    )
    return {
        "key": group.key,
        "title": group.title,
        "event_type": group.event_type,
        "external_event_id": group.external_event_id,
        "source_label": _source_name(group.source_slug),
        "source_url": source_url,
        "source_member_count": group.source_member_count,
        "eligible_member_count": group.eligible_member_count,
        "suppressed_member_count": group.suppressed_member_count,
        "unmonitored_member_count": group.unmonitored_member_count,
        "folded_eligible_member_count": group.folded_eligible_member_count,
        "is_exclusive_slate": group.is_exclusive_slate,
        "selection_reason": group.selection_reason,
        "editorial_scope": group.editorial_scope.as_dict(),
        "volume_24h": group.volume_24h,
        "largest_move_24h_percentage_points": group.largest_move_pp,
        "latest_observed_at": group.latest_observed_at.isoformat(),
        "resolution_deadline_at": group.nearest_deadline_at.isoformat(),
        "members": [
            {
                "topic_id": member.fact.topic_id,
                "title": member.fact.title,
                "option_label": member.fact.group_item_title,
                "event_type": member.fact.event_type,
                "current_probability": member.fact.current_probability,
                "baseline_probability_24h": (
                    member.fact.baseline_probability_24h
                ),
                "delta_24h_percentage_points": (
                    member.fact.delta_24h_percentage_points
                ),
                "observed_at": _iso(member.fact.current_observed_at),
                "resolution_deadline_at": member.fact.deadline_at.isoformat(),
                "selection_reason": member.selection_reason,
                "recent_claim_id": member.fact.recent_claim_id,
            }
            for member in group.members
        ],
    }


def _serialize_signal(row: dict[str, Any]) -> dict[str, Any]:
    fact = row.get("expectation_fact")
    group = row.get("expectation_group")
    return {
        "id": str(row["id"]),
        "title": str(row["public_statement"]),
        "claim_type": str(row["claim_type"]),
        "desk_id": str(row["desk_id"]),
        "section_id": str(row["section_id"]),
        "confidence_label": _text(row.get("confidence_label")),
        "epistemic_status": _text(row.get("epistemic_status")),
        "status": str(row["status"]),
        "published_at": _iso(row.get("issued_at")),
        "updated_at": _iso(row.get("updated_at")),
        "valid_until": _iso(row.get("valid_until")),
        "subject_type": _text(row.get("subject_type")),
        "subject_id": _text(row.get("subject_id")),
        "event_key": group.key if isinstance(group, ExpectationEventGroup) else None,
        "event_title": (
            group.title if isinstance(group, ExpectationEventGroup) else None
        ),
        "topic_id": fact.topic_id if isinstance(fact, ExpectationFact) else None,
        "selection_reason": (
            "event_representative"
            if isinstance(group, ExpectationEventGroup)
            else "latest_for_subject"
        ),
    }


def _subject_key(row: dict[str, Any]) -> str:
    subject_type = _text(row.get("subject_type"))
    subject_id = _text(row.get("subject_id"))
    if subject_type and subject_id:
        return f"{row.get('section_id')}:{subject_type}:{subject_id}"
    return f"claim:{row.get('id')}"


def _paginate(
    items: list[Any],
    *,
    page: int,
    page_size: int,
) -> tuple[list[Any], dict[str, int]]:
    page_count = max(1, math.ceil(len(items) / page_size))
    bounded_page = min(max(1, page), page_count)
    start = (bounded_page - 1) * page_size
    return items[start : start + page_size], {
        "page": bounded_page,
        "page_size": page_size,
        "page_count": page_count,
        "total_count": len(items),
    }


def _ranking_time(value: datetime | None) -> datetime:
    now = datetime.now(timezone.utc)
    candidate = _utc(value) if value else now
    candidate = min(candidate, now)
    return candidate.replace(second=0, microsecond=0)


def _page_size(value: int, default: int) -> int:
    if value <= 0:
        return default
    return min(MAX_PAGE_SIZE, value)


def _source_name(slug: str) -> str:
    return {
        "polymarket-gamma": "Polymarket Gamma",
    }.get(slug, slug.replace("-", " ").title())


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
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    parsed = _datetime(value)
    return parsed.isoformat() if parsed else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
