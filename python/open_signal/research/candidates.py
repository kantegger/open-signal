"""Research investigation candidates (spec §35.x, OS-021).

Generates investigation candidates only — never "frontier" Claims directly:

- institution entry: an institution's publication count in a topic spikes
  relative to its prior output (new entrant)
- stage transition: a sponsor's trials advance across phases (e.g. Phase 1
  -> Phase 2) for a related condition
- cross-topic relation increase: concept co-occurrence between two topics
  grows over time

Candidates are written to research_signal_candidates (status=generated).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

CANDIDATE_VERSION = "os-021"
INSTITUTION_ENTRY_MULTIPLIER = 3.0
INSTITUTION_ENTRY_MIN_WORKS = 3


class ResearchCandidateDetector:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------- detection
    def detect_institution_entry(
        self,
        works: list[dict[str, Any]],
        *,
        window_years: int = 2,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Institutions whose recent output in the corpus spiked.

        works: OpenAlex work dicts (must include authorships + publication_date).
        """
        now = now or datetime.now(timezone.utc)
        year_now = now.year
        recent = Counter()
        prior = Counter()
        for w in works:
            pub = (w.get("publication_date") or "")[:4]
            try:
                y = int(pub)
            except ValueError:
                continue
            for a in w.get("authorships") or []:
                for inst in a.get("institutions") or []:
                    name = inst.get("display_name")
                    if not name:
                        continue
                    if y >= year_now - window_years + 1:
                        recent[name] += 1
                    else:
                        prior[name] += 1

        candidates = []
        for name, count in recent.items():
            base = prior.get(name, 0)
            if count >= INSTITUTION_ENTRY_MIN_WORKS and count >= INSTITUTION_ENTRY_MULTIPLIER * max(1, base):
                candidates.append(
                    {
                        "candidate_type": "institution_entry",
                        "subject_ids": [],
                        "observation_window_start": f"{year_now - window_years}-01-01",
                        "observation_window_end": f"{year_now}-12-31",
                        "baseline_definition": f"prior-year works {base}",
                        "derived_metrics": {"institution": name, "recent_works": count, "prior_works": base},
                        "evidence_relation_ids": [],
                        "status": "generated",
                    }
                )
        return candidates

    def detect_stage_transition(
        self,
        studies: list[dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Sponsors advancing trials across phases for a related condition.

        studies: ClinicalTrials.gov v2 study dicts.
        """
        sponsor_phases: dict[str, set[str]] = defaultdict(set)
        sponsor_title: dict[str, str] = {}
        for s in studies:
            ps = s.get("protocolSection") or {}
            ident = ps.get("identificationModule") or {}
            sponsor = (ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor", {}).get("name")
            phases = (ps.get("designModule") or {}).get("phases") or []
            if not sponsor:
                continue
            sponsor_phases[sponsor].update(phases)
            sponsor_title.setdefault(sponsor, ident.get("briefTitle") or "")

        candidates = []
        phase_rank = {"EARLY_PHASE1": 1, "PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "PHASE4": 4}
        for sponsor, phases in sponsor_phases.items():
            ranks = [phase_rank.get(p, 0) for p in phases if p in phase_rank]
            if len(set(r for r in ranks if r)) >= 2:  # spans >= 2 phases
                candidates.append(
                    {
                        "candidate_type": "stage_transition",
                        "subject_ids": [],
                        "observation_window_start": "2020-01-01",
                        "observation_window_end": f"{now or datetime.now(timezone.utc)}".split(" ")[0],
                        "baseline_definition": "trial phase distribution",
                        "derived_metrics": {
                            "sponsor": sponsor,
                            "phases": sorted(phases),
                            "title_hint": sponsor_title[sponsor][:120],
                        },
                        "evidence_relation_ids": [],
                        "status": "generated",
                    }
                )
        return candidates

    def detect_cross_topic_relation(
        self,
        works: list[dict[str, Any]],
        *,
        topic_concepts: dict[str, list[str]],
        window_years: int = 2,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Growth in co-occurrence between two topics' concepts."""
        now = now or datetime.now(timezone.utc)
        year_now = now.year
        recent = Counter()
        prior = Counter()
        for w in works:
            pub = (w.get("publication_date") or "")[:4]
            try:
                y = int(pub)
            except ValueError:
                continue
            concepts = {c.get("display_name", "") for c in w.get("concepts") or []}
            pairs = set()
            for tid, names in topic_concepts.items():
                if concepts & set(names):
                    pairs.add(tid)
            if len(pairs) >= 2:
                for a, b in _pair_combinations(sorted(pairs)):
                    if y >= year_now - window_years + 1:
                        recent[(a, b)] += 1
                    else:
                        prior[(a, b)] += 1

        candidates = []
        for (a, b), count in recent.items():
            base = prior.get((a, b), 0)
            if count >= 2 and count > base:
                candidates.append(
                    {
                        "candidate_type": "cross_topic_relation",
                        "subject_ids": [],
                        "observation_window_start": f"{year_now - window_years}-01-01",
                        "observation_window_end": f"{year_now}-12-31",
                        "baseline_definition": f"prior co-occurrence {base}",
                        "derived_metrics": {"topics": [a, b], "recent_cooccurrences": count, "prior_cooccurrences": base},
                        "evidence_relation_ids": [],
                        "status": "generated",
                    }
                )
        return candidates

    # --------------------------------------------------------------- storage
    def persist(self, candidates: list[dict[str, Any]], section_id: str = "research-frontier") -> int:
        stored = 0
        with self.engine.begin() as conn:
            for c in candidates:
                subject_ids = c.get("subject_ids") or []
                result = conn.execute(
                    text(
                        """
                        INSERT INTO research_signal_candidates
                          (candidate_type, subject_ids, observation_window_start,
                           observation_window_end, baseline_definition, derived_metrics,
                           evidence_relation_ids, candidate_generator_version, status)
                        VALUES
                          (:type, CAST(:subjects AS uuid[]), CAST(:start AS timestamptz),
                           CAST(:end AS timestamptz), :baseline, CAST(:metrics AS jsonb),
                           CAST(:evidence AS uuid[]), :ver, 'generated')
                        """
                    ),
                    {
                        "type": c["candidate_type"],
                        "subjects": subject_ids,
                        "start": c["observation_window_start"],
                        "end": c["observation_window_end"],
                        "baseline": c["baseline_definition"],
                        "metrics": json.dumps(c["derived_metrics"]),
                        "evidence": c.get("evidence_relation_ids") or [],
                        "ver": CANDIDATE_VERSION,
                    },
                )
                stored += result.rowcount
        return stored

    def recent_candidates(self, candidate_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            if candidate_type:
                rows = conn.execute(
                    text(
                        "SELECT candidate_type, derived_metrics, baseline_definition, status "
                        "FROM research_signal_candidates WHERE candidate_type = :t "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"t": candidate_type, "limit": limit},
                ).fetchall()
            else:
                rows = conn.execute(
                    text(
                        "SELECT candidate_type, derived_metrics, baseline_definition, status "
                        "FROM research_signal_candidates ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                ).fetchall()
        return [
            {"candidate_type": r[0], "derived_metrics": r[1], "baseline_definition": r[2], "status": r[3]}
            for r in rows
        ]


def _pair_combinations(items: list[str]) -> list[tuple[str, str]]:
    return [(items[i], items[j]) for i in range(len(items)) for j in range(i + 1, len(items))]
