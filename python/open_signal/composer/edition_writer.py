"""Immutable rolling-edition writer (spec §60–71, OS-028/029/048).

The historical table name ``daily_editions`` is retained, but an edition is a
snapshot generated whenever verified Section output or a retirement event
changes the active publication pool.  Claims remain read-only.  A public
snapshot becomes current only after every Render Plan row is written in the
same transaction.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from open_signal.composer.editions import EditionComposer
from open_signal.composer.publication_context import (
    CONTEXT_VERSION,
    PublicationContextBuilder,
)
from open_signal.derived.public_interest import (
    decision_from_render_candidate,
    load_editorial_scope_policy,
)

COMPOSER_VERSION = "os-052"
PUBLICATION_CHANNEL = "front-page"
SPARSE_THRESHOLD = 3
PUBLIC_STATUSES = {"published", "sparse", "beta", "corrected"}
SLOT_ORDER = ("lead", "secondary", "live_feed", "digest", "main", "utility", "archive")
EDITORIAL_SLOTS = frozenset({"lead", "secondary", "main"})
CONTINUITY_LOOKBACK_HOURS = 720
CONTINUITY_SECONDARY_TARGET = 3
CONTINUITY_QUERY_LIMIT = 5000
CONTINUITY_PRIORITY_BASE = 2000


class EditionWriter:
    def __init__(
        self,
        engine: Any,
        composer: EditionComposer | None = None,
        context_builder: PublicationContextBuilder | None = None,
    ) -> None:
        self.engine = engine
        self.composer = composer or EditionComposer()
        self.context_builder = context_builder or PublicationContextBuilder()

    # ---------------------------------------------------------------- build
    def build_edition(
        self,
        candidates: list[dict[str, Any]],
        *,
        edition_date: date | None = None,
        section_maturity: str = "production",
        trigger_type: str = "scheduled",
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Compile and atomically publish one immutable edition snapshot."""
        generated_at = _utc(generated_at or datetime.now(timezone.utc))
        edition_date = edition_date or generated_at.date()
        plan = self.composer.compose(
            candidates,
            section_maturity=section_maturity,
            now=generated_at,
        )

        items = plan["items"]
        sparse = len(items) < SPARSE_THRESHOLD
        status = "sparse" if sparse else "published"
        included_claim_ids = sorted(
            {
                str(claim_id)
                for item in items
                for claim_id in _claim_ids(item)
                if _uuid_or_none(claim_id) is not None
            }
        )
        section_ids = sorted(
            {
                str(item.get("section_id"))
                for item in items
                if item.get("section_id") and item.get("section_id") != "default"
            }
        )
        freshness_summary = _freshness_summary(items, plan["warnings"])

        with self.engine.begin() as conn:
            publication_context = self.context_builder.capture(
                conn,
                captured_at=generated_at,
            )
            current = conn.execute(
                text(
                    "SELECT current_edition_id FROM publication_channels "
                    "WHERE id = :channel FOR UPDATE"
                ),
                {"channel": PUBLICATION_CHANNEL},
            ).fetchone()
            previous_id = str(current[0]) if current else None

            edition_payload = {
                "edition_date": edition_date.isoformat(),
                "generated_at": generated_at.isoformat(),
                "status": status,
                "publication_mode": "rolling_snapshot",
                "trigger_type": trigger_type,
                "supersedes_edition_id": previous_id,
                "composer_version": COMPOSER_VERSION,
                "policy_version": self.composer.freshness_evaluator.policy_version,
                "editorial_scope_policy_version": load_editorial_scope_policy()[
                    "version"
                ],
                "sections": section_ids,
                "lead": _lead(items),
                "lead_set": _lead_set(items),
                "slots": _slots_summary(items),
                "continuity": _continuity_summary(items),
                "freshness": freshness_summary,
                "warnings": plan["warnings"],
                "publication_context": publication_context,
            }

            edition_row = conn.execute(
                text(
                    """
                    INSERT INTO daily_editions
                      (edition_date, generated_at, status, included_section_ids,
                       included_claim_ids, composer_version, component_versions,
                       generation_cost_usd, correction_count, edition_payload,
                       trigger_type, supersedes_edition_id, freshness_summary,
                       published_at, policy_version)
                    VALUES
                      (:date, :generated, :status, :sections, :claims,
                       :version, CAST(:components AS jsonb), 0, 0,
                       CAST(:payload AS jsonb), :trigger, :supersedes,
                       CAST(:freshness AS jsonb), :published, :policy)
                    RETURNING id
                    """
                ),
                {
                    "date": edition_date,
                    "generated": generated_at,
                    "status": status,
                    "sections": section_ids,
                    "claims": [uuid.UUID(value) for value in included_claim_ids],
                    "version": COMPOSER_VERSION,
                    "components": _dumps(_component_versions(items)),
                    "payload": _dumps(edition_payload),
                    "trigger": trigger_type,
                    "supersedes": _uuid_or_none(previous_id),
                    "freshness": _dumps(freshness_summary),
                    "published": generated_at,
                    "policy": self.composer.freshness_evaluator.policy_version,
                },
            ).fetchone()
            edition_id = str(edition_row[0])

            for slot_id in SLOT_ORDER:
                for position, item in enumerate(plan["slots"].get(slot_id, [])):
                    self._insert_render_plan(
                        conn,
                        edition_id=edition_id,
                        slot_id=slot_id,
                        position=position,
                        item=item,
                    )

            _insert_audit_event(
                conn,
                action="publication.snapshot.published",
                actor=f"composer/{COMPOSER_VERSION}",
                target=edition_id,
                detail={
                    "channel": PUBLICATION_CHANNEL,
                    "trigger_type": trigger_type,
                    "supersedes_edition_id": previous_id,
                    "status": status,
                    "item_count": len(items),
                    "claim_ids": included_claim_ids,
                    "section_ids": section_ids,
                    "policy_version": self.composer.freshness_evaluator.policy_version,
                },
            )

            # This pointer change is the final statement in the transaction.
            # Readers therefore see either the complete old snapshot or the
            # complete new snapshot, never a partially written page.
            conn.execute(
                text(
                    """
                    INSERT INTO publication_channels
                      (id, current_edition_id, previous_edition_id,
                       policy_version, updated_at)
                    VALUES (:channel, :current, :previous, :policy, :updated)
                    ON CONFLICT (id) DO UPDATE SET
                      previous_edition_id = publication_channels.current_edition_id,
                      current_edition_id = EXCLUDED.current_edition_id,
                      policy_version = EXCLUDED.policy_version,
                      updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "channel": PUBLICATION_CHANNEL,
                    "current": uuid.UUID(edition_id),
                    "previous": _uuid_or_none(previous_id),
                    "policy": self.composer.freshness_evaluator.policy_version,
                    "updated": generated_at,
                },
            )

        return {
            "edition_id": edition_id,
            "status": status,
            "item_count": len(items),
            "claim_ids": included_claim_ids,
            "sections": section_ids,
            "cache_key": self.cache_key(edition_id),
            "warnings": plan["warnings"],
            "trigger_type": trigger_type,
            "supersedes_edition_id": previous_id,
            "policy_version": self.composer.freshness_evaluator.policy_version,
        }

    def build_rolling_edition(
        self,
        candidates: list[dict[str, Any]],
        *,
        refreshed_section_ids: set[str] | None = None,
        retain_refreshed_items: bool = False,
        trigger_type: str = "section_refresh",
        generated_at: datetime | None = None,
        section_maturity: str = "production",
    ) -> dict[str, Any]:
        """Recompose the whole page from changed and still-active Sections.

        A refreshed Section normally replaces its previous publication output
        as a unit. Scanner-style Sections may request ``retain_refreshed_items``
        to compile their still-valid featured and feed items together with new
        observations. New candidates retain priority over carried items.
        Unrefreshed Sections are always carried forward and independently
        re-evaluated for Claim validity and elapsed-age retirement.
        """
        generated_at = _utc(generated_at or datetime.now(timezone.utc))
        refreshed = set(refreshed_section_ids or ())
        if refreshed_section_ids is None:
            refreshed = {
                str(item["section_id"]) for item in candidates if item.get("section_id")
            }
        active: list[dict[str, Any]] = []
        carried_from_refreshed: list[dict[str, Any]] = []
        for item in self._current_candidates():
            if not _public_interest_allows_slot(item, now=generated_at):
                continue
            if item.get("_continuity_fill") and not _continuity_source_is_live(
                item, now=generated_at
            ):
                continue
            if item.get("section_id") not in refreshed:
                active.append(item)
                continue
            if retain_refreshed_items:
                carried = dict(item)
                carried["priority"] = 1000 + int(
                    item.get("visual_priority") or item.get("position") or 0
                )
                carried_from_refreshed.append(carried)

        # Scanner refreshes retain compact history, but a refreshed Section's
        # old full editorial surfaces may only fill capacity left by the new
        # candidates.  Without this boundary, three new featured Expectations
        # plus three still-current featured items trip the composer's strict
        # Section-diversity gate before its priority/slot rules can run.
        carried_from_refreshed = _retain_within_editorial_cap(
            carried_from_refreshed,
            candidates,
            section_cap=self.composer.section_cap,
        )
        merged = self._fill_continuity_reserve(
            _dedupe_candidates([*active, *carried_from_refreshed, *candidates]),
            generated_at=generated_at,
            section_maturity=section_maturity,
        )
        return self.build_edition(
            merged,
            edition_date=generated_at.date(),
            section_maturity=section_maturity,
            trigger_type=trigger_type,
            generated_at=generated_at,
        )

    def reconcile_freshness(
        self,
        *,
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Publish only when freshness or validity changes public meaning.

        This method is safe to schedule hourly: it does not manufacture an
        Edition when every current item would retain the same state and Slot.
        """
        generated_at = _utc(generated_at or datetime.now(timezone.utc))
        current_id = self.current_edition_id()
        if current_id is None:
            return {"published": False, "reason": "no current edition"}
        candidates = self._current_candidates()
        transitions: list[dict[str, Any]] = []
        for candidate in candidates:
            decision = self.composer.freshness_evaluator.evaluate(
                candidate,
                now=generated_at,
            )
            previous_state = str(candidate.get("freshness_state") or "current")
            if not decision.eligible or decision.state != previous_state:
                transitions.append(
                    {
                        "claim_id": candidate.get("claim_id"),
                        "from": previous_state,
                        "to": decision.state,
                        "reason": decision.reason,
                    }
                )
            elif decision.demote_from_lead and candidate.get("slot_id") == "lead":
                transitions.append(
                    {
                        "claim_id": candidate.get("claim_id"),
                        "from": "lead",
                        "to": "secondary",
                        "reason": decision.reason,
                    }
                )

        with self.engine.connect() as conn:
            channel_state = conn.execute(
                text(
                    """
                    SELECT pc.policy_version,
                           e.composer_version,
                           e.edition_payload #>> '{publication_context,version}',
                            e.edition_payload #>>
                              '{publication_context,research_fingerprint}',
                            e.edition_payload ->> 'editorial_scope_policy_version'
                    FROM publication_channels pc
                    LEFT JOIN daily_editions e ON e.id = pc.current_edition_id
                    WHERE pc.id = :channel
                    """
                ),
                {"channel": PUBLICATION_CHANNEL},
            ).fetchone()
            current_research_fingerprint = self.context_builder.research_fingerprint(
                conn,
                captured_at=generated_at,
            )
        channel_policy = channel_state[0] if channel_state else None
        channel_composer = channel_state[1] if channel_state else None
        context_version = channel_state[2] if channel_state else None
        stored_research_fingerprint = channel_state[3] if channel_state else None
        stored_scope_policy = channel_state[4] if channel_state else None
        current_policy = self.composer.freshness_evaluator.policy_version
        current_scope_policy = str(load_editorial_scope_policy()["version"])
        if channel_policy != current_policy:
            transitions.append(
                {
                    "claim_id": None,
                    "from": channel_policy,
                    "to": current_policy,
                    "reason": "freshness policy version changed",
                }
            )
        if channel_composer != COMPOSER_VERSION:
            transitions.append(
                {
                    "claim_id": None,
                    "from": channel_composer,
                    "to": COMPOSER_VERSION,
                    "reason": "edition composer version changed",
                }
            )
        if context_version != CONTEXT_VERSION:
            transitions.append(
                {
                    "claim_id": None,
                    "from": context_version,
                    "to": CONTEXT_VERSION,
                    "reason": "publication context version changed",
                }
            )
        if stored_research_fingerprint != current_research_fingerprint:
            transitions.append(
                {
                    "claim_id": None,
                    "from": stored_research_fingerprint,
                    "to": current_research_fingerprint,
                    "reason": "public research screening changed",
                }
            )
        if stored_scope_policy != current_scope_policy:
            transitions.append(
                {
                    "claim_id": None,
                    "from": stored_scope_policy,
                    "to": current_scope_policy,
                    "reason": "editorial scope policy version changed",
                }
            )

        if not transitions:
            return {
                "published": False,
                "reason": "no material freshness transition",
                "edition_id": current_id,
            }
        edition = self.build_rolling_edition(
            [],
            refreshed_section_ids=set(),
            trigger_type="freshness_reconcile",
            generated_at=generated_at,
            section_maturity="beta",
        )
        return {"published": True, "transitions": transitions, **edition}

    def _insert_render_plan(
        self,
        conn: Any,
        *,
        edition_id: str,
        slot_id: str,
        position: int,
        item: dict[str, Any],
    ) -> None:
        fields = _json_object(item.get("display_fields"))
        hidden = _json_object(item.get("hidden_detail_fields"))
        variant = str(item.get("component_variant") or _variant_for(slot_id))
        if variant not in {"compact", "standard", "lead", "mobile"}:
            variant = _variant_for(slot_id)
        conn.execute(
            text(
                """
                INSERT INTO render_plans
                  (edition_id, slot_id, section_instance_id, claim_ids,
                   component_id, component_version, component_variant,
                   headline, dek, display_fields, hidden_detail_fields,
                   evidence_bundle_id, visual_priority, mobile_priority,
                   generated_by, approved_by_verification_run_id, position,
                   data_as_of, assessed_at, materially_updated_at,
                   freshness_state, expires_at)
                VALUES
                  (:edition, :slot, :section_instance, :claims, :component,
                   :version, :variant, :headline, :dek, CAST(:fields AS jsonb),
                   CAST(:hidden AS jsonb), :evidence, :vp, :mp, :generated,
                   :approved, :position, :data_as_of, :assessed_at,
                   :materially_updated_at, :freshness_state, :expires_at)
                """
            ),
            {
                "edition": uuid.UUID(edition_id),
                "slot": slot_id,
                "section_instance": _uuid_or_none(item.get("section_instance_id")),
                "claims": [
                    value
                    for value in (
                        _uuid_or_none(claim_id) for claim_id in _claim_ids(item)
                    )
                    if value is not None
                ],
                "component": item.get("component_id") or "signal-feed.compact-change",
                "version": item.get("component_version") or "1.0.0",
                "variant": variant,
                "headline": _headline(item),
                "dek": item.get("dek")
                or fields.get("primary_observation")
                or fields.get("observation"),
                "fields": _dumps(fields),
                "hidden": _dumps(hidden),
                "evidence": _uuid_or_none(item.get("evidence_bundle_id")),
                "vp": int(item.get("visual_priority", 5)),
                "mp": int(item.get("mobile_priority", item.get("visual_priority", 5))),
                "generated": item.get("generated_by")
                or f"{COMPOSER_VERSION}/{COMPOSER_VERSION}",
                "approved": _uuid_or_none(item.get("approved_by_verification_run_id")),
                "position": position,
                "data_as_of": _time(
                    item.get("data_as_of")
                    or fields.get("data_as_of")
                    or fields.get("updated_at")
                ),
                "assessed_at": _time(item.get("assessed_at") or item.get("issued_at")),
                "materially_updated_at": _time(
                    item.get("materially_updated_at")
                    or fields.get("materially_updated_at")
                    or fields.get("updated_at")
                    or item.get("issued_at")
                ),
                "freshness_state": item.get("freshness_state") or "current",
                "expires_at": _time(item.get("expires_at")),
            },
        )

    # ---------------------------------------------------------------- read
    def edition_json(self, edition_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT edition_date, generated_at, status, included_section_ids, "
                    "included_claim_ids, composer_version, component_versions, "
                    "generation_cost_usd, correction_count, edition_payload, "
                    "trigger_type, supersedes_edition_id, freshness_summary, "
                    "published_at, policy_version "
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
            "included_claims": [str(value) for value in row[4]],
            "composer_version": row[5],
            "component_versions": _json_object(row[6]),
            "generation_cost_usd": float(row[7] or 0),
            "correction_count": row[8],
            "edition_payload": _json_object(row[9]),
            "trigger_type": row[10],
            "supersedes_edition_id": str(row[11]) if row[11] else None,
            "freshness_summary": _json_object(row[12]),
            "published_at": row[13].isoformat() if row[13] else None,
            "policy_version": row[14],
        }

    def current_edition_id(self) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT current_edition_id FROM publication_channels "
                    "WHERE id = :channel"
                ),
                {"channel": PUBLICATION_CHANNEL},
            ).fetchone()
        return str(row[0]) if row else None

    def cache_key(self, edition_id: str) -> str:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT edition_date, generated_at FROM daily_editions WHERE id = :id"
                ),
                {"id": edition_id},
            ).fetchone()
        if row is None:
            raise KeyError(edition_id)
        timestamp = int(row[1].timestamp())
        return f"edition/{row[0].isoformat()}/{timestamp}/{edition_id}"

    def _current_candidates(self) -> list[dict[str, Any]]:
        edition_id = self.current_edition_id()
        return self._candidates_for_edition(edition_id) if edition_id else []

    def _candidates_for_edition(self, edition_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT rp.slot_id, rp.section_instance_id, rp.claim_ids,
                           rp.component_id, rp.component_version,
                           rp.component_variant, rp.headline, rp.dek,
                           rp.display_fields, rp.hidden_detail_fields,
                           rp.evidence_bundle_id, rp.visual_priority,
                           rp.mobile_priority, rp.generated_by,
                           rp.approved_by_verification_run_id, rp.position,
                           rp.data_as_of, rp.assessed_at,
                           rp.materially_updated_at, rp.freshness_state,
                           rp.expires_at, c.id, c.status, c.section_id,
                           c.claim_type, c.issued_at, c.valid_until, c.updated_at,
                           si.subject_type, si.subject_id, sm.source_id,
                           sm.external_event_id, sm.status,
                           ce.id, ce.status, ce.resolution_deadline_at
                     FROM render_plans rp
                     LEFT JOIN claims c ON c.id = rp.claim_ids[1]
                     LEFT JOIN section_instances si
                       ON si.id = rp.section_instance_id
                     LEFT JOIN source_markets sm
                       ON si.subject_type = 'source_market'
                      AND sm.id = si.subject_id
                     LEFT JOIN LATERAL (
                       SELECT id, status, resolution_deadline_at
                       FROM canonical_expectations
                       WHERE si.subject_type = 'source_market'
                         AND source_market_ids @> ARRAY[si.subject_id]::uuid[]
                       ORDER BY updated_at DESC LIMIT 1
                     ) ce ON true
                     WHERE rp.edition_id = :edition
                     ORDER BY rp.slot_id, rp.position
                    """
                ),
                {"edition": edition_id},
            ).fetchall()
        return [_candidate_from_render_row(row) for row in rows]

    def _recent_editorial_candidates(
        self, *, generated_at: datetime
    ) -> list[dict[str, Any]]:
        """Load a bounded, immutable history pool for continuity backfill.

        The query intentionally reads only prior full editorial surfaces.  It
        never republishes them directly: every row is re-evaluated against the
        current freshness and semantic-validity policy before selection.
        """
        lookback_start = generated_at - timedelta(hours=CONTINUITY_LOOKBACK_HOURS)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT rp.slot_id, rp.section_instance_id, rp.claim_ids,
                           rp.component_id, rp.component_version,
                           rp.component_variant, rp.headline, rp.dek,
                           rp.display_fields, rp.hidden_detail_fields,
                           rp.evidence_bundle_id, rp.visual_priority,
                           rp.mobile_priority, rp.generated_by,
                           rp.approved_by_verification_run_id, rp.position,
                           rp.data_as_of, rp.assessed_at,
                           rp.materially_updated_at, rp.freshness_state,
                           rp.expires_at, c.id, c.status, c.section_id,
                           c.claim_type, c.issued_at, c.valid_until, c.updated_at,
                           si.subject_type, si.subject_id, sm.source_id,
                           sm.external_event_id, sm.status,
                           ce.id, ce.status, ce.resolution_deadline_at,
                           e.id, e.generated_at
                    FROM daily_editions e
                    JOIN render_plans rp ON rp.edition_id = e.id
                    LEFT JOIN claims c ON c.id = rp.claim_ids[1]
                    LEFT JOIN section_instances si
                      ON si.id = rp.section_instance_id
                    LEFT JOIN source_markets sm
                      ON si.subject_type = 'source_market'
                     AND sm.id = si.subject_id
                    LEFT JOIN LATERAL (
                      SELECT id, status, resolution_deadline_at
                      FROM canonical_expectations
                      WHERE si.subject_type = 'source_market'
                        AND source_market_ids @> ARRAY[si.subject_id]::uuid[]
                      ORDER BY updated_at DESC LIMIT 1
                    ) ce ON true
                    WHERE e.generated_at >= :lookback_start
                      AND e.generated_at <= :generated_at
                      AND e.status IN ('published', 'sparse', 'beta', 'corrected')
                      AND rp.slot_id IN ('lead', 'secondary', 'main')
                    ORDER BY e.generated_at DESC,
                             CASE rp.slot_id
                               WHEN 'lead' THEN 0
                               WHEN 'secondary' THEN 1
                               ELSE 2
                             END,
                             rp.visual_priority, rp.position
                    LIMIT :query_limit
                    """
                ),
                {
                    "lookback_start": lookback_start,
                    "generated_at": generated_at,
                    "query_limit": CONTINUITY_QUERY_LIMIT,
                },
            ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            candidate = _candidate_from_render_row(row)
            candidate["_continuity_source_edition_id"] = str(row[36])
            candidate["_continuity_source_edition_generated_at"] = row[37].isoformat()
            candidate["_continuity_source_slot"] = candidate.get("slot_id")
            candidates.append(candidate)
        return candidates

    def _fill_continuity_reserve(
        self,
        candidates: list[dict[str, Any]],
        *,
        generated_at: datetime,
        section_maturity: str,
    ) -> list[dict[str, Any]]:
        """Fill spare Secondary capacity from still-valid recent Editions.

        Fresh candidates and the current Edition always win.  The reserve is
        considered only when Secondary Signals would otherwise be under the
        OS-048 target of three.  Original evidence and material timestamps are
        preserved, making the age visible instead of presenting carry-forward
        material as newly observed.
        """
        visible = _dedupe_candidates(candidates)
        visible = self._fill_lead_continuity_reserve(
            visible,
            generated_at=generated_at,
            section_maturity=section_maturity,
        )
        preflight = self.composer.compose(
            visible,
            section_maturity=section_maturity,
            now=generated_at,
        )
        secondary_count = len(preflight["slots"].get("secondary", []))
        needed = max(0, CONTINUITY_SECONDARY_TARGET - secondary_count)
        if needed == 0:
            return visible

        seen_claims = {
            str(item.get("claim_id"))
            for item in visible
            if item.get("claim_id")
        }
        seen_keys = {_continuity_identity(item) for item in visible}
        reserve_by_key: dict[str, dict[str, Any]] = {}
        for historical in self._recent_editorial_candidates(
            generated_at=generated_at
        ):
            claim_id = str(historical.get("claim_id") or "")
            if claim_id and claim_id in seen_claims:
                continue

            candidate = dict(historical)
            source_slot = str(candidate.get("slot_id") or "secondary")
            candidate["_continuity_source_slot"] = source_slot
            candidate["slot_id"] = "secondary"
            candidate["component_variant"] = "standard"
            candidate["presentation_role"] = "primary"

            definition = self.composer.component_runtime.registry.component(
                str(candidate.get("component_id") or "")
            )
            if definition is None or "secondary" not in definition.supported_slot_types:
                continue
            if not _continuity_source_is_live(candidate, now=generated_at):
                continue
            if not _public_interest_allows_slot(
                candidate,
                now=generated_at,
                slot_override="secondary",
            ):
                continue
            decision = self.composer.freshness_evaluator.evaluate(
                candidate, now=generated_at
            )
            if not decision.eligible:
                continue

            key = _continuity_identity(candidate)
            if key in seen_keys or key in reserve_by_key:
                continue
            candidate["_continuity_freshness_state"] = decision.state
            candidate["freshness_state"] = decision.state
            reserve_by_key[key] = candidate

        reserve = list(reserve_by_key.values())
        selected: list[dict[str, Any]] = []
        while reserve and len(selected) < needed:
            candidate = min(
                reserve,
                key=lambda item: _continuity_rank(
                    item,
                    visible=[*visible, *selected],
                ),
            )
            reserve.remove(candidate)
            continuity_key = _continuity_identity(candidate)
            hidden = dict(_json_object(candidate.get("hidden_detail_fields")))
            hidden["publication_continuity"] = {
                "origin": "recent_edition",
                "continuity_key": continuity_key,
                "source_edition_id": candidate.get(
                    "_continuity_source_edition_id"
                ),
                "source_edition_generated_at": candidate.get(
                    "_continuity_source_edition_generated_at"
                ),
                "source_slot": candidate.get("_continuity_source_slot"),
                "retained_data_as_of": candidate.get("data_as_of"),
            }
            candidate["hidden_detail_fields"] = hidden
            candidate["_continuity_fill"] = True
            candidate["continuity_key"] = continuity_key
            candidate["priority"] = CONTINUITY_PRIORITY_BASE + len(selected)
            selected.append(candidate)

        return _dedupe_candidates([*visible, *selected])

    def _fill_lead_continuity_reserve(
        self,
        candidates: list[dict[str, Any]],
        *,
        generated_at: datetime,
        section_maturity: str,
    ) -> list[dict[str, Any]]:
        """Keep an important recent Hero instead of promoting fresh trivia."""

        visible = _dedupe_candidates(candidates)
        preflight = self.composer.compose(
            visible,
            section_maturity=section_maturity,
            now=generated_at,
        )
        if preflight["slots"].get("lead"):
            return visible

        seen_claims = {
            str(item.get("claim_id")) for item in visible if item.get("claim_id")
        }
        seen_keys = {_continuity_identity(item) for item in visible}
        for historical in self._recent_editorial_candidates(
            generated_at=generated_at
        ):
            if str(historical.get("slot_id") or "") != "lead":
                continue
            claim_id = str(historical.get("claim_id") or "")
            if claim_id and claim_id in seen_claims:
                continue
            key = _continuity_identity(historical)
            if key in seen_keys:
                continue
            if not _continuity_source_is_live(historical, now=generated_at):
                continue
            if not _public_interest_allows_slot(
                historical,
                now=generated_at,
                slot_override="lead",
            ):
                continue
            freshness = self.composer.freshness_evaluator.evaluate(
                historical,
                now=generated_at,
            )
            if not freshness.eligible or freshness.demote_from_lead:
                continue
            definition = self.composer.component_runtime.registry.component(
                str(historical.get("component_id") or "")
            )
            if definition is None or "lead" not in definition.supported_slot_types:
                continue

            candidate = dict(historical)
            hidden = dict(_json_object(candidate.get("hidden_detail_fields")))
            hidden["publication_continuity"] = {
                "origin": "recent_edition",
                "continuity_key": key,
                "source_edition_id": candidate.get(
                    "_continuity_source_edition_id"
                ),
                "source_edition_generated_at": candidate.get(
                    "_continuity_source_edition_generated_at"
                ),
                "source_slot": "lead",
                "retained_data_as_of": candidate.get("data_as_of"),
            }
            candidate["hidden_detail_fields"] = hidden
            candidate["slot_id"] = "lead"
            candidate["component_variant"] = "lead"
            candidate["presentation_role"] = "primary"
            candidate["freshness_state"] = freshness.state
            candidate["_continuity_fill"] = True
            candidate["continuity_key"] = key
            candidate["priority"] = CONTINUITY_PRIORITY_BASE - 1
            return _dedupe_candidates([*visible, candidate])
        return visible

    # --------------------------------------------------------------- archive
    def snapshot(self, edition_id: str) -> dict[str, Any]:
        payload = self.edition_json(edition_id)
        if payload is None:
            raise KeyError(edition_id)
        return {"snapshot": payload, "immutable": True, "source": "daily_editions"}

    # --------------------------------------------------------- correction flow
    def rollback(self, edition_id: str, reason: str, actor: str = "editor") -> str:
        return self._publish_clone(
            edition_id,
            trigger_type="rollback",
            reason=reason,
            payload_patch={"rollback_from": edition_id},
            actor=actor,
        )

    def correction(self, edition_id: str, patch: dict[str, Any], reason: str) -> str:
        return self._publish_clone(
            edition_id,
            trigger_type="correction",
            reason=reason,
            payload_patch={**patch, "corrected_from": edition_id},
            actor="editor",
        )

    def _publish_clone(
        self,
        edition_id: str,
        *,
        trigger_type: str,
        reason: str,
        payload_patch: dict[str, Any],
        actor: str,
    ) -> str:
        source = self.edition_json(edition_id)
        if source is None:
            raise KeyError(edition_id)
        generated_at = datetime.now(timezone.utc)
        payload = {**source["edition_payload"], **payload_patch}
        payload["correction_reason"] = reason
        payload["generated_at"] = generated_at.isoformat()
        payload["trigger_type"] = trigger_type

        with self.engine.begin() as conn:
            current = conn.execute(
                text(
                    "SELECT current_edition_id FROM publication_channels "
                    "WHERE id = :channel FOR UPDATE"
                ),
                {"channel": PUBLICATION_CHANNEL},
            ).fetchone()
            previous_id = str(current[0]) if current else None
            row = conn.execute(
                text(
                    """
                    INSERT INTO daily_editions
                      (edition_date, generated_at, status, included_section_ids,
                       included_claim_ids, composer_version, component_versions,
                       generation_cost_usd, correction_count, edition_payload,
                       trigger_type, supersedes_edition_id, freshness_summary,
                       published_at, policy_version)
                    VALUES
                      (:date, :generated, 'corrected', :sections, :claims,
                       :version, CAST(:components AS jsonb), 0, :corrections,
                       CAST(:payload AS jsonb), :trigger, :supersedes,
                       CAST(:freshness AS jsonb), :published, :policy)
                    RETURNING id
                    """
                ),
                {
                    "date": date.fromisoformat(source["edition_date"]),
                    "generated": generated_at,
                    "sections": source["included_sections"],
                    "claims": [uuid.UUID(value) for value in source["included_claims"]],
                    "version": source["composer_version"],
                    "components": _dumps(source["component_versions"]),
                    "corrections": int(source["correction_count"] or 0) + 1,
                    "payload": _dumps(payload),
                    "trigger": trigger_type,
                    "supersedes": _uuid_or_none(previous_id),
                    "freshness": _dumps(source["freshness_summary"]),
                    "published": generated_at,
                    "policy": source["policy_version"],
                },
            ).fetchone()
            new_id = str(row[0])
            conn.execute(
                text(
                    """
                    INSERT INTO render_plans
                      (edition_id, slot_id, section_instance_id, claim_ids,
                       component_id, component_version, component_variant,
                       headline, dek, display_fields, hidden_detail_fields,
                       evidence_bundle_id, visual_priority, mobile_priority,
                       generated_by, approved_by_verification_run_id, position,
                       data_as_of, assessed_at, materially_updated_at,
                       freshness_state, expires_at)
                    SELECT :new_id, slot_id, section_instance_id, claim_ids,
                           component_id, component_version, component_variant,
                           headline, dek, display_fields, hidden_detail_fields,
                           evidence_bundle_id, visual_priority, mobile_priority,
                           generated_by, approved_by_verification_run_id, position,
                           data_as_of, assessed_at, materially_updated_at,
                           freshness_state, expires_at
                    FROM render_plans WHERE edition_id = :source_id
                    """
                ),
                {"new_id": uuid.UUID(new_id), "source_id": uuid.UUID(edition_id)},
            )
            _insert_audit_event(
                conn,
                action=f"publication.snapshot.{trigger_type}",
                actor=actor,
                target=new_id,
                detail={
                    "channel": PUBLICATION_CHANNEL,
                    "source_edition_id": edition_id,
                    "supersedes_edition_id": previous_id,
                    "reason": reason,
                    "policy_version": source["policy_version"],
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO publication_channels
                      (id, current_edition_id, previous_edition_id,
                       policy_version, updated_at)
                    VALUES (:channel, :current, :previous, :policy, :updated)
                    ON CONFLICT (id) DO UPDATE SET
                      previous_edition_id = publication_channels.current_edition_id,
                      current_edition_id = EXCLUDED.current_edition_id,
                      policy_version = EXCLUDED.policy_version,
                      updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "channel": PUBLICATION_CHANNEL,
                    "current": uuid.UUID(new_id),
                    "previous": _uuid_or_none(previous_id),
                    "policy": source["policy_version"],
                    "updated": generated_at,
                },
            )
        return new_id


