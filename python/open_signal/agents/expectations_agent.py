"""Expectations desk charter agent (spec §31-32, OS-019).

Runs the LLM over candidate-detection output + evidence bundle and
produces a structured observation with persistence judgment and noise
check. Hard guardrails: no psychological attribution, no investment
advice — enforced in the prompt and validated on the output.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from open_signal.agents.runtime import Abstention, AgentRuntime

EXPECTATIONS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "observation": {"type": "string", "minLength": 10},
        "persistence": {"type": "string", "enum": ["persistent", "transient", "abstain"]},
        "noise_check": {"type": "string", "enum": ["clean", "noisy", "abstain"]},
        "no_psychological_attribution": {"type": "boolean", "const": True},
        "no_investment_advice": {"type": "boolean", "const": True},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 5},
    },
    "required": [
        "observation",
        "persistence",
        "noise_check",
        "no_psychological_attribution",
        "no_investment_advice",
        "confidence",
        "reason",
    ],
    "additionalProperties": False,
}

GUARDRAILS = (
    "硬性护栏（违反即拒绝输出）：\n"
    "1. 禁止心理归因：不得描述交易者/市场参与者的心理、情绪或意图"
    "（如'恐慌''信心不足''情绪低落'）。只能描述价格、概率、成交量、价差等可观测事实。\n"
    "2. 禁止投资建议：不得包含买卖建议、仓位建议或收益率预测。\n"
    "输出中 no_psychological_attribution 与 no_investment_advice 必须为 true。"
)


class ExpectationsCharterAgent:
    def __init__(self, runtime: AgentRuntime, engine: Any) -> None:
        self.runtime = runtime
        self.engine = engine

    # ------------------------------------------------------------------ main
    def evaluate_candidate(
        self,
        *,
        source_market_id: str,
        canonical_expectation_id: str,
        calculation: dict[str, Any],
        evidence_bundle_id: str | None,
        lineage_id: str,
        desk_id: str = "expectations-desk",
        section_id: str = "expectations-moved",
        capability_id: str = "expectation.persistence",
    ) -> dict[str, Any]:
        """Judge persistence/noise for one candidate; raises Abstention."""
        self._ensure_lineage()

        context = {
            "source_market_id": source_market_id,
            "canonical_expectation_id": canonical_expectation_id,
            "metrics": {k: v for k, v in calculation.items() if k != "_calc_record_id"},
            "evidence_bundle_id": evidence_bundle_id,
            "task": (
                "基于给定的确定性指标判断价格变化的持续性（persistent/transient）"
                "与数据噪音（clean/noisy），并写一句中文观察叙述。"
                "观察只描述可观测事实。"
            ),
            "guardrails": GUARDRAILS,
        }

        result = self.runtime.run(
            lineage_id=lineage_id,
            desk_id=desk_id,
            section_id=section_id,
            capability_id=capability_id,
            charter=self.runtime.load_charter("expectations-desk-charter"),
            context=context,
            output_schema=EXPECTATIONS_OUTPUT_SCHEMA,
        )

        # hard guardrail: reject outputs that violate the constraints
        structured = result.structured
        if structured.get("no_psychological_attribution") is not True or structured.get("no_investment_advice") is not True:
            from open_signal.agents.runtime import StructuredOutputError

            raise StructuredOutputError("output violates guardrails (psychological attribution or investment advice)")

        # charter abstention: persistence/noise both abstain
        if structured.get("persistence") == "abstain" or structured.get("noise_check") == "abstain":
            raise Abstention(structured.get("reason") or "insufficient evidence", result.raw_output)

        return self._persist(
            result,
            source_market_id=source_market_id,
            canonical_expectation_id=canonical_expectation_id,
            calculation=calculation,
            evidence_bundle_id=evidence_bundle_id,
            lineage_id=lineage_id,
        )

    # ---------------------------------------------------------------- persist
    def _ensure_lineage(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                    "VALUES ('expectations-desk', 'Expectations', 'market observations', 'os-019', 'shadow') "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                    "model_version, charter_id, charter_version, toolset_version, "
                    "context_builder_version, status, activated_at) "
                    "VALUES ('expectations-ml-v1', 'expectations-desk', 'Expectations Observation', "
                    "'deepseek-chat', 'v1', 'expectations-desk-charter', 'os-019', 'os-015', "
                    "'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
                )
            )

    def _persist(
        self,
        result: Any,
        *,
        source_market_id: str,
        canonical_expectation_id: str,
        calculation: dict[str, Any],
        evidence_bundle_id: str | None,
        lineage_id: str,
    ) -> dict[str, Any]:
        structured = result.structured

        with self.engine.begin() as conn:
            if evidence_bundle_id is None:
                eb_row = conn.execute(
                    text(
                        """
                        INSERT INTO evidence_bundles
                          (primary_evidence, supporting_evidence, counter_evidence,
                           data_calculation_ids, source_coverage, snapshot_hash)
                        VALUES (CAST(:p AS jsonb), '[]'::jsonb, '[]'::jsonb,
                                ARRAY[]::uuid[], CAST(:c AS jsonb), :h)
                        RETURNING id
                        """
                    ),
                    {
                        "p": json.dumps({"metrics": {k: v for k, v in calculation.items() if k != "_calc_record_id"}}),
                        "c": json.dumps({"source_market_id": source_market_id}),
                        "h": uuid.uuid4().hex,
                    },
                ).fetchone()
                evidence_bundle_id = str(eb_row[0])

            proposition = {
                "subject_ids": [source_market_id],
                "predicate": "price_persistence",
                "operator": "is",
                "value": structured["persistence"],
                "unit": None,
                "baseline": {
                    "delta_24h": calculation.get("delta_24h"),
                    "persistence": calculation.get("persistence"),
                },
                "qualifiers": {"noise_check": structured["noise_check"]},
                "proposition_version": "0.1.0",
            }
            row = conn.execute(
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
                      ('open-signal', 'expectations-desk', :lineage, :model, 'os-019',
                       :run, 'expectations-moved', 'expectation.persistence',
                       'agent_observation', :statement, CAST(:prop AS jsonb),
                       :confidence, :label, 'agent_judgment',
                       :eb, :hash, now(), 'draft')
                    RETURNING id
                    """
                ),
                {
                    "lineage": lineage_id,
                    "model": result.model,
                    "run": result.run_id,
                    "statement": structured["observation"],
                    "prop": json.dumps(proposition),
                    "confidence": structured["confidence"],
                    "label": _confidence_label(structured["confidence"]),
                    "eb": evidence_bundle_id,
                    "hash": uuid.uuid4().hex,
                },
            ).fetchone()
            claim_id = str(row[0])

        return {
            "run_id": result.run_id,
            "claim_id": claim_id,
            "persistence": structured["persistence"],
            "noise_check": structured["noise_check"],
            "observation": structured["observation"],
            "confidence": structured["confidence"],
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "cost_usd": result.usage.cost_usd(result.model),
            },
        }


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"
