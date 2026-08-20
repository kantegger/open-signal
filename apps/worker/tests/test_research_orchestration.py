from copy import deepcopy
from datetime import UTC, datetime

import pytest
from open_signal.orchestration.research import (
    ResearchSectionService,
    _infer_openalex_topics,
    _metadata_topic_ids,
)
from open_signal.research.candidates import ResearchCandidateDetector
from open_signal.research.publication import select_public_research_items
from open_signal.sources.clinicaltrials import ClinicalTrialsChain


def test_transport_metadata_preserves_multiple_monitoring_topics() -> None:
    assert _metadata_topic_ids(
        {
            "monitoring_topics": {
                "synthetic-biology": True,
                "generative-ai": True,
                "quantum-computing": False,
            }
        }
    ) == ["generative-ai", "synthetic-biology"]


def test_candidate_refresh_rejects_a_stale_schedule_contract() -> None:
    with pytest.raises(ValueError, match="schedule/code mismatch"):
        ResearchSectionService(None).generate_candidates(
            {"candidate_version": "os-021.stale"}
        )


def test_legacy_openalex_record_is_inferred_only_from_frozen_concepts() -> None:
    payload = {
        "concepts": [
            {"display_name": "Large language models"},
            {"display_name": "CRISPR"},
        ]
    }
    topic_concepts = {
        "generative-ai": ["Large language models", "Artificial intelligence"],
        "synthetic-biology": ["CRISPR", "Synthetic biology"],
        "quantum-computing": ["Quantum computing"],
    }

    assert _infer_openalex_topics(payload, topic_concepts) == [
        "generative-ai",
        "synthetic-biology",
    ]


def test_static_cross_sponsor_fixtures_remain_internal_screening() -> None:
    """Static registry breadth is context, not a newly observed transition."""

    chain = ClinicalTrialsChain(None, offline=True)
    studies_by_id: dict[str, dict] = {}
    labels: dict[str, str] = {}
    try:
        for topic in chain.topics["topics"]:
            topic_id = str(topic["id"])
            query = chain.baseline_query(topic_id)
            if not query:
                continue
            labels[topic_id] = str(topic.get("label_en") or topic["label"])
            for source_study in chain._load(query).get("studies") or []:
                study = deepcopy(source_study)
                protocol = study.get("protocolSection") or {}
                study_id = str(
                    (protocol.get("identificationModule") or {}).get("nctId") or ""
                )
                if not study_id:
                    continue
                stored = studies_by_id.setdefault(study_id, study)
                metadata = stored.setdefault("_open_signal", {})
                topics = set(metadata.get("monitoring_topic_ids") or [])
                topics.add(topic_id)
                metadata["monitoring_topic_ids"] = sorted(topics)
    finally:
        chain.close()

    detected_at = datetime(2026, 8, 9, 8, tzinfo=UTC)
    candidates = ResearchCandidateDetector(None).detect_stage_transition(
        list(studies_by_id.values()),
        now=detected_at,
        topic_labels=labels,
    )
    candidate_rows = [
        {**candidate, "id": f"fixture-{index}", "created_at": detected_at}
        for index, candidate in enumerate(candidates)
    ]

    selected, eligible_total = select_public_research_items(candidate_rows)

    assert len(studies_by_id) == 6
    assert eligible_total == 0
    assert selected == []
