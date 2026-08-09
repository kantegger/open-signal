"""Research Frontier ingestion-to-shadow orchestration (OS-049)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from open_signal.agents.runtime import Abstention, AgentRuntime, DeepSeekClient
from open_signal.budget import BudgetGuard
from open_signal.orchestration.metadata import ensure_runtime_metadata
from open_signal.research.agent import ResearchDomainAgent
from open_signal.research.candidates import ResearchCandidateDetector
from open_signal.sources.openalex import OpenAlexChain

SECTION_ID = "research-frontier"
DESK_ID = "research-frontier-desk"


class ResearchSectionService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def generate_candidates(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        del payload
        source_ids = ensure_runtime_metadata(self.engine)
        works = self._latest_payloads(source_ids["openalex"], "work")
        studies = self._latest_payloads(
            source_ids["clinicaltrials-gov"],
            "study",
        )
        topic_chain = OpenAlexChain(None)
        try:
            topic_concepts = {
                str(topic["id"]): [
                    str(value)
                    for value in (
                        topic.get("entity_mappings", {}).get(
                            "openalex_concepts", []
                        )
                    )
                ]
                for topic in topic_chain.list_topics()
            }
        finally:
            topic_chain.close()

        detector = ResearchCandidateDetector(self.engine)
        candidates = [
            *detector.detect_institution_entry(works),
            *detector.detect_stage_transition(studies),
            *detector.detect_cross_topic_relation(
                works,
                topic_concepts=topic_concepts,
            ),
        ]
        stored = detector.persist(candidates)
        return {
            "section_id": SECTION_ID,
            "maturity": "shadow",
            "works_evaluated": len(works),
            "studies_evaluated": len(studies),
            "candidates_detected": len(candidates),
            "candidates_created": stored,
            "duplicates_skipped": len(candidates) - stored,
            "public_claims_created": 0,
        }

    def investigate_shadow(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = payload or {}
        maximum = max(1, min(5, int(payload.get("maximum_candidates") or 5)))
        if not os.environ.get("DEEPSEEK_API_KEY"):
            return {
                "section_id": SECTION_ID,
                "maturity": "shadow",
                "status": "skipped",
                "reason": "DEEPSEEK_API_KEY not configured",
                "public_claims_created": 0,
            }

        budget = BudgetGuard(self.engine, desk_day_limit_usd=8.0)
        allowed, reason, state = budget.allow_llm_run(DESK_ID)
        if not allowed:
            return {
                "section_id": SECTION_ID,
                "maturity": "shadow",
                "status": "skipped",
                "reason": reason,
                "budget": state.to_dict(),
                "public_claims_created": 0,
            }

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, candidate_type, baseline_definition,
                           derived_metrics
                    FROM research_signal_candidates
                    WHERE status = 'generated'
                    ORDER BY created_at
                    LIMIT :limit
                    """
                ),
                {"limit": maximum},
            ).fetchall()

        client = DeepSeekClient(model="deepseek-chat")
        runtime = AgentRuntime(self.engine, client=client)
        agent = ResearchDomainAgent(runtime, self.engine)
        investigated = abstained = 0
        try:
            for row in rows:
                candidate = {
                    "candidate_type": row[1],
                    "baseline_definition": row[2],
                    "derived_metrics": row[3],
                }
                try:
                    agent.evaluate_candidate(
                        candidate_id=str(row[0]),
                        candidate=candidate,
                        lineage_id="research-ml-v1",
                    )
                    investigated += 1
                except Abstention:
                    abstained += 1
        finally:
            client.close()

        return {
            "section_id": SECTION_ID,
            "maturity": "shadow",
            "status": "completed",
            "candidates_selected": len(rows),
            "investigated": investigated,
            "abstained": abstained,
            "public_claims_created": 0,
        }

    def _latest_payloads(
        self, source_id: str, record_type: str
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (external_id) payload
                    FROM raw_source_records
                    WHERE source_id = :source
                      AND record_type = :record_type
                      AND status = 'active'
                    ORDER BY external_id, ingested_at DESC
                    """
                ),
                {"source": source_id, "record_type": record_type},
            ).fetchall()
        return [_object(row[0]) for row in rows]


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}
