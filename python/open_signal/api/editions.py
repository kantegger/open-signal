"""Read-only presenters for the rolling public front page."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from open_signal.composer.edition_writer import PUBLICATION_CHANNEL, SLOT_ORDER
from open_signal.composer.publication_context import empty_publication_context
from open_signal.sources.registry import Registry
from sqlalchemy import text


class EditionArchivePresenter:
    """Keyset-paginated index of every Edition that has ever been public."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        year: int | None = None,
        section: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        if year is not None and not 2000 <= year <= 2100:
            raise ValueError("year must be between 2000 and 2100")
        section = (section.strip() or None) if section else None
        status = (status.strip() or None) if status else None
        if section and len(section) > 80:
            raise ValueError("section filter is too long")

        clauses = ["e.first_published_at IS NOT NULL"]
        params: dict[str, Any] = {"row_limit": bounded_limit + 1}
        if year is not None:
            clauses.append("e.edition_date >= :year_start")
            clauses.append("e.edition_date < :year_end")
            params["year_start"] = date(year, 1, 1)
            params["year_end"] = date(year + 1, 1, 1)
        if section:
            clauses.append(":section = ANY(e.included_section_ids)")
            params["section"] = section
        if status:
            clauses.append("e.status = :status")
            params["status"] = status

        filter_clause = " AND ".join(clauses)
        page_clause = ""
        if cursor:
            cursor_time, cursor_id = _decode_archive_cursor(cursor)
            page_clause = (
                " AND (e.generated_at < :cursor_time OR "
                "(e.generated_at = :cursor_time AND e.id < :cursor_id))"
            )
            params["cursor_time"] = cursor_time
            params["cursor_id"] = cursor_id

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT e.id, e.edition_date, e.generated_at, e.status,
                           e.included_section_ids,
                           cardinality(e.included_claim_ids),
                           e.correction_count, e.trigger_type,
                           e.first_published_at, e.record_class, e.payload_hash,
                           lifecycle.event_count,
                           lifecycle.latest_event_type,
                           lifecycle.latest_event_at,
                           e.included_claim_ids,
                           prior_edition.included_claim_ids
                    FROM daily_editions e
                    LEFT JOIN LATERAL (
                      SELECT count(*) AS event_count,
                             (array_agg(
                               ev.event_type ORDER BY ev.sequence_no DESC
                             ))[1] AS latest_event_type,
                             (array_agg(
                               ev.created_at ORDER BY ev.sequence_no DESC
                             ))[1] AS latest_event_at
                      FROM edition_events ev
                      WHERE ev.edition_id = e.id
                    ) lifecycle ON true
                    LEFT JOIN LATERAL (
                      SELECT prior.included_claim_ids
                      FROM daily_editions prior
                      WHERE prior.first_published_at IS NOT NULL
                        AND (
                          prior.generated_at < e.generated_at OR
                          (prior.generated_at = e.generated_at AND prior.id < e.id)
                        )
                      ORDER BY prior.generated_at DESC, prior.id DESC
                      LIMIT 1
                    ) prior_edition ON true
                    WHERE {filter_clause}{page_clause}
                    ORDER BY e.generated_at DESC, e.id DESC
                    LIMIT :row_limit
                    """
                ),
                params,
            ).fetchall()
            total_count = conn.execute(
                text(
                    f"SELECT count(*) FROM daily_editions e "
                    f"WHERE {filter_clause}"
                ),
                params,
            ).scalar_one()
            facets = conn.execute(
                text(
                    """
                    SELECT
                      ARRAY(
                        SELECT DISTINCT EXTRACT(YEAR FROM edition_date)::int
                        FROM daily_editions
                        WHERE first_published_at IS NOT NULL
                        ORDER BY 1 DESC
                      ),
                      ARRAY(
                        SELECT DISTINCT section_id
                        FROM daily_editions
                        CROSS JOIN LATERAL
                          unnest(included_section_ids) AS sections(section_id)
                        WHERE first_published_at IS NOT NULL
                        ORDER BY 1
                      ),
                      ARRAY(
                        SELECT DISTINCT status
                        FROM daily_editions
                        WHERE first_published_at IS NOT NULL
                        ORDER BY 1
                      )
                    """
                )
            ).one()

        has_more = len(rows) > bounded_limit
        visible_rows = rows[:bounded_limit]
        next_cursor = None
        if has_more and visible_rows:
            last = visible_rows[-1]
            next_cursor = _encode_archive_cursor(last[2], last[0])

        return {
            "items": [
                {
                    "id": str(row[0]),
                    "edition_date": row[1].isoformat(),
                    "generated_at": _iso(row[2]),
                    "status": row[3],
                    "sections": list(row[4] or []),
                    "claim_count": int(row[5] or 0),
                    "correction_count": int(row[6] or 0),
                    "trigger_type": row[7],
                    "first_published_at": _iso(row[8]),
                    "record_class": row[9],
                    "payload_hash": row[10],
                    "event_count": int(row[11] or 0),
                    "latest_event_type": row[12],
                    "latest_event_at": _iso(row[13]),
                    "claim_diff": _claim_diff(row[14], row[15]),
                }
                for row in visible_rows
            ],
            "next_cursor": next_cursor,
            "has_more": has_more,
            "page_size": bounded_limit,
            "total_count": int(total_count),
            "filters": {
                "year": year,
                "section": section,
                "status": status,
            },
            "facets": {
                "years": list(facets[0] or []),
                "sections": list(facets[1] or []),
                "statuses": list(facets[2] or []),
            },
        }


def _encode_archive_cursor(generated_at: datetime, edition_id: UUID) -> str:
    payload = json.dumps(
        {"generated_at": generated_at.isoformat(), "id": str(edition_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_archive_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        if not cursor or len(cursor) > 512:
            raise ValueError
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]))
        edition_id = UUID(str(payload["id"]))
        if generated_at.tzinfo is None:
            raise ValueError
        return generated_at, edition_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("invalid archive cursor") from exc


def _claim_diff(
    current_claim_ids: Any,
    previous_claim_ids: Any,
) -> dict[str, int] | None:
    """Compare immutable Claim membership without reinterpreting either Edition."""

    if previous_claim_ids is None:
        return None
    current = {str(claim_id) for claim_id in (current_claim_ids or [])}
    previous = {str(claim_id) for claim_id in (previous_claim_ids or [])}
    return {
        "added": len(current - previous),
        "retained": len(current & previous),
        "retired": len(previous - current),
    }


class FrontPagePresenter:
    """Assemble validated Render Plans without reinterpreting their Claims."""

    def __init__(self, engine: Any, registry: Registry | None = None) -> None:
        self.engine = engine
        self.registry = registry or Registry.load()

    def build(
        self,
        *,
        locale: str = "en",
        edition_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            if edition_id:
                edition = conn.execute(
                    text(
                        """
                        SELECT e.id, e.edition_date, e.generated_at, e.status,
                               e.included_section_ids, e.composer_version,
                               e.correction_count, e.trigger_type,
                               e.supersedes_edition_id, e.freshness_summary,
                               e.published_at, e.policy_version, e.edition_payload,
                               CASE
                                 WHEN pc.current_edition_id = e.id
                                 THEN pc.previous_edition_id
                                 ELSE e.supersedes_edition_id
                               END,
                               CASE
                                 WHEN pc.current_edition_id = e.id
                                 THEN pc.updated_at
                                 ELSE e.generated_at
                               END,
                               (pc.current_edition_id = e.id)
                        FROM daily_editions e
                        LEFT JOIN publication_channels pc
                          ON pc.id = :channel
                        WHERE e.id = :edition
                          AND e.first_published_at IS NOT NULL
                        """
                    ),
                    {"channel": PUBLICATION_CHANNEL, "edition": edition_id},
                ).fetchone()
            else:
                edition = conn.execute(
                    text(
                        """
                        SELECT e.id, e.edition_date, e.generated_at, e.status,
                               e.included_section_ids, e.composer_version,
                               e.correction_count, e.trigger_type,
                               e.supersedes_edition_id, e.freshness_summary,
                               e.published_at, e.policy_version, e.edition_payload,
                               pc.previous_edition_id, pc.updated_at, true
                        FROM publication_channels pc
                        JOIN daily_editions e ON e.id = pc.current_edition_id
                        WHERE pc.id = :channel
                        """
                    ),
                    {"channel": PUBLICATION_CHANNEL},
                ).fetchone()
                if edition is None:
                    edition = conn.execute(
                        text(
                            """
                            SELECT id, edition_date, generated_at, status,
                                   included_section_ids, composer_version,
                                   correction_count, trigger_type,
                                   supersedes_edition_id, freshness_summary,
                                   published_at, policy_version, edition_payload,
                                   NULL, generated_at, false
                            FROM daily_editions
                            WHERE first_published_at IS NOT NULL
                            ORDER BY generated_at DESC LIMIT 1
                            """
                        )
                    ).fetchone()
            if edition is None:
                return None

            rows = conn.execute(
                text(
                    """
                    SELECT rp.id, rp.slot_id, rp.position,
                           rp.section_instance_id, rp.claim_ids,
                           rp.component_id, rp.component_version,
                           rp.component_variant, rp.headline, rp.dek,
                           rp.display_fields, rp.hidden_detail_fields,
                           rp.visual_priority, rp.mobile_priority,
                           rp.generated_by, rp.data_as_of, rp.assessed_at,
                           rp.materially_updated_at, rp.freshness_state,
                           rp.expires_at, c.id, c.public_statement,
                           c.structured_proposition, c.confidence,
                           c.confidence_label, c.epistemic_status, c.status,
                           c.desk_id, c.section_id, c.capability_id,
                           c.claim_type, c.issued_at, c.updated_at,
                           eb.primary_evidence, eb.supporting_evidence,
                           eb.counter_evidence, eb.source_coverage,
                           eb.unresolved_questions, eb.known_limitations,
                           eb.snapshot_hash, ce.id, ce.canonical_question,
                           ce.event_type, ce.resolution_deadline_at
                    FROM render_plans rp
                    LEFT JOIN claims c ON c.id = rp.claim_ids[1]
                    LEFT JOIN section_instances si
                      ON si.id = rp.section_instance_id
                    LEFT JOIN evidence_bundles eb
                      ON eb.id = COALESCE(rp.evidence_bundle_id, c.evidence_bundle_id)
                    LEFT JOIN LATERAL (
                      SELECT id, canonical_question, event_type,
                             resolution_deadline_at
                      FROM canonical_expectations
                      WHERE si.subject_type = 'source_market'
                        AND source_market_ids @> ARRAY[si.subject_id]::uuid[]
                      ORDER BY updated_at DESC LIMIT 1
                    ) ce ON true
                    WHERE rp.edition_id = :edition
                    ORDER BY rp.slot_id, rp.position, rp.visual_priority
                    """
                ),
                {"edition": edition[0]},
            ).fetchall()

            archive = conn.execute(
                text(
                    """
                    SELECT id, edition_date, generated_at, status,
                           included_section_ids, included_claim_ids,
                           correction_count, trigger_type
                    FROM daily_editions
                    WHERE first_published_at IS NOT NULL
                    ORDER BY generated_at DESC
                    LIMIT 13
                    """
                )
            ).fetchall()

        slot_items: dict[str, list[dict[str, Any]]] = {slot: [] for slot in SLOT_ORDER}
        composed_at = _iso(edition[2])
        for row in rows:
            item = self._item(row, locale=locale, composed_at=composed_at)
            slot_items.setdefault(item["slot_id"], []).append(item)

        slots = []
        by_type = {slot.type: slot for slot in self.registry.slots()}
        for slot_type in SLOT_ORDER:
            definition = by_type[slot_type]
            slots.append(
                {
                    "id": definition.id,
                    "type": definition.type,
                    "size": definition.size,
                    "required": definition.required,
                    "collapsible": definition.collapsible,
                    "desktop_order": definition.desktop_order,
                    "mobile_order": definition.mobile_order,
                    "items": slot_items.get(slot_type, []),
                }
            )

        freshness = _object(edition[9])
        edition_payload = _object(edition[12])
        publication_context = _publication_context(
            edition_payload.get("publication_context"),
            captured_at=composed_at,
        )
        return {
            "snapshot": {
                "id": str(edition[0]),
                "edition_date": edition[1].isoformat(),
                "composed_at": composed_at,
                "published_at": _iso(edition[10]) or composed_at,
                "status": edition[3],
                "trigger_type": edition[7],
                "supersedes_edition_id": str(edition[8]) if edition[8] else None,
                "previous_edition_id": str(edition[13]) if edition[13] else None,
                "composer_version": edition[5],
                "policy_version": edition[11],
                "correction_count": edition[6],
                "is_current": bool(edition[15]),
                "publication_mode": "rolling_snapshot",
            },
            "freshness": {
                **freshness,
                "last_successful_compile_at": composed_at,
                "channel_updated_at": _iso(edition[14]),
            },
            "sections": list(edition[4] or []),
            "publication_context": publication_context,
            "slots": slots,
            "archive": [
                {
                    "id": str(row[0]),
                    "edition_date": row[1].isoformat(),
                    "composed_at": _iso(row[2]),
                    "status": row[3],
                    "sections": list(row[4] or []),
                    "claim_count": len(row[5] or []),
                    "correction_count": row[6],
                    "trigger_type": row[7],
                    "claim_diff": _claim_diff(
                        row[5],
                        archive[index + 1][5]
                        if index + 1 < len(archive)
                        else None,
                    ),
                }
                for index, row in enumerate(archive[:12])
            ],
            "method": {
                "summary": (
                    "Open Signal separates observation, analysis, and assessment; "
                    "publishes verified judgments alongside explicitly labeled source "
                    "observations and watch items; and preserves every snapshot."
                ),
                "composer_version": edition[5],
                "policy_version": edition[11],
            },
            "system_state": {
                "status": "operational",
                "publication_channel": PUBLICATION_CHANNEL,
                "last_checked_at": _iso(edition[14]) or composed_at,
            },
            "locale": {
                "requested": locale,
                "published": "en",
                "fallback_used": locale != "en",
                "translation_provenance": None,
            },
        }

    def legacy_latest(self, *, locale: str = "en") -> dict[str, Any] | None:
        """Compatibility view for clients built before Render Plan delivery."""
        page = self.build(locale=locale)
        if page is None:
            return None
        seen: set[str] = set()
        cards: list[dict[str, Any]] = []
        for slot in page["slots"]:
            for item in slot["items"]:
                claim_id = item["trust"].get("claim_id")
                if not claim_id or claim_id in seen:
                    continue
                seen.add(claim_id)
                fields = item["display_fields"]
                cards.append(
                    {
                        "id": claim_id,
                        "headline": item["headline"],
                        "summary": fields.get("observation") or item.get("dek") or "",
                        "trend": fields.get("trend") or _derive_trend(fields),
                        "probability": fields.get("probability")
                        or fields.get("current_probability"),
                        "confidence": item["trust"].get("confidence"),
                        "confidence_label": item["trust"].get("confidence_label"),
                        "source_label": item["trust"].get("source_label"),
                        "section": item.get("section_id"),
                        "tags": [
                            str(item.get("section_id") or "signal")
                            .replace("-", " ")
                            .title(),
                            str(item["trust"].get("claim_type") or "claim")
                            .replace("_", " ")
                            .title(),
                        ],
                        "issued_at": item["times"].get("assessed_at"),
                    }
                )
        return {
            "id": page["snapshot"]["id"],
            "edition_date": page["snapshot"]["edition_date"],
            "generated_at": page["snapshot"]["composed_at"],
            "sections": page["sections"],
            "claim_ids": list(seen),
            "edition_payload": {"publication_mode": "rolling_snapshot"},
            "cards": cards,
        }

    def _item(
        self, row: Any, *, locale: str, composed_at: str | None
    ) -> dict[str, Any]:
        fields = _object(row[10])
        hidden = _object(row[11])
        proposition = _object(row[22])
        localized, published_locale = _localized(proposition, locale)
        for key in (
            "headline",
            "observation",
            "analysis",
            "assessment",
            "probability",
            "trend",
        ):
            if localized.get(key) is not None and fields.get(key) is None:
                fields[key] = localized[key]
        if (
            fields.get("current_probability") is None
            and localized.get("probability") is not None
        ):
            fields["current_probability"] = localized["probability"]

        definition = self.registry.component(row[5])
        family = definition.family_id if definition else _family(row[5])
        primary = _list(row[33])
        supporting = _list(row[34])
        counter = _list(row[35])
        evidence_count = len(primary) + len(supporting)
        source_label = (
            fields.get("source_name")
            or fields.get("authority")
            or fields.get("source")
            or row[27]
            or "Open Signal"
        )
        headline = fields.get("headline") or row[8]
        if headline in {"Signal", "Verified signal"} and localized.get("headline"):
            headline = localized["headline"]
        return {
            "id": str(row[0]),
            "slot_id": row[1],
            "position": row[2],
            "section_instance_id": str(row[3]) if row[3] else None,
            "section_id": row[28] or _section_from_component(row[5]),
            "claim_ids": [str(value) for value in row[4] or []],
            "component_id": row[5],
            "component_family": family,
            "component_version": row[6],
            "component_variant": row[7],
            "headline": str(headline or row[21] or "Verified signal"),
            "dek": row[9],
            "display_fields": fields,
            "hidden_detail_fields": hidden,
            "visual_priority": row[12],
            "mobile_priority": row[13],
            "generated_by": row[14],
            "freshness_state": row[18],
            "trust": {
                "claim_id": str(row[20]) if row[20] else None,
                "claim_status": row[26],
                "claim_type": row[30],
                "confidence": float(row[23]) if row[23] is not None else None,
                "confidence_label": row[24],
                "epistemic_status": row[25],
                "source_label": str(source_label),
                "evidence_count": evidence_count,
                "counterevidence_count": len(counter),
                "snapshot_hash": row[39],
            },
            "times": {
                "data_as_of": _iso(row[15])
                or fields.get("data_as_of")
                or fields.get("updated_at"),
                "assessed_at": _iso(row[16]) or _iso(row[31]),
                "composed_at": composed_at,
                "materially_updated_at": _iso(row[17]) or _iso(row[32]),
                "expires_at": _iso(row[19]),
            },
            "evidence_preview": {
                "primary": primary[:3],
                "supporting": supporting[:3],
                "counter": counter[:2],
                "source_coverage": _object(row[36]),
                "unresolved_questions": _list(row[37]),
                "known_limitations": _list(row[38]),
            },
            "topic": (
                {
                    "id": str(row[40]),
                    "title": row[41],
                    "event_type": row[42],
                    "resolution_deadline_at": _iso(row[43]),
                }
                if row[40]
                else None
            ),
            "locale": {
                "requested": locale,
                "published": published_locale,
                "fallback_used": published_locale != locale,
            },
        }


def _localized(proposition: dict[str, Any], locale: str) -> tuple[dict[str, Any], str]:
    requested = proposition.get(locale)
    if isinstance(requested, dict):
        return requested, locale
    english = proposition.get("en")
    if isinstance(english, dict):
        return english, "en"
    return proposition, "und"


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


def _publication_context(value: Any, *, captured_at: str | None) -> dict[str, Any]:
    fallback = empty_publication_context(captured_at=captured_at)
    captured = _object(value)
    if not captured:
        return fallback
    counts = _object(captured.get("counts"))
    return {
        **fallback,
        **captured,
        "counts": {**fallback["counts"], **counts},
        "claims": _list(captured.get("claims")),
        "expectations": _list(captured.get("expectations")),
        "rules": _list(captured.get("rules")),
        "research": _list(captured.get("research")),
        "coverage": _list(captured.get("coverage")),
    }


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _family(component_id: str) -> str:
    if component_id.startswith("resolution."):
        return "resolution-comparison"
    return component_id.split(".", 1)[0]


def _section_from_component(component_id: str) -> str:
    if ".rules" in component_id or "rule-" in component_id:
        return "rules-moved"
    if ".research" in component_id or "evidence-relationship" in component_id:
        return "research-frontier"
    if component_id.startswith("archive"):
        return "archive"
    return "expectations-moved"


def _derive_trend(fields: dict[str, Any]) -> str:
    delta = fields.get("delta_percentage_points")
    if isinstance(delta, (int, float)):
        return "up" if delta > 0 else "down" if delta < 0 else "neutral"
    value = json.dumps(fields, default=str).lower()
    if any(word in value for word in ("increase", "higher", "rose", "up ")):
        return "up"
    if any(word in value for word in ("decrease", "lower", "fell", "down")):
        return "down"
    return "neutral"