def _insert_audit_event(
    conn: Any,
    *,
    action: str,
    actor: str,
    target: str,
    detail: dict[str, Any],
) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_events (action, actor, target, detail) "
            "VALUES (:action, :actor, :target, CAST(:detail AS jsonb))"
        ),
        {
            "action": action,
            "actor": actor,
            "target": target,
            "detail": _dumps(detail),
        },
    )


def _candidate_from_render_row(row: Any) -> dict[str, Any]:
    hidden = _json_object(row[9])
    continuity = _json_object(hidden.get("publication_continuity"))
    claim_ids = [str(value) for value in (row[2] or [])]
    candidate: dict[str, Any] = {
        "slot_id": row[0],
        "presentation_role": "index_echo" if row[0] == "digest" else "primary",
        "section_instance_id": str(row[1]) if row[1] else None,
        "claim_ids": claim_ids,
        "claim_id": (
            str(row[21])
            if row[21]
            else (claim_ids[0] if claim_ids else None)
        ),
        "component_id": row[3],
        "component_version": row[4],
        "component_variant": row[5],
        "headline": row[6],
        "dek": row[7],
        "display_fields": _json_object(row[8]),
        "hidden_detail_fields": hidden,
        "evidence_bundle_id": str(row[10]) if row[10] else None,
        "visual_priority": row[11],
        "mobile_priority": row[12],
        "generated_by": row[13],
        "approved_by_verification_run_id": str(row[14]) if row[14] else None,
        "position": row[15],
        "data_as_of": row[16].isoformat() if row[16] else None,
        "assessed_at": row[17].isoformat() if row[17] else None,
        "materially_updated_at": row[18].isoformat() if row[18] else None,
        "freshness_state": row[19],
        "expires_at": row[20].isoformat() if row[20] else None,
        "claim_status": row[22] or "published",
        "section_id": row[23] or "default",
        "claim_type": row[24] or "source_fact",
        "issued_at": row[25].isoformat() if row[25] else None,
        "valid_until": row[26].isoformat() if row[26] else None,
        "claim_updated_at": row[27].isoformat() if row[27] else None,
        "subject_type": row[28],
        "subject_id": str(row[29]) if row[29] else None,
        "source_id": str(row[30]) if row[30] else None,
        "external_event_id": str(row[31]) if row[31] else None,
        "source_status": row[32],
        "topic_id": str(row[33]) if row[33] else None,
        "topic_status": row[34],
        "resolution_deadline_at": row[35].isoformat() if row[35] else None,
    }
    if continuity:
        candidate.update(
            {
                "_continuity_fill": True,
                "_continuity_source_edition_id": continuity.get(
                    "source_edition_id"
                ),
                "_continuity_source_edition_generated_at": continuity.get(
                    "source_edition_generated_at"
                ),
                "_continuity_source_slot": continuity.get("source_slot"),
                "continuity_key": continuity.get("continuity_key"),
                "priority": CONTINUITY_PRIORITY_BASE + int(row[15] or 0),
            }
        )
    candidate["continuity_key"] = candidate.get(
        "continuity_key"
    ) or _continuity_identity(candidate)
    return candidate


