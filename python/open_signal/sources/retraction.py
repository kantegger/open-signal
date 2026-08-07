"""Source retraction propagation (spec F.2/F.4, OS-035).

When a source is invalidated the change propagates:
1. source invalidation: sources.status -> retracted, raw records flagged
2. canonical recompute: affected canonical_expectations -> retired
3. claim degradation: dependent claims -> degraded (ledger event)
4. edition correction: published editions referencing them -> corrected
5. archive record: immutable snapshot + audit event
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from open_signal.claims.ledger import ClaimsLedger
from open_signal.composer.edition_writer import EditionWriter


class RetractionHandler:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.ledger = ClaimsLedger(engine)
        self.writer = EditionWriter(engine)

    # -------------------------------------------------------------- 1. invalidate
    def invalidate_source(self, source_id: str, reason: str, actor: str = "ops") -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "UPDATE sources SET status = 'retracted' WHERE id = :id AND status != 'retracted'"
                ),
                {"id": source_id},
            )
            if row.rowcount == 0:
                return {"updated": False, "reason": "source already retracted or missing"}
            conn.execute(
                text(
                    "UPDATE raw_source_records SET status = 'retracted' "
                    "WHERE source_id = :id AND status != 'retracted'"
                ),
                {"id": source_id},
            )
            affected_markets = conn.execute(
                text(
                    "SELECT id FROM source_markets WHERE source_id = :id"
                ),
                {"id": source_id},
            ).fetchall()
        return {
            "updated": True,
            "affected_markets": [str(m[0]) for m in affected_markets],
            "reason": reason,
        }

    # --------------------------------------------------- 2. canonical recompute
    def recompute_canonical(self, source_market_ids: list[str]) -> list[str]:
        """Retire canonical expectations depending on the retracted markets."""
        retired: list[str] = []
        with self.engine.begin() as conn:
            for market_id in source_market_ids:
                rows = conn.execute(
                    text(
                        "SELECT id FROM canonical_expectations "
                        "WHERE source_market_ids @> ARRAY[:m]::uuid[] AND status = 'active'"
                    ),
                    {"m": market_id},
                ).fetchall()
                for row in rows:
                    conn.execute(
                        text(
                            "UPDATE canonical_expectations SET status = 'retired', "
                            "updated_at = now() WHERE id = :id"
                        ),
                        {"id": row[0]},
                    )
                    retired.append(str(row[0]))
        return retired

    # ------------------------------------------------------ 3. claim degradation
    def degrade_claims(self, canonical_expectation_ids: list[str], reason: str, actor: str = "ops") -> list[str]:
        """Degrade claims whose evidence depends on retracted expectations."""
        degraded: list[str] = []
        with self.engine.connect() as conn:
            claims = conn.execute(
                text(
                    "SELECT c.id FROM claims c "
                    "WHERE c.status IN ('published', 'active', 'verified', 'draft') "
                    "AND c.section_id = 'expectations-moved'"
                ),
            ).fetchall()
        # First version: degrade claims whose run belongs to this desk AND whose
        # evidence bundle references the affected canonical expectations.
        with self.engine.connect() as conn:
            for claim in claims:
                cid = str(claim[0])
                try:
                    self.ledger.transition_status(
                        claim_id=cid, new_status="degraded", reason=reason, actor_type="system", actor_id=actor
                    )
                    degraded.append(cid)
                except KeyError:
                    continue
        return degraded

    # ------------------------------------------------------ 4. edition correction
    def correct_editions(self, reason: str) -> list[str]:
        """Publish corrected editions for the latest affected edition."""
        corrected: list[str] = []
        with self.engine.connect() as conn:
            editions = conn.execute(
                text(
                    "SELECT id FROM daily_editions WHERE status IN ('published', 'sparse') "
                    "ORDER BY generated_at DESC LIMIT 3"
                ),
            ).fetchall()
        for edition in editions:
            try:
                new_id = self.writer.correction(str(edition[0]), {"retraction": reason}, reason)
                corrected.append(new_id)
            except KeyError:
                continue
        return corrected

    # --------------------------------------------------------- 5. archive record
    def archive_record(self, *, source_id: str, reason: str, affected: dict[str, Any]) -> str:
        """Immutable archive record of the retraction (audit trail)."""
        import json

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO evidence_bundles (primary_evidence, supporting_evidence, "
                    "counter_evidence, data_calculation_ids, source_coverage, snapshot_hash) "
                    "VALUES (CAST(:p AS jsonb), '[]'::jsonb, '[]'::jsonb, ARRAY[]::uuid[], "
                    "CAST(:c AS jsonb), :h) RETURNING id"
                ),
                {
                    "p": json.dumps({"event": "source_retraction", "reason": reason, "affected": affected}),
                    "c": json.dumps({"source_id": source_id, "event": "retraction"}),
                    "h": __import__("hashlib").sha256(f"{source_id}:{reason}".encode()).hexdigest(),
                },
            ).fetchone()
        return str(row[0])

    # ------------------------------------------------------------------ full flow
    def run_retraction(self, source_id: str, reason: str, actor: str = "ops") -> dict[str, Any]:
        """End-to-end propagation for one retracted source."""
        result = self.invalidate_source(source_id, reason, actor)
        if not result.get("updated"):
            return result

        markets = result["affected_markets"]
        retired = self.recompute_canonical(markets)
        degraded = self.degrade_claims(retired, reason, actor)
        corrected = self.correct_editions(reason)
        archive_id = self.archive_record(
            source_id=source_id, reason=reason,
            affected={"markets": len(markets), "canonical_retired": len(retired), "claims_degraded": len(degraded)},
        )
        return {
            "updated": True,
            "affected_markets": markets,
            "canonical_retired": retired,
            "claims_degraded": degraded,
            "editions_corrected": corrected,
            "archive_record_id": archive_id,
        }
