"""Deterministic claim construction (spec §29, §32.6, OS-011).

Turns candidate-detection output into:
- an Observation Claim (claim_type=derived_observation)
- a Section Instance (with Claim Bundle)
- a Probability Move render candidate

No LLM is involved in this path (spec OS-011: "暂不运行复杂 Agent").
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from open_signal.derived.series_contract import market_series_snapshot

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

    def _create_evidence_bundle(
        self,
        conn: Any,
        source_market_id: str,
        calculation: dict[str, Any],
        snapshot_hash: str,
    ) -> str:
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
                "hash": snapshot_hash,
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

        stable_calculation = {
            key: calculation.get(key)
            for key in (
                "delta_1h",
                "delta_24h",
                "delta_7d",
                "direction",
                "persistence",
                "acceleration",
                "reversal",
                "data_quality",
            )
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(
                {
                    "source_market_id": source_market_id,
                    "canonical_expectation_id": canonical_expectation_id,
                    "calculation": stable_calculation,
                    "builder_version": EVIDENCE_BUNDLE_VERSION,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        idempotency_key = f"expectation:{snapshot_hash}"

        with self.engine.connect() as conn:
            context = conn.execute(
                text(
                    "SELECT canonical_question, source_market_ids "
                    "FROM canonical_expectations WHERE id = :id"
                ),
                {"id": canonical_expectation_id},
            ).fetchone()
            existing = conn.execute(
                text(
                    """
                    SELECT c.id, si.id, c.run_id, c.evidence_bundle_id
                    FROM claims c
                    LEFT JOIN section_instances si ON si.claim_id = c.id
                    WHERE c.idempotency_key = :key
                    ORDER BY si.created_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"key": idempotency_key},
            ).fetchone()
        if context is None:
            raise ValueError(
                f"canonical expectation {canonical_expectation_id} not found"
            )
        question, market_ids = context
        if source_market_id not in [str(m) for m in market_ids]:
            raise ValueError("source market not part of the canonical expectation")
        if existing is not None:
            return {
                "claim_id": str(existing[0]),
                "section_instance_id": str(existing[1]) if existing[1] else None,
                "run_id": str(existing[2]),
                "render_candidate": self._render_candidate(
                    question,
                    source_market_id,
                    calculation,
                    now,
                    evidence_bundle_id=str(existing[3]),
                ),
                "created": False,
                "idempotency_key": idempotency_key,
            }

        with self.engine.begin() as conn:
            run_id = self._create_run(conn, source_market_id, calculation)
            evidence_bundle_id = self._create_evidence_bundle(
                conn,
                source_market_id,
                calculation,
                snapshot_hash,
            )

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
                f"The YES probability for {question} "
                f"{'increased' if direction > 0 else ('decreased' if direction < 0 else 'was unchanged')} "
                f"by {abs(calculation.get('delta_24h', 0.0)):.1f} percentage points "
                "over the past 24 hours."
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
                       idempotency_key, issued_at, valid_from, valid_until,
                       status)
                    VALUES
                      (:inst, :desk, :lineage, :model, :charter, :run,
                       :section, :capability, 'derived_observation',
                       :statement, CAST(:prop AS jsonb),
                       :confidence, 'high', 'derived',
                       :eb, :hash, :key, :issued, :issued, :valid_until,
                       'draft')
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
                    "hash": snapshot_hash,
                    "key": idempotency_key,
                    "issued": now,
                    "valid_until": now + timedelta(hours=72),
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
            question,
            source_market_id,
            calculation,
            now,
            evidence_bundle_id=evidence_bundle_id,
        )
        return {
            "claim_id": claim_id,
            "section_instance_id": section_instance_id,
            "run_id": run_id,
            "render_candidate": render_candidate,
            "created": True,
            "idempotency_key": idempotency_key,
        }

    # -------------------------------------------------------------- rendering
    def _render_candidate(
        self,
        question: str,
        source_market_id: str,
        calculation: dict[str, Any],
        now: datetime,
        *,
        evidence_bundle_id: str | None = None,
    ) -> dict[str, Any]:
        """Probability Move render fields (spec §52.1)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT observed_at, probability
                    FROM market_observations
                    WHERE source_market_id = :market
                      AND probability IS NOT NULL
                      AND observed_at <= :captured_at
                      AND observed_at >= :captured_at - interval '7 days'
                    ORDER BY observed_at
                    """
                ),
                {"market": source_market_id, "captured_at": now},
            ).fetchall()
        series_snapshot = market_series_snapshot(
            [(row[0], row[1]) for row in rows],
            captured_at=now,
        )
        series = [
            {"timestamp": point[0], "probability": point[1]}
            for point in series_snapshot["points"]
        ]
        current = float(series[-1]["probability"]) if series else None
        delta = float(calculation.get("delta_24h", 0.0))
        start = current - delta / 100 if current is not None else None
        observation = (
            f"YES moved {'up' if delta > 0 else ('down' if delta < 0 else 'sideways')} "
            f"by {abs(delta):.1f} percentage points over 24 hours."
        )
        return {
            "component_id": "time-series.probability-move",
            "component_version": "1.0.0",
            "component_variant": "standard",
            "slot_id": "secondary",
            "headline": question,
            "dek": None,
            "display_fields": {
                "expectation_title": question,
                "current_probability": current,
                "start_probability": start,
                "delta_percentage_points": round(delta, 4),
                "window": "24h",
                "series": series,
                "series_quality": series_snapshot["quality"],
                "source_name": "Polymarket Gamma",
                "updated_at": now.isoformat(),
                "observation": observation,
            },
            "hidden_detail_fields": {
                "calculation": {k: v for k, v in calculation.items() if k != "_calc_record_id"},
            },
            "evidence_bundle_id": evidence_bundle_id,
            "visual_priority": 2,
            "mobile_priority": 2,
            "generated_by": f"os-011/{CHARTER_VERSION}",
            "approved_by_verification_run_id": None,
            "data_as_of": series[-1]["timestamp"] if series else now.isoformat(),
            "assessed_at": now.isoformat(),
            "materially_updated_at": now.isoformat(),
        }