def _continuity_identity(item: dict[str, Any]) -> str:
    explicit = item.get("continuity_key")
    if explicit:
        return str(explicit)
    hidden = _json_object(item.get("hidden_detail_fields"))
    publication = _json_object(hidden.get("publication"))
    if publication.get("event_key"):
        return str(publication["event_key"])
    source_id = item.get("source_id")
    event_id = item.get("external_event_id")
    if source_id and event_id:
        return f"{source_id}:event:{event_id}"
    if item.get("topic_id"):
        return f"topic:{item['topic_id']}"
    if item.get("subject_type") and item.get("subject_id"):
        return f"subject:{item['subject_type']}:{item['subject_id']}"
    if item.get("claim_id"):
        return f"claim:{item['claim_id']}"
    headline = " ".join(str(item.get("headline") or "").lower().split())
    return f"headline:{headline}"


def _continuity_source_is_live(
    item: dict[str, Any], *, now: datetime
) -> bool:
    if str(item.get("section_id") or "") != "expectations-moved":
        return True
    fields = _json_object(item.get("display_fields"))
    deadline = _time(
        item.get("resolution_deadline_at")
        or fields.get("resolution_deadline")
        or fields.get("resolution_deadline_at")
    )
    if deadline is not None and deadline <= now:
        return False
    source_status = str(item.get("source_status") or "").lower()
    if source_status and source_status not in {"active", "open", "trading"}:
        return False
    topic_status = str(item.get("topic_status") or "").lower()
    return not topic_status or topic_status in {"active", "open"}


