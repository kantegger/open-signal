"""Edition writer (spec §60-71, OS-028 + OS-029).

Orchestrates deterministic candidates into a Daily Edition without ever
mutating Claims:

OS-028: Lead/Lead Set selection, page pacing, component choice, Sparse
        Edition handling
OS-029: render_plans + daily_editions rows, Edition JSON, CDN cache key,
        archive snapshot, rollback, correction

Claims are read-only here.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from open_signal.composer.editions import EditionComposer, ComposeError

COMPOSER_VERSION = "os-028"
SPARSE_THRESHOLD = 3  # fewer items -> sparse edition


class EditionWriter:
    def __init__(self, engine: Any, composer: EditionComposer | None = None) -> None:
        self.engine = engine
        self.composer = composer or EditionComposer()

    # ---------------------------------------------------------------- build
    def build_edition(
        self,
        candidates: list[dict[str, Any]],
        *,
        edition_date: date | None = None,
        section_maturity: str = "production",
    ) -> dict[str, Any]:
        """Compose + persist a daily edition. Returns the edition summary."""
        edition_date = edition_date or date.today()
        try:
            plan = self.composer.compose(candidates, section_maturity=section_maturity)
        except ComposeError as exc:
            raise

        items = plan["items"]
        sparse = len(items) < SPARSE_THRESHOLD
        included_claim_ids = sorted({i["claim_id"] for i in items if i.get("claim_id")})
        section_ids = sorted({i.get("section_id") or "default" for i in items})
        generated_at = datetime.now(timezone.utc)

        edition_payload = {
            "edition_date": edition_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "status": "sparse" if sparse else "published",
            "composer_version": COMPOSER_VERSION,
            "sections": section_ids,
            "lead": _lead(items),
            "lead_set": _lead_set(items),
            "slots": _slots_summary(items),
            "warnings": plan["warnings"],
        }

        with self.engine.begin() as conn:
            edition_row = conn.execute(
                text(
                    """
                    INSERT INTO daily_editions
                      (edition_date, generated_at, status, included_section_ids,
                       included_claim_ids, composer_version, component_versions,
                       generation_cost_usd, correction_count, edition_payload)
                    VALUES
                      (:date, :generated, :status, :sections, :claims,
                       :version, CAST(:components AS jsonb), 0, 0,
                       CAST(:payload AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "date": edition_date,
                    "generated": generated_at,
                    "status": "sparse" if sparse else "published",
                    "sections": section_ids,
                    "claims": [uuid.UUID(c) for c in included_claim_ids],
                    "version": COMPOSER_VERSION,
                    "components": json.dumps(_component_versions(items)),
                    "payload": json.dumps(edition_payload),
                },
            ).fetchone()
            edition_id = str(edition_row[0])

            # render plans: one row per slot group
            for slot_id, slot_items in (plan["slots"] or {}).items():
                if not slot_items:
                    continue
                first = slot_items[0]
                conn.execute(
                    text(
                        """
                        INSERT INTO render_plans
                          (edition_id, slot_id, section_instance_id, claim_ids,
                           component_id, component_version, component_variant,
                           headline, dek, display_fields, hidden_detail_fields,
                           evidence_bundle_id, visual_priority, mobile_priority,
                           generated_by, approved_by_verification_run_id)
                        VALUES
                          (:edition, :slot, NULL, :claims, :component, :version,
                           'standard', :headline, NULL, CAST(:fields AS jsonb),
                           CAST(:hidden AS jsonb), NULL, :vp, :mp, :generated, NULL)
                        """
                    ),
                    {
                        "edition": edition_id,
                        "slot": slot_id,
                        "claims": [uuid.UUID(first.get("claim_id"))] if first.get("claim_id") else [],
                        "component": first.get("component_id") or "",
                        "version": first.get("component_version") or "",
                        "headline": (first.get("display_fields") or {}).get(
                            "expectation_title",
                            (first.get("display_fields") or {}).get("rule_title") or "Signal",
                        ),
                        "fields": json.dumps(first.get("display_fields") or {}),
                        "hidden": json.dumps(first.get("hidden_detail_fields") or {}),
                        "vp": first.get("visual_priority", 5),
                        "mp": first.get("mobile_priority", 5),
                        "generated": f"{COMPOSER_VERSION}/{COMPOSER_VERSION}",
                    },
                )

        return {
            "edition_id": edition_id,
            "status": "sparse" if sparse else "published",
            "item_count": len(items),
            "claim_ids": included_claim_ids,
            "sections": section_ids,
            "cache_key": self.cache_key(edition_id),
            "warnings": plan["warnings"],
        }

    # ------------------------------------------------------------------- read
    def edition_json(self, edition_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT edition_date, generated_at, status, included_section_ids, "
                    "included_claim_ids, composer_version, component_versions, "
                    "generation_cost_usd, correction_count, edition_payload "
                    "FROM daily_editions WHERE id = :id"
                ),
                {"id": edition_id},
            ).fetchone()
        if row is None:
            return None
        return {
            "id": edition_id,
            "edition_date": row[0].isoformat(),
            "generated_at": row[1].isoformat(),
            "status": row[2],
            "included_sections": row[3],
            "included_claims": [str(c) for c in row[4]],
            "composer_version": row[5],
            "component_versions": row[6],
            "generation_cost_usd": float(row[7] or 0),
            "correction_count": row[8],
            "edition_payload": row[9],
        }

    def cache_key(self, edition_id: str) -> str:
        """CDN cache key: content-addressed by edition date + generated_at."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT edition_date, generated_at FROM daily_editions WHERE id = :id"),
                {"id": edition_id},
            ).fetchone()
        if row is None:
            raise KeyError(edition_id)
        ts = int(row[1].timestamp())
        return f"edition/{row[0].isoformat()}/{ts}/{edition_id}"

    # ---------------------------------------------------------------- archive
    def snapshot(self, edition_id: str) -> dict[str, Any]:
        """Archive snapshot = immutable edition JSON (claims are read-only)."""
        payload = self.edition_json(edition_id)
        if payload is None:
            raise KeyError(edition_id)
        return {"snapshot": payload, "immutable": True, "source": "daily_editions"}

    # ------------------------------------------------------------ rollback
    def rollback(self, edition_id: str, reason: str, actor: str = "editor") -> str:
        """Create a new edition restoring an older snapshot's payload."""
        payload = self.edition_json(edition_id)
        if payload is None:
            raise KeyError(edition_id)
        old = payload["edition_payload"]
        corrected = dict(old)
        corrected["rollback_from"] = edition_id
        corrected["correction_reason"] = reason

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO daily_editions
                      (edition_date, generated_at, status, included_section_ids,
                       included_claim_ids, composer_version, component_versions,
                       generation_cost_usd, correction_count, edition_payload)
                    VALUES
                      (:date, now(), 'corrected', :sections, :claims,
                       :version, CAST(:components AS jsonb), 0, 1,
                       CAST(:payload AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "date": payload["edition_date"],
                    "sections": payload["included_sections"],
                    "claims": [uuid.UUID(c) for c in payload["included_claims"]],
                    "version": payload["composer_version"],
                    "components": json.dumps(payload["component_versions"]),
                    "payload": json.dumps(corrected),
                },
            ).fetchone()
        return str(row[0])

    def correction(self, edition_id: str, patch: dict[str, Any], reason: str) -> str:
        """Publish a corrected edition (new row, correction_count incremented)."""
        payload = self.edition_json(edition_id)
        if payload is None:
            raise KeyError(edition_id)
        corrected = dict(payload["edition_payload"])
        corrected.update(patch)
        corrected["corrected_from"] = edition_id
        corrected["correction_reason"] = reason

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO daily_editions
                      (edition_date, generated_at, status, included_section_ids,
                       included_claim_ids, composer_version, component_versions,
                       generation_cost_usd, correction_count, edition_payload)
                    VALUES
                      (:date, now(), 'corrected', :sections, :claims,
                       :version, CAST(:components AS jsonb), 0,
                       :corrections, CAST(:payload AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "date": payload["edition_date"],
                    "sections": payload["included_sections"],
                    "claims": [uuid.UUID(c) for c in payload["included_claims"]],
                    "version": payload["composer_version"],
                    "components": json.dumps(payload["component_versions"]),
                    "corrections": (payload["correction_count"] or 0) + 1,
                    "payload": json.dumps(corrected),
                },
            ).fetchone()
        return str(row[0])


def _lead(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for i in items:
        if i.get("slot_id") == "lead":
            return {"component_id": i.get("component_id"), "headline": (i.get("display_fields") or {}).get("expectation_title")}
    return None


def _lead_set(items: list[dict[str, Any]]) -> list[str]:
    return [(i.get("display_fields") or {}).get("expectation_title") or (i.get("display_fields") or {}).get("rule_title") or "" for i in items[:2]]


def _slots_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in items:
        slot = i.get("slot_id") or "unassigned"
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def _component_versions(items: list[dict[str, Any]]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for i in items:
        cid = i.get("component_id")
        if cid:
            versions[cid] = i.get("component_version") or ""
    return versions
