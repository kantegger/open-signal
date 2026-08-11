"""Snapshot-bound public context for the rolling front page.

Render Plans carry Open Signal's selected editorial judgments.  This module
captures the larger, explicitly typed information field around those
judgments: verified Claim records, deterministic source observations, and
screening/watch items.  The captured JSON is stored inside ``edition_payload``
so every public number and micro-chart belongs to the same immutable snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from open_signal.derived.expectation_selection import (
    ExpectationFact,
    eligible_expectation_facts,
    load_expectation_facts,
    representative_facts,
    select_expectation_groups,
)
from open_signal.derived.series_contract import market_series_snapshot
from open_signal.research.candidates import CANDIDATE_VERSION
from open_signal.research.publication import select_public_research_items

CONTEXT_VERSION = "1.5.0"
CLAIM_LIMIT = 24
EXPECTATION_LIMIT = 12
RULE_LIMIT = 8
RESEARCH_LIMIT = 6
RESEARCH_SCAN_LIMIT = 500


class PublicationContextBuilder:
    """Capture typed, public-safe context using an existing transaction."""

    def capture(self, conn: Any, *, captured_at: datetime) -> dict[str, Any]:
        captured_at = _utc(captured_at)
        expectation_facts = load_expectation_facts(conn, as_of=captured_at)
        claims, claim_total = self._claims(
            conn,
            captured_at=captured_at,
            expectation_facts=expectation_facts,
        )
        expectations = self._expectations(
            conn,
            captured_at=captured_at,
            facts=expectation_facts,
        )
        rules = self._rules(conn, captured_at=captured_at)
        research, research_total = self._research(conn, captured_at=captured_at)
        research_fingerprint = _research_fingerprint(research, research_total)
        coverage = self._coverage(conn, captured_at=captured_at)
        return {
            "version": CONTEXT_VERSION,
            "snapshot_bound": True,
            "captured_at": captured_at.isoformat(),
            "research_fingerprint": research_fingerprint,
            "counts": {
                "verified_claims": claim_total,
                "expectation_observations": len(expectations),
                "rules_tracked": len(rules),
                "research_screening": research_total,
                "source_records_24h": sum(
                    int(item["records_24h"]) for item in coverage
                ),
            },
            "claims": claims,
            "expectations": expectations,
            "rules": rules,
            "research": research,
            "coverage": coverage,
        }

    def _claims(
        self,
        conn: Any,
        *,
        captured_at: datetime,
        expectation_facts: list[ExpectationFact] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = conn.execute(
            text(
                """
                WITH ranked AS (
                  SELECT c.id, c.section_id, c.claim_type, c.public_statement,
                         c.structured_proposition, c.confidence,
                         c.confidence_label, c.epistemic_status, c.status,
                         c.issued_at, c.updated_at, c.valid_until,
                         eb.primary_evidence, eb.supporting_evidence,
                         subject.subject_type, subject.subject_id,
                         row_number() OVER (
                           PARTITION BY concat(
                             c.section_id, ':',
                             COALESCE(subject.subject_type, 'claim'), ':',
                             COALESCE(subject.subject_id::text, c.id::text)
                           )
                           ORDER BY COALESCE(c.updated_at, c.issued_at) DESC,
                                    c.id
                         ) AS subject_rank
                  FROM claims c
                  LEFT JOIN evidence_bundles eb
                    ON eb.id = c.evidence_bundle_id
                  LEFT JOIN LATERAL (
                    SELECT si.subject_type, si.subject_id
                    FROM section_instances si
                    WHERE si.claim_id = c.id
                    ORDER BY si.created_at DESC, si.id
                    LIMIT 1
                  ) subject ON true
                  WHERE c.status IN ('verified', 'published', 'active')
                    AND c.issued_at <= :captured_at
                    AND (c.valid_from IS NULL OR c.valid_from <= :captured_at)
                    AND (c.valid_until IS NULL OR c.valid_until > :captured_at)
                )
                SELECT id, section_id, claim_type, public_statement,
                       structured_proposition, confidence, confidence_label,
                       epistemic_status, status, issued_at, updated_at,
                       valid_until, primary_evidence, supporting_evidence,
                       subject_type, subject_id
                FROM ranked
                WHERE subject_rank = 1
                ORDER BY COALESCE(updated_at, issued_at) DESC, id
                LIMIT :limit
                """
            ),
            {"captured_at": captured_at, "limit": 5000},
        ).fetchall()
        visible_rows = rows
        if expectation_facts is not None:
            eligible = eligible_expectation_facts(
                expectation_facts,
                as_of=captured_at,
            )
            selected_event_keys = {
                group.key
                for group in select_expectation_groups(
                    eligible,
                    as_of=captured_at,
                    page_size=CLAIM_LIMIT,
                    minimum_surface="live_feed",
                )
            }
            event_by_market = {
                fact.market_id: fact.event_key
                for fact in eligible
                if fact.event_key in selected_event_keys
            }
            visible_rows = []
            used_events: set[str] = set()
            for row in rows:
                if row[14] != "source_market":
                    visible_rows.append(row)
                    continue
                event_key = event_by_market.get(str(row[15]))
                if event_key is None or event_key in used_events:
                    continue
                visible_rows.append(row)
                used_events.add(event_key)

        claims: list[dict[str, Any]] = []
        for row in visible_rows[:CLAIM_LIMIT]:
            proposition = _object(row[4])
            direction, change = _claim_change(proposition)
            primary = _list(row[12])
            supporting = _list(row[13])
            claims.append(
                {
                    "id": str(row[0]),
                    "section_id": row[1],
                    "claim_type": row[2],
                    "statement": row[3],
                    "direction": direction,
                    "change": change,
                    "confidence": _number(row[5]),
                    "confidence_label": row[6],
                    "epistemic_status": row[7],
                    "status": row[8],
                    "source_label": _claim_source(row[1], proposition),
                    "evidence_count": len(primary) + len(supporting),
                    "issued_at": _iso(row[9]),
                    "updated_at": _iso(row[10]),
                    "valid_until": _iso(row[11]),
                }
            )
        return claims, len(visible_rows)

    def _expectations(
        self,
        conn: Any,
        *,
        captured_at: datetime,
        facts: list[ExpectationFact] | None = None,
    ) -> list[dict[str, Any]]:
        if facts is None:
            facts = load_expectation_facts(conn, as_of=captured_at)
        selected = representative_facts(
            facts,
            as_of=captured_at,
            limit=EXPECTATION_LIMIT,
            minimum_surface="live_feed",
        )
        observations: list[dict[str, Any]] = []
        for fact in selected:
            series_snapshot = self._market_series(
                conn,
                source_market_id=fact.market_id,
                captured_at=captured_at,
            )
            observations.append(
                {
                    "id": fact.topic_id,
                    "title": fact.title,
                    "event_title": fact.event_title,
                    "event_key": fact.event_key,
                    "event_type": fact.event_type,
                    "resolution_deadline_at": fact.deadline_at.isoformat(),
                    "status": fact.canonical_status,
                    "updated_at": _iso(fact.current_observed_at),
                    "source_market_count": 1,
                    "source_market_status": fact.market_status,
                    "source_label": _source_name(fact.source_slug),
                    "current_probability": fact.current_probability,
                    "current_observed_at": _iso(fact.current_observed_at),
                    "baseline_probability_24h": (
                        fact.baseline_probability_24h
                    ),
                    "baseline_observed_at": _iso(fact.baseline_observed_at),
                    "delta_24h_percentage_points": (
                        fact.delta_24h_percentage_points
                    ),
                    "series": series_snapshot["points"],
                    "series_quality": series_snapshot["quality"],
                }
            )
        return observations

    def _market_series(
        self,
        conn: Any,
        *,
        source_market_id: Any,
        captured_at: datetime,
    ) -> dict[str, Any]:
        if source_market_id is None:
            return market_series_snapshot([], captured_at=captured_at)
        rows = conn.execute(
            text(
                """
                SELECT observed_at, probability
                FROM market_observations
                WHERE source_market_id = :market_id
                  AND probability IS NOT NULL
                  AND observed_at <= :captured_at
                  AND observed_at >= :captured_at - interval '7 days'
                ORDER BY observed_at
                """
            ),
            {
                "market_id": source_market_id,
                "captured_at": captured_at,
            },
        ).fetchall()
        return market_series_snapshot(
            [(row[0], row[1]) for row in rows],
            captured_at=captured_at,
        )

    def _rules(
        self, conn: Any, *, captured_at: datetime
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            text(
                """
                SELECT cr.id, cr.title, cr.rule_type, cr.previous_state,
                       cr.current_state, cr.announced_at, cr.adopted_at,
                       cr.effective_at, cr.enforcement_at, cr.updated_at,
                       authority.canonical_name, jurisdiction.canonical_name,
                       transition.from_state, transition.to_state,
                       transition.occurred_at, transition.transition_confidence
                FROM canonical_rules cr
                LEFT JOIN canonical_entities authority
                  ON authority.id = cr.issuing_authority_id
                LEFT JOIN canonical_entities jurisdiction
                  ON jurisdiction.id = cr.jurisdiction_id
                LEFT JOIN LATERAL (
                  SELECT rt.from_state, rt.to_state, rt.occurred_at,
                         rt.transition_confidence
                  FROM rule_transitions rt
                  WHERE rt.canonical_rule_id = cr.id
                    AND rt.status IN ('verified', 'confirmed', 'active')
                    AND rt.detected_at <= :captured_at
                  ORDER BY rt.detected_at DESC
                  LIMIT 1
                ) transition ON true
                WHERE cr.status = 'active'
                  AND cr.created_at <= :captured_at
                ORDER BY COALESCE(transition.occurred_at, cr.updated_at) DESC
                LIMIT :limit
                """
            ),
            {"captured_at": captured_at, "limit": RULE_LIMIT},
        ).fetchall()
        return [
            {
                "id": str(row[0]),
                "title": row[1],
                "rule_type": row[2],
                "previous_state": row[12] or row[3],
                "current_state": row[13] or row[4],
                "announced_at": _iso(row[5]),
                "adopted_at": _iso(row[6]),
                "effective_at": _iso(row[7]),
                "enforcement_at": _iso(row[8]),
                "updated_at": _iso(row[9]),
                "authority": row[10],
                "jurisdiction": row[11],
                "transition_at": _iso(row[14]),
                "transition_confidence": _number(row[15]),
                "source_label": "Federal Register",
            }
            for row in rows
        ]

    def _research(
        self, conn: Any, *, captured_at: datetime
    ) -> tuple[list[dict[str, Any]], int]:
        rows = conn.execute(
            text(
                """
                SELECT id, candidate_type, derived_metrics, status, created_at,
                       observation_window_start, observation_window_end,
                       baseline_definition, evidence_relation_ids
                FROM research_signal_candidates
                WHERE candidate_generator_version = :candidate_version
                  AND status IN ('generated', 'shadow_investigation')
                  AND created_at <= :captured_at
                  AND created_at >= :captured_at - interval '30 days'
                ORDER BY (status = 'shadow_investigation') DESC,
                         created_at DESC, id
                LIMIT :limit
                """
            ),
            {
                "captured_at": captured_at,
                "candidate_version": CANDIDATE_VERSION,
                "limit": RESEARCH_SCAN_LIMIT,
            },
        ).fetchall()
        candidates = [
            {
                "id": str(row[0]),
                "candidate_type": row[1],
                "derived_metrics": _object(row[2]),
                "status": row[3],
                "created_at": row[4],
                "observation_window_start": row[5],
                "observation_window_end": row[6],
                "baseline_definition": row[7],
                "evidence_relation_ids": list(row[8] or []),
            }
            for row in rows
        ]
        return select_public_research_items(
            candidates,
            limit=RESEARCH_LIMIT,
        )

    def research_fingerprint(self, conn: Any, *, captured_at: datetime) -> str:
        """Fingerprint the current public-qualified Research screening set."""

        items, eligible_total = self._research(
            conn,
            captured_at=_utc(captured_at),
        )
        return _research_fingerprint(items, eligible_total)

    def _coverage(
        self, conn: Any, *, captured_at: datetime
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            text(
                """
                SELECT s.slug, count(r.id),
                       count(r.id) FILTER (
                         WHERE r.ingested_at >= :captured_at - interval '24 hours'
                           AND r.ingested_at <= :captured_at
                       ),
                       max(r.ingested_at)
                FROM sources s
                LEFT JOIN raw_source_records r
                  ON r.source_id = s.id
                 AND r.ingested_at <= :captured_at
                GROUP BY s.slug
                HAVING count(r.id) > 0
                ORDER BY count(r.id) DESC, s.slug
                """
            ),
            {"captured_at": captured_at},
        ).fetchall()
        return [
            {
                "source_slug": row[0],
                "source_label": _source_name(row[0]),
                "records_total": int(row[1]),
                "records_24h": int(row[2]),
                "latest_ingested_at": _iso(row[3]),
            }
            for row in rows
        ]


def empty_publication_context(*, captured_at: str | None = None) -> dict[str, Any]:
    """Stable presenter fallback for snapshots created before this contract."""

    return {
        "version": CONTEXT_VERSION,
        "snapshot_bound": False,
        "captured_at": captured_at,
        "research_fingerprint": _research_fingerprint([], 0),
        "counts": {
            "verified_claims": 0,
            "expectation_observations": 0,
            "rules_tracked": 0,
            "research_screening": 0,
            "source_records_24h": 0,
        },
        "claims": [],
        "expectations": [],
        "rules": [],
        "research": [],
        "coverage": [],
    }


def _research_fingerprint(
    items: list[dict[str, Any]],
    eligible_total: int,
) -> str:
    payload = {
        "candidate_generator_version": CANDIDATE_VERSION,
        "eligible_total": eligible_total,
        "items": items,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _claim_change(proposition: dict[str, Any]) -> tuple[str, str | None]:
    operator = str(proposition.get("operator") or "").lower()
    baseline = _object(proposition.get("baseline"))
    value = _number(proposition.get("value"))
    if operator in {"increased", "increase", "rose", "higher"}:
        direction = "up"
    elif operator in {"decreased", "decrease", "fell", "lower"}:
        direction = "down"
    else:
        direction = "neutral"
    delta = _number(baseline.get("delta_24h"))
    if delta is None and value is not None and direction != "neutral":
        delta = value if direction == "up" else -abs(value)
    if delta is not None:
        return direction, f"{delta:+.1f}pp"
    previous = baseline.get("previous_state")
    current = proposition.get("current_state") or _object(
        proposition.get("qualifiers")
    ).get("current_state")
    if previous and current:
        return "neutral", f"{previous} → {current}"
    return direction, None


def _claim_source(section_id: str, proposition: dict[str, Any]) -> str:
    qualifiers = _object(proposition.get("qualifiers"))
    if section_id == "rules-moved":
        return str(qualifiers.get("authority") or "Federal Register")
    if section_id == "research-frontier":
        return "OpenAlex / ClinicalTrials.gov"
    return "Polymarket Gamma"


def _source_name(slug: Any) -> str:
    names = {
        "polymarket-gamma": "Polymarket",
        "federal-register": "Federal Register",
        "openalex": "OpenAlex",
        "clinicaltrials-gov": "ClinicalTrials.gov",
    }
    key = str(slug or "")
    return names.get(key, key.replace("-", " ").title() or "Source")


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    return str(value) if value else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
