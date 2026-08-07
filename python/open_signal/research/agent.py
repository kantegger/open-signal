"""Research domain agent (spec §35.x, OS-022).

Runs the Research Domain Agent with Historian + Skeptic + Verification
roles over investigation candidates. Initial scope writes to the Shadow
Ledger only — research_signal_candidates status is updated, no Claims are
created.
"""

from __future__ import annotations

import json
from typing import Any

from open_signal.agents.runtime import Abstention, AgentRuntime
from sqlalchemy import text

RESEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["investigate", "skip", "abstain"]},
        "hypothesis": {"type": "string", "minLength": 10},
        "historical_context": {"type": "string", "minLength": 5},
        "skeptic_concerns": {"type": "array", "items": {"type": "string"}},
        "verification_note": {"type": "string", "minLength": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "minLength": 5},
    },
    "required": [
        "verdict",
        "hypothesis",
        "historical_context",
        "skeptic_concerns",
        "verification_note",
        "confidence",
        "reason",
    ],
    "additionalProperties": False,
}

ROLES_PROMPT = (
    "你同时担任三个角色并输出统一判断：\n"
    "1. Historian：将该信号与历史基线比较（baseline_definition 与 derived_metrics 中的 "
    "prior 数值），判断是趋势还是噪音。\n"
    "2. Skeptic：主动列出反例/替代解释（样本偏差、来源单一、窗口选择偏差）。\n"
    "3. Verification：确认引用证据可追溯；若无法确认则降低 confidence。\n"
    "结论只写入 shadow ledger（research_signal_candidates），绝不创建正式 Claim。"
)


class ResearchDomainAgent:
    def __init__(self, runtime: AgentRuntime, engine: Any) -> None:
        self.runtime = runtime
        self.engine = engine

    # ------------------------------------------------------------------ main
    def evaluate_candidate(
        self,
        *,
        candidate_id: str,
        candidate: dict[str, Any],
        lineage_id: str,
        desk_id: str = "research-frontier-desk",
        section_id: str = "research-frontier",
        capability_id: str = "research.investigation",
    ) -> dict[str, Any]:
        """Judge one candidate; updates shadow ledger (no Claims)."""
        self._ensure_lineage()

        context = {
            "candidate_id": candidate_id,
            "candidate_type": candidate.get("candidate_type"),
            "baseline_definition": candidate.get("baseline_definition"),
            "derived_metrics": candidate.get("derived_metrics"),
            "roles": ROLES_PROMPT,
            "task": "判断该研究候选是否值得深入调查，并输出 hypothesis 与 shadow ledger 记录。",
        }

        try:
            result = self.runtime.run(
                lineage_id=lineage_id,
                desk_id=desk_id,
                section_id=section_id,
                capability_id=capability_id,
                charter=self.runtime.load_charter("research-frontier-charter"),
                context=context,
                output_schema=RESEARCH_OUTPUT_SCHEMA,
                candidate_id=candidate_id,
            )
        except Abstention:
            self._update_status(candidate_id, "abstained")
            raise

        structured = result.structured
        new_status = "shadow_investigation" if structured["verdict"] == "investigate" else "rejected"
        self._update_status(candidate_id, new_status, structured)

        return {
            "candidate_id": candidate_id,
            "run_id": result.run_id,
            "verdict": structured["verdict"],
            "status": new_status,
            "hypothesis": structured["hypothesis"],
            "historical_context": structured["historical_context"],
            "skeptic_concerns": structured["skeptic_concerns"],
            "verification_note": structured["verification_note"],
            "confidence": structured["confidence"],
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "cost_usd": result.usage.cost_usd(result.model),
            },
        }

    # ------------------------------------------------------------- shadow ledger
    def _update_status(self, candidate_id: str, status: str, structured: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as conn:
            if structured is None:
                conn.execute(
                    text(
                        "UPDATE research_signal_candidates SET status = :status WHERE id = :id"
                    ),
                    {"status": status, "id": candidate_id},
                )
                return
            shadow = {
                "hypothesis": structured["hypothesis"],
                "historical_context": structured["historical_context"],
                "skeptic_concerns": structured["skeptic_concerns"],
                "verification_note": structured["verification_note"],
                "confidence": structured["confidence"],
            }
            conn.execute(
                text(
                    "UPDATE research_signal_candidates SET status = :status, "
                    "derived_metrics = derived_metrics || CAST(:shadow AS jsonb) "
                    "WHERE id = :id"
                ),
                {"status": status, "shadow": json.dumps(shadow), "id": candidate_id},
            )

    def _ensure_lineage(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity) "
                    "VALUES ('research-frontier-desk', 'Research Frontier', 'research structure changes', "
                    "'os-022', 'shadow') ON CONFLICT (id) DO NOTHING"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO agent_lineages (id, desk_id, name, foundation_model, "
                    "model_version, charter_id, charter_version, toolset_version, "
                    "context_builder_version, status, activated_at) "
                    "VALUES ('research-ml-v1', 'research-frontier-desk', 'Research Domain Agent', "
                    "'deepseek-chat', 'v1', 'research-frontier-charter', 'os-022', 'os-015', "
                    "'v1', 'active', now()) ON CONFLICT (id) DO NOTHING"
                )
            )

    def shadow_ledger_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, candidate_type, status, derived_metrics "
                    "FROM research_signal_candidates "
                    "WHERE status IN ('shadow_investigation', 'rejected', 'abstained') "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [
            {"candidate_id": str(r[0]), "candidate_type": r[1], "status": r[2], "derived_metrics": r[3]}
            for r in rows
        ]
