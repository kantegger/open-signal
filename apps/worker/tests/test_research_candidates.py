"""Research investigation candidate tests (OS-021). Requires real PostgreSQL
via OPEN_SIGNAL_TEST_DATABASE_URL (migration 0001 applied).
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from open_signal.research.candidates import ResearchCandidateDetector


@pytest.fixture()
def engine():
    url = os.environ.get("OPEN_SIGNAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OPEN_SIGNAL_TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine

    return create_engine(url)


@pytest.fixture()
def detector(engine) -> ResearchCandidateDetector:
    return ResearchCandidateDetector(engine)


def _cleanup(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM research_signal_candidates"))


def _work(year: str, institution: str, concepts: list[str], title: str = "t") -> dict:
    return {
        "publication_date": f"{year}-06-01",
        "title": title,
        "authorships": [{"institutions": [{"display_name": institution}]}],
        "concepts": [{"display_name": c} for c in concepts],
    }


def _study(sponsor: str, phase: str, title: str = "Study") -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": f"NCT{uuid.uuid4().hex[:6]}", "briefTitle": title},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "designModule": {"phases": [phase]},
        }
    }


# ------------------------------------------------------------- detection


def test_institution_entry_detected(detector, engine) -> None:
    works = []
    # steady contributor (not new)
    works += [_work("2023", "Old University", ["A"]) for _ in range(10)]
    works += [_work("2024", "Old University", ["A"]) for _ in range(10)]
    # new entrant: burst in recent window
    works += [_work("2024", "New Lab", ["A"]) for _ in range(5)]

    candidates = detector.detect_institution_entry(works, window_years=2, now=datetime(2025, 1, 1, tzinfo=UTC))
    names = [c["derived_metrics"]["institution"] for c in candidates]
    assert "New Lab" in names
    assert "Old University" not in names


def test_institution_entry_needs_burst(detector, engine) -> None:
    works = [_work("2024", "Trickle", ["A"]) for _ in range(1)]
    candidates = detector.detect_institution_entry(works, window_years=2, now=datetime(2025, 1, 1, tzinfo=UTC))
    assert candidates == []


def test_stage_transition_detected(detector, engine) -> None:
    studies = [_study("PharmaCo", "PHASE1"), _study("PharmaCo", "PHASE2")]
    candidates = detector.detect_stage_transition(studies)
    sponsors = [c["derived_metrics"]["sponsor"] for c in candidates]
    assert "PharmaCo" in sponsors


def test_stage_transition_single_phase_not_candidate(detector, engine) -> None:
    studies = [_study("SingleCo", "PHASE2"), _study("SingleCo", "PHASE2")]
    candidates = detector.detect_stage_transition(studies)
    assert candidates == []


def test_cross_topic_relation_detected(detector, engine) -> None:
    topic_concepts = {
        "oncology-immunotherapy": ["CAR T cell therapy"],
        "synthetic-biology": ["CRISPR"],
        "generative-ai": ["Large language models"],
    }
    works = []
    # prior co-occurrence: 1 (baseline)
    works += [_work("2023", "X", ["CAR T cell therapy", "CRISPR"])]
    # recent growth
    works += [_work("2024", "X", ["CAR T cell therapy", "CRISPR"]) for _ in range(3)]
    candidates = detector.detect_cross_topic_relation(
        works, topic_concepts=topic_concepts, window_years=2, now=datetime(2025, 1, 1, tzinfo=UTC)
    )
    assert len(candidates) == 1
    assert candidates[0]["derived_metrics"]["topics"] == ["oncology-immunotherapy", "synthetic-biology"]


# ---------------------------------------------------------------- persistence


def test_persist_and_no_claims(detector, engine) -> None:
    from sqlalchemy import text

    _cleanup(engine)
    with engine.connect() as conn:
        claims_before = conn.execute(text("SELECT count(*) FROM claims")).scalar_one()

    candidates = detector.detect_institution_entry(
        [_work("2024", "New Lab", ["A"]) for _ in range(5)],
        window_years=2,
        now=datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert len(candidates) == 1
    stored = detector.persist(candidates)
    assert stored == 1

    # candidates only: this stage must not create any claims
    with engine.connect() as conn:
        claims_after = conn.execute(text("SELECT count(*) FROM claims")).scalar_one()
    assert claims_after == claims_before

    recent = detector.recent_candidates(candidate_type="institution_entry")
    assert len(recent) == 1
    assert recent[0]["status"] == "generated"
    _cleanup(engine)
