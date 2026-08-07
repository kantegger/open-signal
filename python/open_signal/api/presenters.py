"""Public claim page presenter (spec §171, OS-030).

Aggregates the read-only view for public display: Observation, Analysis,
Assessment, Evidence, Counterevidence, Agent lineage, Claim ID, Version
history. Never mutates the ledger.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


class ClaimPagePresenter:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(self, claim_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT id, claim_type, public_statement, structured_proposition, "
                    "confidence, confidence_label, epistemic_status, status, desk_id, "
                    "agent_lineage_id, model_version, charter_version, evidence_bundle_id, "
                    "issued_at FROM claims WHERE id = :id"
                ),
                {"id": claim_id},
            ).fetchone()
            if claim is None:
                return None

            versions = conn.execute(
                text(
                    "SELECT version_number, public_statement, change_type, change_reason, "
                    "confidence, created_at FROM claim_versions WHERE claim_id = :id "
                    "ORDER BY version_number ASC"
                ),
                {"id": claim_id},
            ).fetchall()

            evidence = None
            if claim[12]:
                evidence = conn.execute(
                    text(
                        "SELECT primary_evidence, supporting_evidence, counter_evidence, "
                        "data_calculation_ids, source_coverage, snapshot_hash "
                        "FROM evidence_bundles WHERE id = :id"
                    ),
                    {"id": claim[12]},
                ).fetchone()

            lineage = conn.execute(
                text(
                    "SELECT l.desk_id, l.name, l.foundation_model, l.model_version, "
                    "l.charter_id, l.charter_version, l.status "
                    "FROM agent_lineages l WHERE l.id = :id"
                ),
                {"id": claim[9]},
            ).fetchone()

        return self._assemble(claim, versions, evidence, lineage)

    # ------------------------------------------------------------------ view
    def _assemble(self, claim: Any, versions: list[Any], evidence: Any | None, lineage: Any | None) -> dict[str, Any]:
        proposition = claim[3] or {}
        return {
            "claim": {
                "id": str(claim[0]),
                "claim_type": claim[1],
                "public_statement": claim[2],
                "status": claim[7],
                "desk_id": claim[8],
                "issued_at": claim[13].isoformat(),
            },
            # 1. Observation
            "observation": claim[2],
            # 2. Analysis
            "analysis": {
                "structured_proposition": proposition,
                "predicate": proposition.get("predicate"),
                "operator": proposition.get("operator"),
                "value": proposition.get("value"),
            },
            # 3. Assessment (versions are authoritative; use the latest)
            "assessment": {
                "confidence": float(versions[-1][4]) if versions and versions[-1][4] is not None else None,
                "confidence_label": claim[5],
                "epistemic_status": claim[6],
                "model_version": claim[10],
                "charter_version": claim[11],
            },
            # 4. Evidence
            "evidence": self._evidence_block(evidence, "primary_evidence"),
            # 5. Counterevidence
            "counterevidence": self._evidence_block(evidence, "counter_evidence"),
            # 6. Agent lineage
            "agent_lineage": (
                {
                    "lineage_id": claim[9],
                    "desk_id": lineage[0] if lineage else None,
                    "name": lineage[1] if lineage else None,
                    "foundation_model": lineage[2] if lineage else None,
                    "model_version": lineage[3] if lineage else None,
                    "charter_id": lineage[4] if lineage else None,
                    "charter_version": lineage[5] if lineage else None,
                    "status": lineage[6] if lineage else None,
                }
                if lineage
                else {"lineage_id": claim[9]}
            ),
            # 8. Version history
            "version_history": [
                {
                    "version_number": v[0],
                    "public_statement": v[1],
                    "change_type": v[2],
                    "change_reason": v[3],
                    "confidence": float(v[4]) if v[4] is not None else None,
                    "created_at": v[5].isoformat(),
                }
                for v in versions
            ],
        }

    @staticmethod
    def _evidence_block(evidence: Any | None, column: str) -> dict[str, Any]:
        if evidence is None:
            return {"items": [], "snapshot_hash": None}
        idx = {"primary_evidence": 0, "supporting_evidence": 1, "counter_evidence": 2}[column]
        return {
            "items": evidence[idx] if isinstance(evidence[idx], list) else [],
            "snapshot_hash": evidence[5],
        }