def _public_interest_allows_slot(
    item: dict[str, Any],
    *,
    now: datetime,
    slot_override: str | None = None,
) -> bool:
    """Prevent low-value Expectations from surviving through carry-forward."""

    if str(item.get("section_id") or "") != "expectations-moved":
        return True
    slot_id = slot_override or str(item.get("slot_id") or "live_feed")
    required_surface = {
        "lead": "hero",
        "secondary": "secondary",
        "main": "secondary",
        "live_feed": "live_feed",
        "digest": "live_feed",
        "utility": "explore",
        "archive": "explore",
    }.get(slot_id, "live_feed")
    return decision_from_render_candidate(item, as_of=now).allows(required_surface)


def _continuity_rank(
    item: dict[str, Any], *, visible: list[dict[str, Any]]
) -> tuple[Any, ...]:
    editorial = [
        candidate
        for candidate in visible
        if candidate.get("slot_id") in EDITORIAL_SLOTS
    ]
    secondary = [
        candidate for candidate in visible if candidate.get("slot_id") == "secondary"
    ]
    visible_sections = {
        str(candidate.get("section_id") or "default") for candidate in editorial
    }
    visible_families = {
        str(candidate.get("component_id") or "").split(".")[0]
        for candidate in secondary
    }
    section = str(item.get("section_id") or "default")
    family = str(item.get("component_id") or "").split(".")[0]
    source_slot_rank = {"lead": 0, "secondary": 1, "main": 2}.get(
        str(item.get("_continuity_source_slot") or "secondary"), 3
    )
    anchor = _time(
        item.get("materially_updated_at")
        or item.get("data_as_of")
        or item.get("assessed_at")
    )
    recency_rank = -(anchor.timestamp() if anchor is not None else 0.0)
    return (
        1 if section in visible_sections else 0,
        1 if family in visible_families else 0,
        1 if item.get("_continuity_freshness_state") == "aging" else 0,
        source_slot_rank,
        recency_rank,
        int(item.get("visual_priority") or 100),
        str(item.get("headline") or ""),
    )


