"""Rules desk charter agent (spec §33.x, OS-018).

Feeds rule-change candidates (paragraph alignment output from OS-014) to
the LLM and produces a structured observation: materiality verdict,
affected categories, limitations and a preferred component. Non-material
changes are filtered out; the agent may abstain.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from open_signal.agents.runtime import AgentRuntime

RULES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "observation": {"type": "string"},
        "materiality": {"type": "string", "enum": ["material", "non_material", "abstain"]},
        "affected_categories": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "preferred_component": {
            "type": "string",
            "enum": [
                "rule-stage-transition.standard",
                "rule-change-summary.materiality",
                "signal-feed.rule-flash",
                "none",
            ],
        },
        "reason": {"type": "string"},
    },
    "required": [
        "observation",
        "materiality",
        "affected_categories",
        "limitations",
        "preferred_component",
        "reason",
    ],
    "additionalProperties": False,
}

COMPONENT_HINT = (
    "规则实质变化 → rule-change-summary.materiality；"
    "规则状态迁移（proposed→final/effective）→ rule-stage-transition.standard；"
    "仅时效性提示 → signal-feed.rule-flash；无合适组件 → none"
)


class RulesCharterAgent:
    def __init__(self, runtime: AgentRuntime, engine: Any) -> None:
        self.runtime = runtime
        self.engine = engine

    # ------------------------------------------------------------------ main
    def evaluate_change(
        self,
        *,
        rule_meta: dict[str, Any],
        change_candidates: list[dict[str, Any]],
        lineage_id: str,
        desk_id: str = "rules-desk",
        section_id: str = "rules-moved",
        capability_id: str = "rule.materiality",
    ) -> dict[str, Any]:
        """Evaluate one rule-change batch; returns the structured verdict.

        Raises Abstention when the model abstains.
        """
        self._ensure_rules_lineage()

        if not change_candidates:
            return {
                "observation": "无实质变更候选",
                "materiality": "non_material",
                "affected_categories": [],
                "limitations": ["无段落变更"],
                "preferred_component": "none",
                "reason": "paragraph alignment 未发现 substantive changes",
            }

        context = {
            "rule": rule_meta,
            "change_candidates": change_candidates,
            "component_hint": COMPONENT_HINT,
            "task": (
                "判断这组规则变更是否具有实质影响（material）。"
                "区分 material（政策/阈值/适用范围变化）与 non_material（日期/编号/格式）。"
                "输出 JSON。"
            ),
        }

        result = self.runtime.run(
            lineage_id=lineage_id,
            desk_id=desk_id,
            section_id=section_id,
            capability_id=capability_id,
            charter=self.runtime.load_charter("rules-desk-charter"),
            context=context,
            output_schema=RULES_OUTPUT_SCHEMA,
        )

        return self._persist(result, rule_meta, change_candidates, lineage_id)

    # ---------------------------------------------------------------- persist
    def _ensure_rules_lineage(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                    "VALUES ('rules-desk', 'Rules', 'monitor federal rule changes', 'os-018', 'shadow') "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                    "model_version, charter_id, charter_version, toolset_version, "
                    "context_builder_version, status, activated_at) "
                    "VALUES ('rules-ml-v1', 'rules-desk', 'Rules Materiality', 'deepseek-chat', "
                    "'v1', 'rules-desk-charter', 'os-018', 'os-015', 'v1', 'active', now()) "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )

    def _persist(
        self,
        result: Any,
        rule_meta: dict[str, Any],
        change_candidates: list[dict[str, Any]],
        lineage_id: str,
    ) -> dict[str, Any]:
        structured = result.structured
        material = structured["materiality"] == "material"

        with self.engine.begin() as conn:
            # evidence bundle from the change candidates (claims require one)
            eb_row = conn.execute(
                text(
                    """
                    INSERT INTO evidence_bundles
                      (primary_evidence, supporting_evidence, counter_evidence,
                       data_calculation_ids, source_coverage, snapshot_hash)
                    VALUES
                      (CAST(:primary AS jsonb), '[]'::jsonb, '[]'::jsonb,
                       ARRAY[]::uuid[], CAST(:coverage AS jsonb), :hash)
                    RETURNING id
                    """
                ),
                {
                    "primary": json.dumps(change_candidates),
                    "coverage": json.dumps({"document_number": rule_meta.get("document_number")}),
                    "hash": uuid.uuid4().hex,
                },
            ).fetchone()
            evidence_bundle_id = str(eb_row[0])

            # observation claim for material changes
            claim_id = None
            if material:
                proposition = {
                    "subject_ids": [rule_meta.get("document_number")],
                    "predicate": "rule_materiality",
                    "operator": "is",
                    "value": "material",
                    "unit": None,
                    "baseline": {},
                    "qualifiers": {"affected_categories": structured["affected_categories"]},
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
                          ('open-signal', 'rules-desk', :lineage, :model, 'os-018',
                           :run, 'rules-moved', 'rule.materiality',
                           'rule_change_observation', :statement,
                           CAST(:prop AS jsonb), :confidence, :label, 'agent_judgment',
                           :eb, :hash, now(), 'draft')
                        RETURNING id
                        """
                    ),
                    {
                        "lineage": lineage_id,
                        "run": result.run_id,
                        "model": result.model,
                        "statement": structured["observation"],
                        "prop": json.dumps(proposition),
                        "confidence": _confidence(structured),
                        "label": "medium",
                        "eb": evidence_bundle_id,
                        "hash": uuid.uuid4().hex,
                    },
                ).fetchone()
                claim_id = str(row[0])

        return {
            "run_id": result.run_id,
            "claim_id": claim_id,
            "materiality": structured["materiality"],
            "observation": structured["observation"],
            "affected_categories": structured["affected_categories"],
            "limitations": structured["limitations"],
            "preferred_component": structured["preferred_component"],
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "cost_usd": result.usage.cost_usd(result.model),
            },
        }


def _confidence(structured: dict[str, Any]) -> float:
    if structured["materiality"] == "non_material":
        return 0.7
    return 0.85
