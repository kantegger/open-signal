from collections import Counter
from datetime import UTC, datetime

from open_signal.research.publication import (
    build_public_research_item,
    select_public_research_items,
)

NOW = datetime(2026, 8, 9, 8, tzinfo=UTC)


def _candidate(
    candidate_id: str,
    candidate_type: str,
    metrics: dict,
    *,
    status: str = "generated",
) -> dict:
    return {
        "id": candidate_id,
        "candidate_type": candidate_type,
        "derived_metrics": metrics,
        "status": status,
        "created_at": NOW,
    }


def _institution(
    candidate_id: str,
    topic_id: str,
    topic_label: str,
    institution: str,
    *,
    recent: int = 8,
    prior: int = 1,
    status: str = "generated",
) -> dict:
    return _candidate(
        candidate_id,
        "institution_entry",
        {
            "topic_id": topic_id,
            "topic_label": topic_label,
            "institution": institution,
            "recent_works": recent,
            "prior_works": prior,
            "representative_works": [{"id": f"W-{candidate_id}", "title": "Representative work"}],
            "evidence_count": recent,
            "window_label": "2025–2026 YTD",
            "baseline_label": "Before 2025",
            "hypothesis": "This internal agent prose must never be public.",
        },
        status=status,
    )


def _portfolio(
    candidate_id: str,
    topic_id: str,
    topic_label: str,
    sponsor: str,
) -> dict:
    return _candidate(
        candidate_id,
        "stage_transition",
        {
            "topic_id": topic_id,
            "topic_label": topic_label,
            "sponsor": sponsor,
            "phase_labels": ["Phase 1", "Phase 2"],
            "representative_studies": [
                {"id": f"NCT-{candidate_id}-1", "title": "Phase 1 study"},
                {"id": f"NCT-{candidate_id}-2", "title": "Phase 2 study"},
            ],
            "study_count": 2,
            "window_label": "Registry portfolio as of Aug 2026",
            "baseline_label": "Cross-sectional phase coverage",
        },
    )


def _cross(
    candidate_id: str,
    topics: tuple[tuple[str, str], tuple[str, str]],
) -> dict:
    return _candidate(
        candidate_id,
        "cross_topic_relation",
        {
            "topics": [topic[0] for topic in topics],
            "topic_labels": [topic[1] for topic in topics],
            "recent_cooccurrences": 7,
            "prior_cooccurrences": 2,
            "representative_works": [{"id": f"W-{candidate_id}", "title": "Bridge paper"}],
            "window_label": "2025–2026 YTD",
            "baseline_label": "Before 2025",
        },
    )


def test_institution_public_item_is_event_first_and_excludes_agent_prose() -> None:
    candidate = _institution(
        "one",
        "generative-ai",
        "Generative AI and foundation models",
        "Microsoft Research Asia",
        recent=5,
        prior=0,
        status="shadow_investigation",
    )

    item = build_public_research_item(candidate)

    assert item is not None
    assert item["headline"] == (
        "New institutional output appeared in Generative AI and foundation models"
    )
    assert item["entity"] == "Microsoft Research Asia"
    assert item["screening_stage"] == "investigated"
    assert "Microsoft Research Asia" not in item["headline"]
    assert "internal agent prose" not in str(item)


def test_incomplete_internal_candidate_is_not_public() -> None:
    candidate = _institution(
        "missing-topic",
        "generative-ai",
        "Generative AI and foundation models",
        "New Lab",
    )
    del candidate["derived_metrics"]["topic_label"]

    assert build_public_research_item(candidate) is None
    assert select_public_research_items([candidate]) == ([], 0)


def test_trial_portfolio_does_not_claim_advancement() -> None:
    item = build_public_research_item(
        _portfolio(
            "portfolio",
            "oncology-immunotherapy",
            "Oncology immunotherapy",
            "National Cancer Institute",
        )
    )

    assert item is not None
    assert item["direction"] == "neutral"
    assert "span Phase 1 and Phase 2" in item["headline"]
    assert "advanced" not in item["headline"].lower()
    assert "transition" not in item["headline"].lower()


def test_selection_deduplicates_and_preserves_type_and_topic_diversity() -> None:
    candidates = [
        _institution("i1", "generative-ai", "Generative AI", "Lab A"),
        _institution("i1-new", "generative-ai", "Generative AI", "Lab A", recent=12),
        _institution("i2", "quantum-computing", "Quantum computing", "Lab B"),
        _institution("i3", "synthetic-biology", "Synthetic biology", "Lab C"),
        _portfolio("p1", "oncology-immunotherapy", "Oncology immunotherapy", "Sponsor A"),
        _portfolio("p2", "synthetic-biology", "Synthetic biology", "Sponsor B"),
        _cross(
            "c1",
            (
                ("generative-ai", "Generative AI"),
                ("oncology-immunotherapy", "Oncology immunotherapy"),
            ),
        ),
        _cross(
            "c2",
            (
                ("quantum-computing", "Quantum computing"),
                ("synthetic-biology", "Synthetic biology"),
            ),
        ),
    ]

    selected, eligible_total = select_public_research_items(candidates)

    assert eligible_total == 7
    assert len(selected) <= 6
    type_counts = Counter(item["candidate_type"] for item in selected)
    topic_counts = Counter(topic_id for item in selected for topic_id in item["topic_ids"])
    assert set(type_counts) == {
        "institution_entry",
        "stage_transition",
        "cross_topic_relation",
    }
    assert max(type_counts.values()) <= 2
    assert max(topic_counts.values()) <= 2
