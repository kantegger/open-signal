"""Research Frontier ingestion-to-shadow orchestration (OS-049)."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from open_signal.agents.runtime import Abstention, AgentRuntime, DeepSeekClient
from open_signal.budget import BudgetGuard
from open_signal.orchestration.metadata import ensure_runtime_metadata
from open_signal.research.agent import ResearchDomainAgent
from open_signal.research.candidates import CANDIDATE_VERSION, ResearchCandidateDetector
from open_signal.research.publication import (
    public_research_qualification_report,
    select_public_research_items,
)
from open_signal.security.hardening import audit
from open_signal.sources.openalex import OpenAlexChain

SECTION_ID = "research-frontier"
DESK_ID = "research-frontier-desk"
logger = logging.getLogger(__name__)


class ResearchSectionService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def generate_candidates(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = payload or {}
        requested_version = str(payload.get("candidate_version") or "").strip()
        if requested_version and requested_version != CANDIDATE_VERSION:
            raise ValueError(
                "research candidate schedule/code mismatch: "
                f"requested {requested_version}, running {CANDIDATE_VERSION}"
            )
        source_ids = ensure_runtime_metadata(self.engine)
        topic_chain = OpenAlexChain(None)
        try:
            topics = topic_chain.list_topics()
            topic_concepts = {
                str(topic["id"]): [
                    str(value)
                    for value in (
                        topic.get("entity_mappings", {}).get("openalex_concepts", [])
                    )
                ]
                for topic in topics
            }
            topic_labels = {
                str(topic["id"]): str(
                    topic.get("label_en") or topic.get("label") or topic["id"]
                )
                for topic in topics
            }
        finally:
            topic_chain.close()
        works = self._latest_payloads(
            source_ids["openalex"],
            "work",
            topic_concepts=topic_concepts,
        )
        studies = self._latest_payloads(
            source_ids["clinicaltrials-gov"],
            "study",
        )

        detector = ResearchCandidateDetector(self.engine)
        candidates = [
            *detector.detect_institution_entry(
                works,
                topic_labels=topic_labels,
            ),
            *detector.detect_stage_transition(
                studies,
                topic_labels=topic_labels,
            ),
            *detector.detect_cross_topic_relation(
                works,
                topic_concepts=topic_concepts,
                topic_labels=topic_labels,
            ),
        ]
        stored = detector.persist(candidates)
        publication_candidates = detector.publication_candidates()
        selected, eligible_total = select_public_research_items(
            publication_candidates
        )
        qualification = public_research_qualification_report(
            publication_candidates
        )
        result = {
            "section_id": SECTION_ID,
            "maturity": "shadow",
            "candidate_generator_version": CANDIDATE_VERSION,
            "works_evaluated": len(works),
            "studies_evaluated": len(studies),
            "candidates_detected": len(candidates),
            "candidates_created": stored,
            "duplicates_skipped": len(candidates) - stored,
            "public_contract_evaluated": qualification["evaluated"],
            "public_contract_eligible": eligible_total,
            "public_contract_selected": len(selected),
            "public_contract_rejected": qualification["rejected"],
            "public_rejection_reasons": qualification["rejection_reasons"],
            "public_claims_created": 0,
        }
        if (works or studies) and eligible_total == 0:
            logger.warning(
                "research candidate refresh produced zero public-eligible items: %s",
                result,
            )
            result["zero_output_audit_event_id"] = audit(
                self.engine,
                action="research.publication.zero_output",
                actor=f"research-candidate-detector/{CANDIDATE_VERSION}",
                target=SECTION_ID,
                detail=result,
            )
        return result

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
                      AND candidate_generator_version = :version
                    ORDER BY created_at
                    LIMIT :limit
                    """
                ),
                {"limit": maximum, "version": CANDIDATE_VERSION},
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
            "candidate_generator_version": CANDIDATE_VERSION,
            "candidates_selected": len(rows),
            "investigated": investigated,
            "abstained": abstained,
            "public_claims_created": 0,
        }

    def _latest_payloads(
        self,
        source_id: str,
        record_type: str,
        *,
        topic_concepts: Mapping[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (external_id)
                           payload, transport_metadata
                    FROM raw_source_records
                    WHERE source_id = :source
                      AND record_type = :record_type
                      AND status = 'active'
                      AND payload IS NOT NULL
                    ORDER BY external_id, last_seen_at DESC, ingested_at DESC
                    """
                ),
                {"source": source_id, "record_type": record_type},
            ).fetchall()
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(_object(row[0]))
            topic_ids = _metadata_topic_ids(_object(row[1]))
            if not topic_ids and record_type == "work" and topic_concepts:
                topic_ids = _infer_openalex_topics(payload, topic_concepts)
            payload["_open_signal"] = {
                "monitoring_topic_ids": topic_ids,
            }
            payloads.append(payload)
        return payloads


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metadata_topic_ids(metadata: Mapping[str, Any]) -> list[str]:
    topics = metadata.get("monitoring_topics")
    if isinstance(topics, dict):
        return sorted(str(topic_id) for topic_id, enabled in topics.items() if enabled)
    if isinstance(topics, list):
        return sorted({str(topic_id) for topic_id in topics if topic_id})
    return []


def _infer_openalex_topics(
    payload: Mapping[str, Any],
    topic_concepts: Mapping[str, list[str]],
) -> list[str]:
    observed = {
        str(concept.get("display_name") or "").casefold()
        for field in ("concepts", "topics")
        for concept in payload.get(field) or []
        if isinstance(concept, dict) and concept.get("display_name")
    }
    return sorted(
        topic_id
        for topic_id, concepts in topic_concepts.items()
        if observed & {str(concept).casefold() for concept in concepts}
    )
