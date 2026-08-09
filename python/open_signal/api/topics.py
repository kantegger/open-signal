"""Public topic hubs and the bounded SEO discovery index."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

PUBLIC_CLAIM_STATUSES = ("verified", "published", "active")
PUBLIC_EDITION_STATUSES = ("published", "sparse", "beta", "corrected")


class TopicPagePresenter:
    """Assemble one long-lived Canonical Expectation page."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(self, expectation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            topic = conn.execute(
                text(
                    """
                    SELECT id, canonical_question, event_type, outcome_type,
                           resolution_deadline_at, resolution_authority,
                           resolution_rule_summary, status,
                           canonicalization_version, source_market_ids,
                           created_at, updated_at
                    FROM canonical_expectations
                    WHERE id = :id
                    """
                ),
                {"id": expectation_id},
            ).fetchone()
            if topic is None:
                return None

            market_ids = [str(value) for value in topic[9] or []]
            markets = conn.execute(
                text(
                    """
                    SELECT sm.id, sm.external_market_id, sm.external_event_id,
                           sm.question, sm.description, sm.outcome_labels,
                           sm.ends_at, sm.liquidity, sm.volume, sm.status,
                           latest.probability, latest.observed_at,
                           baseline.probability, baseline.observed_at,
                           raw.payload
                    FROM source_markets sm
                    LEFT JOIN LATERAL (
                      SELECT probability, observed_at
                      FROM market_observations
                      WHERE source_market_id = sm.id
                        AND probability IS NOT NULL
                      ORDER BY observed_at DESC LIMIT 1
                    ) latest ON true
                    LEFT JOIN LATERAL (
                      SELECT probability, observed_at
                      FROM market_observations
                      WHERE source_market_id = sm.id
                        AND probability IS NOT NULL
                        AND observed_at >= now() - interval '24 hours'
                      ORDER BY observed_at ASC LIMIT 1
                    ) baseline ON true
                    LEFT JOIN LATERAL (
                      SELECT payload
                      FROM raw_source_records
                      WHERE source_id = sm.source_id
                        AND external_id = sm.external_market_id
                        AND record_type = 'market'
                      ORDER BY last_seen_at DESC, ingested_at DESC LIMIT 1
                    ) raw ON true
                    WHERE sm.id = ANY(CAST(:market_ids AS uuid[]))
                    ORDER BY sm.volume DESC NULLS LAST, sm.updated_at DESC
                    """
                ),
                {"market_ids": market_ids},
            ).fetchall() if market_ids else []

            signals = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (c.id)
                           c.id, c.public_statement, c.claim_type, c.status,
                           c.confidence, c.confidence_label,
                           c.epistemic_status, c.issued_at, c.updated_at
                    FROM claims c
                    JOIN section_instances si ON si.claim_id = c.id
                    WHERE si.subject_type = 'source_market'
                      AND si.subject_id = ANY(CAST(:market_ids AS uuid[]))
                      AND c.status = ANY(CAST(:statuses AS text[]))
                    ORDER BY c.id, c.issued_at DESC
                    """
                ),
                {
                    "market_ids": market_ids,
                    "statuses": list(PUBLIC_CLAIM_STATUSES),
                },
            ).fetchall() if market_ids else []

        market_payloads = [self._market(row) for row in markets]
        source_event = _source_event(market_payloads)
        return {
            "topic": {
                "id": str(topic[0]),
                "title": topic[1],
                "event_type": topic[2],
                "outcome_type": topic[3],
                "resolution_deadline_at": _iso(topic[4]),
                "resolution_authority": topic[5],
                "resolution_rule_summary": topic[6],
                "status": topic[7],
                "canonicalization_version": topic[8],
                "created_at": _iso(topic[10]),
                "updated_at": _iso(topic[11]),
            },
            "source_event": source_event,
            "markets": market_payloads,
            "signals": [
                {
                    "id": str(row[0]),
                    "public_statement": row[1],
                    "claim_type": row[2],
                    "status": row[3],
                    "confidence": float(row[4]) if row[4] is not None else None,
                    "confidence_label": row[5],
                    "epistemic_status": row[6],
                    "issued_at": _iso(row[7]),
                    "updated_at": _iso(row[8]),
                }
                for row in sorted(signals, key=lambda item: item[7], reverse=True)
            ],
            "method": {
                "summary": (
                    "This page groups verified Claims under one canonical future "
                    "proposition and preserves the source market's resolution rule."
                )
            },
        }

    @staticmethod
    def _market(row: Any) -> dict[str, Any]:
        current = float(row[10]) if row[10] is not None else None
        baseline = float(row[12]) if row[12] is not None else None
        raw = row[14] if isinstance(row[14], dict) else {}
        return {
            "id": str(row[0]),
            "external_market_id": row[1],
            "external_event_id": row[2],
            "question": row[3],
            "description": row[4],
            "outcome_labels": list(row[5] or []),
            "ends_at": _iso(row[6]),
            "liquidity": float(row[7]) if row[7] is not None else None,
            "volume": float(row[8]) if row[8] is not None else None,
            "status": row[9],
            "current_probability": current,
            "current_observed_at": _iso(row[11]),
            "baseline_probability_24h": baseline,
            "baseline_observed_at": _iso(row[13]),
            "delta_24h_percentage_points": (
                round((current - baseline) * 100, 4)
                if current is not None and baseline is not None
                else None
            ),
            "source_url": _polymarket_url(raw),
            "event_title": raw.get("eventTitle"),
            "event_slug": raw.get("eventSlug"),
            "tags": _tags(raw.get("tags")),
        }


class SeoIndexPresenter:
    """Return only durable public URLs suitable for sitemap generation."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(self, *, limit: int = 1000) -> dict[str, list[dict[str, Any]]]:
        bounded = max(1, min(5000, limit))
        with self.engine.connect() as conn:
            claims = conn.execute(
                text(
                    """
                    SELECT id, public_statement, claim_type, desk_id,
                           confidence_label, epistemic_status, status,
                           issued_at, updated_at, valid_until
                    FROM claims
                    WHERE status = ANY(CAST(:statuses AS text[]))
                    ORDER BY issued_at DESC
                    LIMIT :limit
                    """
                ),
                {"statuses": list(PUBLIC_CLAIM_STATUSES), "limit": bounded},
            ).fetchall()
            topics = conn.execute(
                text(
                    """
                    SELECT ce.id, ce.canonical_question, ce.event_type,
                           ce.resolution_deadline_at, ce.status,
                           cardinality(ce.source_market_ids), ce.updated_at,
                           latest.probability, latest.observed_at,
                           baseline.probability, baseline.observed_at
                    FROM canonical_expectations ce
                    LEFT JOIN LATERAL (
                      SELECT mo.source_market_id, mo.probability, mo.observed_at
                      FROM market_observations mo
                      WHERE mo.source_market_id = ANY(ce.source_market_ids)
                        AND mo.probability IS NOT NULL
                      ORDER BY mo.observed_at DESC
                      LIMIT 1
                    ) latest ON true
                    LEFT JOIN LATERAL (
                      SELECT mo.probability, mo.observed_at
                      FROM market_observations mo
                      WHERE mo.source_market_id = latest.source_market_id
                        AND mo.probability IS NOT NULL
                        AND mo.observed_at >= now() - interval '24 hours'
                      ORDER BY mo.observed_at ASC
                      LIMIT 1
                    ) baseline ON true
                    WHERE ce.status = 'active'
                    ORDER BY ce.updated_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": bounded},
            ).fetchall()
            editions = conn.execute(
                text(
                    """
                    SELECT id, edition_date, generated_at, status,
                           included_section_ids, included_claim_ids,
                           correction_count, trigger_type
                    FROM daily_editions
                    WHERE status = ANY(CAST(:statuses AS text[]))
                    ORDER BY generated_at DESC
                    LIMIT 250
                    """
                ),
                {"statuses": list(PUBLIC_EDITION_STATUSES)},
            ).fetchall()
        return {
            "claims": [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "claim_type": row[2],
                    "desk_id": row[3],
                    "confidence_label": row[4],
                    "epistemic_status": row[5],
                    "status": row[6],
                    "published_at": _iso(row[7]),
                    "updated_at": _iso(row[8]),
                    "valid_until": _iso(row[9]),
                }
                for row in claims
            ],
            "topics": [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "event_type": row[2],
                    "resolution_deadline_at": _iso(row[3]),
                    "status": row[4],
                    "source_market_count": row[5],
                    "updated_at": _iso(row[6]),
                    "current_probability": (
                        float(row[7]) if row[7] is not None else None
                    ),
                    "current_observed_at": _iso(row[8]),
                    "delta_24h_percentage_points": (
                        round((float(row[7]) - float(row[9])) * 100, 4)
                        if row[7] is not None and row[9] is not None
                        else None
                    ),
                    "baseline_observed_at": _iso(row[10]),
                }
                for row in topics
            ],
            "editions": [
                {
                    "id": str(row[0]),
                    "edition_date": row[1].isoformat(),
                    "updated_at": _iso(row[2]),
                    "status": row[3],
                    "sections": list(row[4] or []),
                    "claim_count": len(row[5] or []),
                    "correction_count": row[6],
                    "trigger_type": row[7],
                }
                for row in editions
            ],
        }


def _source_event(markets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for market in markets:
        if market.get("external_event_id") or market.get("event_title"):
            return {
                "id": market.get("external_event_id"),
                "title": market.get("event_title"),
                "slug": market.get("event_slug"),
                "tags": market.get("tags") or [],
                "source_url": market.get("source_url"),
            }
    return None


def _polymarket_url(payload: dict[str, Any]) -> str | None:
    event_slug = payload.get("eventSlug")
    market_slug = payload.get("slug")
    if event_slug:
        return f"https://polymarket.com/event/{event_slug}"
    if market_slug:
        return f"https://polymarket.com/market/{market_slug}"
    return None


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        if isinstance(item, dict):
            label = item.get("label") or item.get("slug")
            if label:
                tags.append(str(label))
        elif item:
            tags.append(str(item))
    return tags


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None