def _continuity_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    carried = []
    for item in items:
        hidden = _json_object(item.get("hidden_detail_fields"))
        continuity = _json_object(hidden.get("publication_continuity"))
        if continuity:
            carried.append(continuity)
    return {
        "carried_items": len(carried),
        "secondary_target": CONTINUITY_SECONDARY_TARGET,
        "source_edition_ids": sorted(
            {
                str(item["source_edition_id"])
                for item in carried
                if item.get("source_edition_id")
            }
        ),
    }


def _lead(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if item.get("slot_id") == "lead":
            return {
                "component_id": item.get("component_id"),
                "headline": _headline(item),
            }
    return None


def _lead_set(items: list[dict[str, Any]]) -> list[str]:
    return [_headline(item) for item in items[:2]]


def _slots_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        slot: sum(1 for item in items if item.get("slot_id") == slot)
        for slot in SLOT_ORDER
    }


def _component_versions(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item["component_id"]): str(item.get("component_version") or "")
        for item in items
        if item.get("component_id")
    }


def _freshness_summary(
    items: list[dict[str, Any]], warnings: list[str]
) -> dict[str, Any]:
    states: dict[str, int] = {"current": 0, "aging": 0}
    sections: dict[str, dict[str, int]] = {}
    for item in items:
        state = str(item.get("freshness_state") or "current")
        states[state] = states.get(state, 0) + 1
        section = str(item.get("section_id") or "default")
        bucket = sections.setdefault(section, {"current": 0, "aging": 0})
        bucket[state] = bucket.get(state, 0) + 1
    return {
        "state": "aging" if states.get("aging") else "current",
        "items": states,
        "sections": sections,
        "retired_during_compile": sum(
            1 for warning in warnings if warning.startswith("retired ")
        ),
    }


