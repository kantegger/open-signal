"""Read-only presenters for the rolling public front page."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from open_signal.composer.edition_writer import PUBLICATION_CHANNEL, SLOT_ORDER
from open_signal.sources.registry import Registry
from sqlalchemy import text


class FrontPagePresenter:
    """Assemble validated Render Plans without reinterpreting their Claims."""

    def __init__(self, engine: Any, registry: Registry | None = None) -> None:
        self.engine = engine
        self.registry = registry or Registry.load()

    def build(self, *, locale: str = "en") -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            edition = conn.execute(
                text(
                    """
                    SELECT e.id, e.edition_date, e.generated_at, e.status,
                           e.included_section_ids, e.composer_version,
                           e.correction_count, e.trigger_type,
                           e.supersedes_edition_id, e.freshness_summary,
                           e.published_at, e.policy_version, e.edition_payload,
                           pc.previous_edition_id, pc.updated_at
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
                               NULL, generated_at
                        FROM daily_editions
                        WHERE status IN ('published', 'sparse', 'beta', 'corrected')
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
                           eb.snapshot_hash
                    FROM render_plans rp
                    LEFT JOIN claims c ON c.id = rp.claim_ids[1]
                    LEFT JOIN evidence_bundles eb
                      ON eb.id = COALESCE(rp.evidence_bundle_id, c.evidence_bundle_id)
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
                    WHERE status IN ('published', 'sparse', 'beta', 'corrected')
                    ORDER BY generated_at DESC
                    LIMIT 12
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
                "is_current": True,
                "publication_mode": "rolling_snapshot",
            },
            "freshness": {
                **freshness,
                "last_successful_compile_at": composed_at,
                "channel_updated_at": _iso(edition[14]),
            },
            "sections": list(edition[4] or []),
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
                }
                for row in archive
            ],
            "method": {
                "summary": (
                    "Open Signal separates observation, analysis, and assessment; "
                    "publishes only verified Render Plans; and preserves every snapshot."
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
