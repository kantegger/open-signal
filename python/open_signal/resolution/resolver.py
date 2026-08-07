"""Resolution MVP (spec §107-110, OS-036).

Scope: binary expectation resolution and rule effective-by-date.
Produces Resolution Records, Brier contributions, and the Recently
Resolved component view.

First-version resolution logic:
- binary expectation: final market probability > 0.5 -> YES else NO
  (deterministic proxy; real settlement sources arrive later)
- rule: effective date reached -> outcome "effective"
- Brier: (predicted - observed)^2, predicted = claim confidence,
  observed = 1 (YES/effective) or 0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


class ResolutionError(Exception):
    pass


class Resolver:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ----------------------------------------------------- binary expectations
    def resolve_binary_expectation(
        self,
        *,
        claim_id: str,
        resolution_contract_id: str,
        final_probability: float,
        resolution_date: datetime | None = None,
        method: str = "market_final_probability",
    ) -> dict[str, Any]:
        """Resolve a binary expectation; writes Resolution Record + Brier."""
        resolution_date = resolution_date or datetime.now(timezone.utc)
        outcome = "yes" if final_probability > 0.5 else "no"
        observed = 1.0 if outcome == "yes" else 0.0

        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT confidence, status, run_id FROM claims WHERE id = :id"
                ),
                {"id": claim_id},
            ).fetchone()
            contract = conn.execute(
                text(
                    "SELECT id, scoring_rule_id FROM resolution_contracts WHERE id = :id"
                ),
                {"id": resolution_contract_id},
            ).fetchone()
        if claim is None:
            raise ResolutionError(f"claim {claim_id} not found")
        if contract is None:
            raise ResolutionError(f"resolution contract {resolution_contract_id} not found")
        if claim[1] == "resolved":
            return {"already_resolved": True, "claim_id": claim_id}

        predicted = float(claim[0]) if claim[0] is not None else 0.5
        brier = round((predicted - observed) ** 2, 6)

        with self.engine.begin() as conn:
            record = conn.execute(
                text(
                    """
                    INSERT INTO resolution_records
                      (claim_id, resolution_contract_id, outcome, numeric_outcome,
                       component_scores, final_score, resolution_source_record_ids,
                       calculation_record_ids, resolver_run_ids, resolved_at, status, resolution_version)
                    VALUES
                      (:claim, :contract, :outcome, :numeric, CAST(:scores AS jsonb),
                       :final, ARRAY[]::uuid[], ARRAY[]::uuid[], ARRAY[]::uuid[], :at, 'resolved', '1.0.0')
                    RETURNING id
                    """
                ),
                {
                    "claim": claim_id,
                    "contract": resolution_contract_id,
                    "outcome": outcome,
                    "numeric": observed,
                    "scores": __import__("json").dumps({"brier": brier, "method": method, "final_probability": final_probability}),
                    "final": 1.0 - brier,
                    "at": resolution_date,
                },
            ).fetchone()
            conn.execute(
                text("UPDATE claims SET status = 'resolved' WHERE id = :id"),
                {"id": claim_id},
            )

        return {
            "resolution_record_id": str(record[0]),
            "claim_id": claim_id,
            "outcome": outcome,
            "brier": brier,
            "predicted_probability": predicted,
            "observed": observed,
            "resolved_at": resolution_date.isoformat(),
        }

    # ------------------------------------------------------ rule effective-by-date
    def resolve_rule_effective_by_date(
        self,
        *,
        rule_id: str,
        claim_id: str,
        resolution_contract_id: str,
        effective_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Record that a rule reached its effective date."""
        effective_at = effective_at or datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            record = conn.execute(
                text(
                    """
                    INSERT INTO resolution_records
                      (claim_id, resolution_contract_id, outcome, numeric_outcome,
                       component_scores, final_score, resolution_source_record_ids,
                       calculation_record_ids, resolver_run_ids, resolved_at, status, resolution_version)
                    VALUES
                      (:claim, :contract, 'effective', 1.0, CAST(:scores AS jsonb),
                       1.0, ARRAY[]::uuid[], ARRAY[]::uuid[], ARRAY[]::uuid[], :at, 'resolved', '1.0.0')
                    RETURNING id
                    """
                ),
                {
                    "claim": claim_id,
                    "contract": resolution_contract_id,
                    "scores": __import__("json").dumps({"rule_id": rule_id, "event": "effective_by_date"}),
                    "at": effective_at,
                },
            ).fetchone()
            conn.execute(
                text("UPDATE claims SET status = 'resolved' WHERE id = :id"),
                {"id": claim_id},
            )
        return {"resolution_record_id": str(record[0]), "claim_id": claim_id, "outcome": "effective"}

    # ------------------------------------------------------------ read views
    def recently_resolved(self, limit: int = 10) -> list[dict[str, Any]]:
        """Recently Resolved component data."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT rr.id, rr.outcome, rr.final_score, rr.resolved_at,
                           c.public_statement, c.desk_id,
                           rr.component_scores->>'brier' AS brier
                    FROM resolution_records rr
                    JOIN claims c ON c.id = rr.claim_id
                    ORDER BY rr.resolved_at DESC LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {
                "resolution_record_id": str(r[0]),
                "outcome": r[1],
                "final_score": float(r[2]) if r[2] is not None else None,
                "resolved_at": r[3].isoformat(),
                "statement": r[4],
                "desk_id": r[5],
                "brier": float(r[6]) if r[6] is not None else None,
            }
            for r in rows
        ]
