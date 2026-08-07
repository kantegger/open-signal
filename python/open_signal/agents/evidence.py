"""Evidence bundle builder (spec §118, OS-016).

Packages a candidate's supporting material into an evidence_bundles row:
primary evidence (recent observation series), historical evidence (earlier
observations), counterexample candidates (bad-quality or reversal points),
computed metrics, a token budget estimate and a snapshot hash for
auditability/idempotency.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

EVIDENCE_BUNDLE_VERSION = "os-016"
DEFAULT_TOKEN_BUDGET = 4000
PRIMARY_WINDOW_ITEMS = 24


class EvidenceBundleBuilder:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ build
    def build_for_candidate(
        self,
        *,
        source_market_id: str,
        calculation: dict[str, Any],
        max_primary: int = PRIMARY_WINDOW_ITEMS,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> dict[str, Any]:
        """Build (and persist) the evidence bundle for one candidate.

        Returns {"bundle_id": str, "snapshot_hash": str, ...} for the caller.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT observed_at, probability, best_bid, best_ask, midpoint,
                           spread, data_quality_flags
                    FROM market_observations
                    WHERE source_market_id = :m
                    ORDER BY observed_at ASC
                    """
                ),
                {"m": source_market_id},
            ).fetchall()

        observations = [
            {
                "observed_at": r[0].isoformat(),
                "probability": float(r[1]) if r[1] is not None else None,
                "best_bid": float(r[2]) if r[2] is not None else None,
                "best_ask": float(r[3]) if r[3] is not None else None,
                "midpoint": float(r[4]) if r[4] is not None else None,
                "spread": float(r[5]) if r[5] is not None else None,
                "flags": list(r[6] or []),
            }
            for r in rows
        ]

        primary = observations[-max_primary:]
        historical = observations[:-max_primary][:: max(1, len(observations[:-max_primary]) // 8)][:16]
        counterexamples = [o for o in observations if o["flags"] or o["probability"] is None]

        metrics = {k: v for k, v in calculation.items() if k != "_calc_record_id"}

        bundle = {
            "source_market_id": source_market_id,
            "primary_evidence": primary,
            "historical_evidence": historical,
            "counterexample_candidates": counterexamples,
            "computed_metrics": metrics,
            "token_budget": token_budget,
            "token_estimate": self._estimate_tokens(primary, historical, counterexamples, metrics),
            "builder_version": EVIDENCE_BUNDLE_VERSION,
        }
        # snapshot hash covers content only (not timestamps) so identical
        # bundles produce identical hashes
        snapshot_hash = hashlib.sha256(
            json.dumps(bundle, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        bundle["built_at"] = datetime.now(timezone.utc).isoformat()

        with self.engine.begin() as conn:
            calc_ids = (
                [calculation["_calc_record_id"]]
                if calculation.get("_calc_record_id")
                else []
            )
            row = conn.execute(
                text(
                    """
                    INSERT INTO evidence_bundles
                      (primary_evidence, supporting_evidence, counter_evidence,
                       data_calculation_ids, source_coverage, snapshot_hash)
                    VALUES
                      (CAST(:primary AS jsonb), CAST(:supporting AS jsonb),
                       CAST(:counter AS jsonb), CAST(:calc AS uuid[]),
                       CAST(:coverage AS jsonb), :hash)
                    RETURNING id
                    """
                ),
                {
                    "primary": json.dumps(primary),
                    "supporting": json.dumps(historical),
                    "counter": json.dumps(counterexamples),
                    "calc": calc_ids,
                    "coverage": json.dumps({"source_markets": [source_market_id]}),
                    "hash": snapshot_hash,
                },
            ).fetchone()
            bundle_id = str(row[0])

        return {
            "bundle_id": bundle_id,
            "snapshot_hash": snapshot_hash,
            "primary_items": len(primary),
            "historical_items": len(historical),
            "counterexamples": len(counterexamples),
            "token_estimate": bundle["token_estimate"],
            "token_budget": token_budget,
        }

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _estimate_tokens(*parts: list[Any]) -> int:
        """Rough token estimate: ~4 chars per token for JSON-serialized text."""
        total_chars = 0
        for part in parts:
            total_chars += len(json.dumps(part, ensure_ascii=False, default=str))
        return max(1, total_chars // 4)