def _headline(item: dict[str, Any]) -> str:
    fields = _json_object(item.get("display_fields"))
    for key in (
        "headline",
        "expectation_title",
        "rule_title",
        "work_title",
        "change_title",
        "event_title",
        "item_title",
        "topic",
        "primary_signal",
        "original_claim",
        "edition_date",
    ):
        if fields.get(key):
            return str(fields[key])
    return str(item.get("headline") or "Verified signal")


def _variant_for(slot_id: str) -> str:
    if slot_id == "lead":
        return "lead"
    if slot_id in {"live_feed", "digest", "utility"}:
        return "compact"
    return "standard"


def _claim_ids(item: dict[str, Any]) -> list[Any]:
    values = item.get("claim_ids")
    if isinstance(values, list):
        return values
    return [item["claim_id"]] if item.get("claim_id") else []


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(candidates):
        claim_id = item.get("claim_id")
        role = item.get("presentation_role") or (
            "index_echo" if item.get("slot_id") == "digest" else "primary"
        )
        key = (
            f"{claim_id}:{role}"
            if claim_id
            else f"{item.get('section_id')}:{item.get('component_id')}:{item.get('headline')}:{index}"
        )
        deduped[key] = item
    return list(deduped.values())


def _retain_within_editorial_cap(
    carried: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    section_cap: int,
) -> list[dict[str, Any]]:
    """Keep refreshed history without exceeding full-surface diversity.

    New candidates always own the available editorial capacity. Compact feed,
    digest, and utility items do not consume the cap and remain eligible for
    normal slot-capacity and freshness handling in ``EditionComposer``.
    """
    if not carried:
        return []

    new_candidates = _dedupe_candidates(candidates)
    new_keys = {
        _candidate_identity(item, index)
        for index, item in enumerate(new_candidates)
    }
    new_editorial_counts: dict[str, int] = {}
    for item in new_candidates:
        if item.get("slot_id") not in EDITORIAL_SLOTS:
            continue
        section = str(item.get("section_id") or "default")
        new_editorial_counts[section] = new_editorial_counts.get(section, 0) + 1

    retained: list[dict[str, Any]] = []
    carried_editorial_counts: dict[str, int] = {}
    for index, item in enumerate(carried):
        if _candidate_identity(item, index) in new_keys:
            continue
        if item.get("slot_id") not in EDITORIAL_SLOTS:
            retained.append(item)
            continue

        section = str(item.get("section_id") or "default")
        available = max(0, section_cap - new_editorial_counts.get(section, 0))
        used = carried_editorial_counts.get(section, 0)
        if used >= available:
            continue
        carried_editorial_counts[section] = used + 1
        retained.append(item)
    return retained


def _candidate_identity(item: dict[str, Any], index: int) -> str:
    claim_id = item.get("claim_id")
    role = item.get("presentation_role") or (
        "index_echo" if item.get("slot_id") == "digest" else "primary"
    )
    if claim_id:
        return f"{claim_id}:{role}"
    return (
        f"{item.get('section_id')}:{item.get('component_id')}:"
        f"{item.get('headline')}:{index}"
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
