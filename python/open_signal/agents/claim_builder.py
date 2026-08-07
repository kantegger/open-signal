"""Deterministic claim construction (spec §29, §32.6, OS-011).

Turns candidate-detection output into:
- an Observation Claim (claim_type=derived_observation)
- a Section Instance (with Claim Bundle)
- a Probability Move render candidate

No LLM is involved in this path (spec OS-011: "暂不运行复杂 Agent").
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

SECTION_ID = "expectations-moved"
CAPABILITY_ID = "expectation.probability-change"
DESK_ID = "expectations-desk"
LINEAGE_ID = "deterministic-obs-v1"
INSTITUTION_ID = "open-signal"
MODEL_VERSION = "deterministic"
CHARTER_VERSION = "os-011"
EVIDENCE_BUNDLE_VERSION = "os-011"


class DeterministicClaimBuilder:
    def __init__(self, engine: Any, *, desk_id: str = DESK_ID) -> None:
        self.engine = engine
        self.desk_id = desk_id

    # ------------------------------------------------------------- primitives
    def ensure_lineage(self) -> None:
        """Create the deterministic observation lineage if missing."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_lineages
                      (id, desk_id, name, foundation_model, model_version,
                       charter_id, charter_version, toolset_version,
                       context_builder_version, status, activated_at)
                    VALUES
                      (:id, :desk, 'Deterministic Observation', 'n/a', :model,
                       'os-011', :charter, 'n/a', 'n/a', 'active', now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": LINEAGE_ID, "desk": self.desk_id, "model": MODEL_VERSION, "charter": CHARTER_VERSION},
            )

    def _create_run(self, conn: Any, candidate_id: str | None, output: dict[str, Any]) -> str:
        row = conn.execute(
            text(
                """
                INSERT INTO investigation_runs
                  (desk_id, section_id, capability_id, candidate_id,
                   agent_lineage_id, model_version, charter_version,
                   started_at, completed_at, status,
                   total_input_tokens, total_output_tokens, total_tool_calls,
                   estimated_cost_usd, output_judgment)
                VALUES
                  (:desk, :section, :capability, :candidate, :lineage,
                   :model, :charter, now(), now(), 'completed',
                   0, 0, 0, 0.0, CAST(:output AS jsonb))
                RETURNING id
                """
            ),
            {
                "desk": self.desk_id,
                "section": SECTION_ID,
                "capability": CAPABILITY_ID,
                "candidate": candidate_id,
                "lineage": LINEAGE_ID,
                "model": MODEL_VERSION,
                "charter": CHARTER_VERSION,
                "output": json.dumps(output),
            },
        ).fetchone()
        return str(row[0])

    def _create_evidence_bundle(self, conn: Any, source_market_id: str, calculation: dict[str, Any]) -> str:
        row = conn.execute(
            text(
                """
                INSERT INTO evidence_bundles
                  (primary_evidence, supporting_evidence, counter_evidence,
                   data_calculation_ids, source_coverage, snapshot_hash)
                VALUES
                  (CAST(:primary AS jsonb), '[]'::jsonb, '[]'::jsonb,
                   ARRAY[:calc]::uuid[], CAST(:coverage AS jsonb), :hash)
                RETURNING id
                """
            ),
            {
                "primary": json.dumps(
                    [
                        {
                            "source_market_id": source_market_id,
                            "observation_series_size": calculation.get("series_size", 0),
                            "metric": {k: v for k, v in calculation.items() if k != "eligible"},
                        }
                    ]
                ),
                "calc": calculation.get("_calc_record_id"),
                "coverage": json.dumps({"source_markets": [source_market_id]}),
                "hash": uuid.uuid4().hex,
            },
        ).fetchone()
        return str(row[0])

    # ------------------------------------------------------------------ build
    def build_from_candidate(
        self,
        *,
        source_market_id: str,
        canonical_expectation_id: str,
        calculation: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build claim + section instance + render candidate for one candidate.

        ``calculation`` should carry a ``_calc_record_id`` key (set by
        CandidateDetector.record_calculation) plus the metric fields.
        """
        now = now or datetime.now(timezone.utc)
        self.ensure_lineage()

        with self.engine.begin() as conn:
            # canonical expectation context
            row = conn.execute(
                text(
                    "SELECT canonical_question, source_market_ids "
                    "FROM canonical_expectations WHERE id = :id"
                ),
                {"id": canonical_expectation_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"canonical expectation {canonical_expectation_id} not found")
            question, market_ids = row
            if source_market_id not in [str(m) for m in market_ids]:
                raise ValueError("source market not part of the canonical expectation")

            run_id = self._create_run(conn, source_market_id, calculation)
            calculation.get("_calc_record_id")
            evidence_bundle_id = self._create_evidence_bundle(conn, source_market_id, calculation)

            direction = calculation.get("direction", 0)
            operator = "increased" if direction > 0 else ("decreased" if direction < 0 else "equals")
            proposition = {
                "subject_ids": [source_market_id],
                "predicate": "probability",
                "operator": operator,
                "value": round(abs(calculation.get("delta_24h", 0.0)), 4),
                "unit": "percentage_points",
                "baseline": {
                    "window": "24h",
                    "delta_24h": calculation.get("delta_24h"),
                    "delta_1h": calculation.get("delta_1h"),
                },
                "qualifiers": {},
                "proposition_version": "0.1.0",
            }
            statement = (
                f"{question} 的 YES 概率在过去 24 小时"
                f"{'上升' if direction > 0 else ('下降' if direction < 0 else '持平')} "
                f"{abs(calculation.get('delta_24h', 0.0)):.1f} 个百分点"
                f"（现 {calculation.get('delta_24h')}，数据完整度 {calculation.get('data_completeness', 0)}）"
            )

            claim_row = conn.execute(
                text(
                    """
                    INSERT INTO claims
                      (institution_id, desk_id, agent_lineage_id, model_version,
                       charter_version, run_id, section_id, capability_id,
                       claim_type, public_statement, structured_proposition,
                       confidence, confidence_label, epistemic_status,
                       evidence_bundle_id, evidence_snapshot_hash,
                       issued_at, status)
                    VALUES
                      (:inst, :desk, :lineage, :model, :charter, :run,
                       :section, :capability, 'derived_observation',
                       :statement, CAST(:prop AS jsonb),
                       :confidence, 'high', 'derived',
                       :eb, :hash, :issued, 'draft')
                    RETURNING id
                    """
                ),
                {
                    "inst": INSTITUTION_ID,
                    "desk": self.desk_id,
                    "lineage": LINEAGE_ID,
                    "model": MODEL_VERSION,
                    "charter": CHARTER_VERSION,
                    "run": run_id,
                    "section": SECTION_ID,
                    "capability": CAPABILITY_ID,
                    "statement": statement,
                    "prop": json.dumps(proposition),
                    "confidence": 0.9,
                    "eb": evidence_bundle_id,
                    "hash": uuid.uuid4().hex,
                    "issued": now,
                },
            ).fetchone()
            claim_id = str(claim_row[0])

            # version row + current_version_id
            conn.execute(
                text(
                    """
                    INSERT INTO claim_versions
                      (claim_id, version_number, public_statement,
                       structured_proposition, confidence, evidence_bundle_id,
                       change_type, change_reason, created_at)
                    VALUES
                      (:cid, 1, :statement, CAST(:prop AS jsonb), 0.9, :eb,
                       'initial', 'deterministic observation', now())
                    RETURNING id
                    """
                ),
                {"cid": claim_id, "statement": statement, "prop": json.dumps(proposition), "eb": evidence_bundle_id},
            )
            conn.execute(
                text(
                    """
                    UPDATE claims SET current_version_id = (
                      SELECT id FROM claim_versions WHERE claim_id = :cid
                      ORDER BY version_number DESC LIMIT 1
                    ) WHERE id = :cid
                    """
                ),
                {"cid": claim_id},
            )

            # section instance + claim bundle
            si_row = conn.execute(
                text(
                    """
                    INSERT INTO section_instances
                      (section_id, capability_id, subject_id, subject_type, claim_id)
                    VALUES (:section, :capability, :subject, 'source_market', :claim)
                    RETURNING id
                    """
                ),
                {"section": SECTION_ID, "capability": CAPABILITY_ID, "subject": source_market_id, "claim": claim_id},
            ).fetchone()
            section_instance_id = str(si_row[0])

            conn.execute(
                text(
                    """
                    INSERT INTO claim_bundles
                      (section_instance_id, section_id, desk_id, headline_claim_id, status)
                    VALUES (:si, :section, :desk, :claim, 'draft')
                    """
                ),
                {"si": section_instance_id, "section": SECTION_ID, "desk": self.desk_id, "claim": claim_id},
            )

        render_candidate = self._render_candidate(
            question, source_market_id, calculation, now
        )
        return {
            "claim_id": claim_id,
            "section_instance_id": section_instance_id,
            "run_id": run_id,
            "render_candidate": render_candidate,
        }

    # -------------------------------------------------------------- rendering
    def _render_candidate(
        self, question: str, source_market_id: str, calculation: dict[str, Any], now: datetime
    ) -> dict[str, Any]:
        """Probability Move render fields (spec §52.1)."""
        return {
            "component_id": "time-series.probability-move",
            "component_version": "1.0.0",
            "component_variant": "standard",
            "slot_id": "secondary",
            "headline": question,
            "dek": None,
            "display_fields": {
                "expectationTitle": question,
                "currentProbability": None,  # filled by observation query
                "startProbability": None,
                "deltaPercentagePoints": round(calculation.get("delta_24h", 0.0), 4),
                "window": "24h",
                "series": [],
                "sourceName": "Polymarket",
                "updatedAt": now.isoformat(),
            },
            "hidden_detail_fields": {
                "calculation": {k: v for k, v in calculation.items() if k != "_calc_record_id"},
            },
            "evidence_bundle_id": None,
            "visual_priority": 2,
            "mobile_priority": 2,
            "generated_by": f"os-011/{CHARTER_VERSION}",
            "approved_by_verification_run_id": None,
        }
