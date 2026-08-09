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

    def build(self, claim_id: str, *, locale: str = "en") -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT id, claim_type, public_statement, structured_proposition, "
                    "confidence, confidence_label, epistemic_status, status, desk_id, "
                    "agent_lineage_id, model_version, charter_version, evidence_bundle_id, "
                    "issued_at, valid_from, valid_until, updated_at, resolution_contract_id "
                    "FROM claims WHERE id = :id"
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
                        "data_calculation_ids, source_coverage, unresolved_questions, "
                        "known_limitations, snapshot_hash "
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

            resolution = None
            if claim[17]:
                resolution = conn.execute(
                    text(
                        "SELECT id, issued_at, evaluation_start_at, evaluation_deadline, "
                        "resolution_predicate, scoring_rule_id, partial_credit_policy, "
                        "ambiguity_policy, missing_data_policy, locked_at, lock_hash, status "
                        "FROM resolution_contracts WHERE id = :id"
                    ),
                    {"id": claim[17]},
                ).fetchone()

            topic = conn.execute(
                text(
                    """
                    SELECT ce.id, ce.canonical_question, ce.event_type,
                           ce.resolution_deadline_at, ce.updated_at
                    FROM section_instances si
                    JOIN canonical_expectations ce
                      ON ce.source_market_ids @> ARRAY[si.subject_id]::uuid[]
                    WHERE si.claim_id = :claim
                      AND si.subject_type = 'source_market'
                    ORDER BY ce.updated_at DESC LIMIT 1
                    """
                ),
                {"claim": claim_id},
            ).fetchone()

        return self._assemble(
            claim,
            versions,
            evidence,
            lineage,
            resolution,
            topic,
            locale=locale,
        )

    # ------------------------------------------------------------------ view
    def _assemble(
        self,
        claim: Any,
        versions: list[Any],
        evidence: Any | None,
        lineage: Any | None,
        resolution: Any | None,
        topic: Any | None,
        *,
        locale: str,
    ) -> dict[str, Any]:
        proposition = claim[3] or {}
        localized, published_locale = self._localized(proposition, locale)
        observation = localized.get("observation") or claim[2]
        analysis_summary = localized.get("analysis")
        assessment_summary = localized.get("assessment")
        return {
            "claim": {
                "id": str(claim[0]),
                "claim_type": claim[1],
                "public_statement": claim[2],
                "status": claim[7],
                "desk_id": claim[8],
                "issued_at": claim[13].isoformat(),
                "valid_from": claim[14].isoformat() if claim[14] else None,
                "valid_until": claim[15].isoformat() if claim[15] else None,
                "materially_updated_at": claim[16].isoformat() if claim[16] else None,
            },
            # 1. Observation
            "observation": observation,
            # 2. Analysis
            "analysis": {
                "summary": analysis_summary,
                "structured_proposition": proposition,
                "predicate": proposition.get("predicate"),
                "operator": proposition.get("operator"),
                "value": proposition.get("value"),
            },
            # 3. Assessment (versions are authoritative; use the latest)
            "assessment": {
                "summary": assessment_summary,
                "confidence": (
                    float(versions[-1][4])
                    if versions and versions[-1][4] is not None
                    else float(claim[4])
                    if claim[4] is not None
                    else None
                ),
                "confidence_label": claim[5],
                "epistemic_status": claim[6],
                "model_version": claim[10],
                "charter_version": claim[11],
            },
            # 4. Evidence
            "evidence": self._evidence_block(evidence, "primary_evidence"),
            "supporting_evidence": self._evidence_block(
                evidence, "supporting_evidence"
            ),
            # 5. Counterevidence
            "counterevidence": self._evidence_block(evidence, "counter_evidence"),
            "uncertainty": {
                "unresolved_questions": list(evidence[5] or []) if evidence else [],
                "known_limitations": list(evidence[6] or []) if evidence else [],
            },
            "method": {
                "calculation_ids": [str(value) for value in (evidence[3] or [])]
                if evidence
                else [],
                "source_coverage": evidence[4] if evidence else {},
            },
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
            "resolution_contract": self._resolution_contract(resolution),
            "topic": (
                {
                    "id": str(topic[0]),
                    "title": topic[1],
                    "event_type": topic[2],
                    "resolution_deadline_at": topic[3].isoformat(),
                    "updated_at": topic[4].isoformat(),
                }
                if topic
                else None
            ),
            "locale": {
                "requested": locale,
                "published": published_locale,
                "fallback_used": published_locale != locale,
                "translation_provenance": None,
            },
        }

    @staticmethod
    def _evidence_block(evidence: Any | None, column: str) -> dict[str, Any]:
        if evidence is None:
            return {"items": [], "snapshot_hash": None}
        idx = {"primary_evidence": 0, "supporting_evidence": 1, "counter_evidence": 2}[
            column
        ]
        return {
            "items": evidence[idx] if isinstance(evidence[idx], list) else [],
            "snapshot_hash": evidence[7],
        }

    @staticmethod
    def _localized(
        proposition: dict[str, Any], locale: str
    ) -> tuple[dict[str, Any], str]:
        requested = proposition.get(locale)
        if isinstance(requested, dict):
            return requested, locale
        english = proposition.get("en")
        if isinstance(english, dict):
            return english, "en"
        return proposition, "und"

    @staticmethod
    def _resolution_contract(resolution: Any | None) -> dict[str, Any] | None:
        if resolution is None:
            return None
        return {
            "id": str(resolution[0]),
            "issued_at": resolution[1].isoformat(),
            "evaluation_start_at": resolution[2].isoformat(),
            "evaluation_deadline": resolution[3].isoformat(),
            "resolution_predicate": resolution[4],
            "scoring_rule_id": resolution[5],
            "partial_credit_policy": resolution[6],
            "ambiguity_policy": resolution[7],
            "missing_data_policy": resolution[8],
            "locked_at": resolution[9].isoformat(),
            "lock_hash": resolution[10],
            "status": resolution[11],
        }
