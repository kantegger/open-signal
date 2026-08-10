"""Expectation canonicalizer (spec §100, OS-009).

Builds single-source Canonical Expectations from Source Markets:
- binary outcomes only (exactly two outcomes, first is YES)
- explicit deadline (ends_at set and in the future)
- explicit YES direction (first outcome label is a positive/yes form)

Cross-source equivalence merging is out of scope (later milestone).
Idempotent: a source market already mapped to a canonical expectation is
skipped (or updated) rather than duplicated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

YES_LABELS = {"yes", "true", "for", "pass", "approve", "in"}

CANONICALIZATION_VERSION = "0.1.0"


class CanonicalizationError(Exception):
    """Raised when a source market cannot be canonicalized."""


class ExpectationCanonicalizer:
    def __init__(self, engine: Any, version: str = CANONICALIZATION_VERSION) -> None:
        self.engine = engine
        self.version = version

    # --------------------------------------------------------------- canonicalize
    def canonicalize_source_market(
        self,
        source_market_id: str,
        *,
        question: str,
        outcome_labels: list[str],
        ends_at: str | None,
        event_type: str | None = None,
        rules_text: str | None = None,
        payload: dict[str, Any] | None = None,
        force: bool = False,
    ) -> str | None:
        """Create/update the canonical expectation for one source market.

        Returns the canonical expectation id, or None if the market is not
        eligible (non-binary, missing deadline, no YES direction).
        """
        if len(outcome_labels) != 2:
            return None
        if not outcome_labels[0].strip().lower() in YES_LABELS:
            return None
        if not ends_at:
            return None

        existing = self._find_by_market(source_market_id)
        if existing and not force:
            return str(existing)

        canonical_question = question
        resolution_rule_summary = rules_text or question
        resolution_rule_hash = hashlib.sha256(
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

        with self.engine.begin() as conn:
            if existing:
                conn.execute(
                    text(
                        """
                        UPDATE canonical_expectations SET
                          updated_at = CASE
                            WHEN canonical_question IS DISTINCT FROM :q
                              OR event_type IS DISTINCT FROM :et
                              OR resolution_deadline_at IS DISTINCT FROM :deadline
                              OR resolution_rule_summary IS DISTINCT FROM :summary
                              OR resolution_rule_hash IS DISTINCT FROM :hash
                              OR source_market_ids IS DISTINCT FROM ARRAY[:m]::uuid[]
                              OR status IS DISTINCT FROM 'active'
                              OR canonicalization_version IS DISTINCT FROM :ver
                            THEN now()
                            ELSE updated_at
                          END,
                          canonical_question = :q,
                          event_type = :et,
                          resolution_deadline_at = :deadline,
                          resolution_rule_summary = :summary,
                          resolution_rule_hash = :hash,
                          source_market_ids = ARRAY[:m]::uuid[],
                          status = 'active',
                          canonicalization_version = :ver
                        WHERE id = :id
                        """
                    ),
                    {
                        "q": canonical_question,
                        "et": event_type or "general",
                        "deadline": ends_at,
                        "summary": resolution_rule_summary,
                        "hash": resolution_rule_hash,
                        "m": source_market_id,
                        "ver": self.version,
                        "id": existing,
                    },
                )
                return str(existing)

            row = conn.execute(
                text(
                    """
                    INSERT INTO canonical_expectations
                      (canonical_question, subject_entity_ids, event_type,
                       outcome_type, resolution_deadline_at,
                       resolution_rule_summary, resolution_rule_hash,
                       source_market_ids, status, canonicalization_version)
                    VALUES
                      (:q, '{}', :et, 'binary', :deadline,
                       :summary, :hash, ARRAY[:m]::uuid[], 'active', :ver)
                    RETURNING id
                    """
                ),
                {
                    "q": canonical_question,
                    "et": event_type or "general",
                    "deadline": ends_at,
                    "summary": resolution_rule_summary,
                    "hash": resolution_rule_hash,
                    "m": source_market_id,
                    "ver": self.version,
                },
            ).fetchone()
            return str(row[0])

    # --------------------------------------------------------------- batch
    def canonicalize_all_eligible(self, limit: int = 500) -> dict[str, int]:
        """Scan source_markets without a canonical expectation and
        canonicalize eligible ones. Returns counts."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT sm.id, sm.question, sm.outcome_labels, sm.ends_at,
                           sm.status, rs.payload
                    FROM source_markets sm
                    LEFT JOIN raw_source_records rs ON rs.id = sm.raw_source_record_id
                    WHERE sm.status = 'active'
                    ORDER BY sm.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()

        created = skipped = 0
        for row in rows:
            market_id = str(row[0])
            if self._find_by_market(market_id):
                skipped += 1
                continue
            payload = row[5] if isinstance(row[5], dict) else {}
            outcome_labels = row[2] or ["Yes", "No"]
            event_type = "general"
            if payload.get("tags"):
                tag = payload["tags"][0]
                event_type = tag.get("slug") or tag.get("label") or "general"

            result = self.canonicalize_source_market(
                market_id,
                question=row[1],
                outcome_labels=outcome_labels,
                ends_at=row[3],
                event_type=event_type,
                rules_text=payload.get("rules") or payload.get("cypher"),
                payload=payload,
            )
            if result:
                created += 1
            else:
                skipped += 1
        return {"created": created, "skipped": skipped}

    # ---------------------------------------------------------------- helpers
    def _find_by_market(self, source_market_id: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM canonical_expectations "
                    "WHERE source_market_ids @> ARRAY[:m]::uuid[] LIMIT 1"
                ),
                {"m": source_market_id},
            ).fetchone()
        return str(row[0]) if row else None
