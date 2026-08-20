"""Research investigation candidates (spec §35.x, OS-021).

Generates investigation candidates only — never "frontier" Claims directly:

- institution entry: an institution's publication count in a topic spikes
  relative to its prior output (new entrant)
- phase portfolio: a sponsor, or a monitored topic across sponsors, has
  registered trials across multiple phases (this does not by itself prove
  that one trial advanced)
- cross-topic relation increase: concept co-occurrence between two topics
  grows over time

Candidates are written to research_signal_candidates (status=generated).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

CANDIDATE_VERSION = "os-021.3"
INSTITUTION_ENTRY_MULTIPLIER = 3.0
INSTITUTION_ENTRY_MIN_WORKS = 3
REPRESENTATIVE_EVIDENCE_LIMIT = 3


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
        topic_labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Institutions whose recent output spiked within a monitored topic.

        works: OpenAlex work dicts (must include authorships + publication_date).
        Records without topic attribution still produce internal candidates, but
        the public contract rejects them until attribution and evidence exist.
        """
        now = now or datetime.now(timezone.utc)
        year_now = now.year
        start_year = year_now - window_years + 1
        topic_labels = topic_labels or {}
        recent: Counter[tuple[str | None, str]] = Counter()
        prior: Counter[tuple[str | None, str]] = Counter()
        recent_evidence: dict[tuple[str | None, str], list[dict[str, Any]]] = (
            defaultdict(list)
        )
        for w in works:
            pub = (w.get("publication_date") or "")[:4]
            try:
                y = int(pub)
            except (TypeError, ValueError):
                continue
            institutions = {
                str(inst.get("display_name")).strip()
                for authorship in w.get("authorships") or []
                for inst in authorship.get("institutions") or []
                if inst.get("display_name")
            }
            topic_ids: list[str | None] = _monitoring_topic_ids(w) or [None]
            evidence = _work_evidence(w)
            for topic_id in topic_ids:
                for name in institutions:
                    key = (topic_id, name)
                    if y >= start_year:
                        recent[key] += 1
                        if evidence:
                            recent_evidence[key].append(evidence)
                    else:
                        prior[key] += 1

        candidates = []
        for (topic_id, name), count in sorted(
            recent.items(),
            key=lambda item: (item[0][0] or "", item[0][1]),
        ):
            base = prior.get((topic_id, name), 0)
            if (
                count >= INSTITUTION_ENTRY_MIN_WORKS
                and count >= INSTITUTION_ENTRY_MULTIPLIER * max(1, base)
            ):
                metrics: dict[str, Any] = {
                    "institution": name,
                    "recent_works": count,
                    "prior_works": base,
                    "representative_works": _representative_evidence(
                        recent_evidence[(topic_id, name)]
                    ),
                    "evidence_count": count,
                    "window_label": _publication_window_label(year_now, window_years),
                    "baseline_label": f"Before {start_year}",
                }
                if topic_id:
                    metrics["topic_id"] = topic_id
                    if topic_labels.get(topic_id):
                        metrics["topic_label"] = topic_labels[topic_id]
                candidates.append(
                    {
                        "candidate_type": "institution_entry",
                        "subject_ids": [],
                        "observation_window_start": f"{start_year}-01-01",
                        "observation_window_end": now.date().isoformat(),
                        "baseline_definition": f"works published before {start_year}: {base}",
                        "derived_metrics": metrics,
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
        topic_labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Registered trial portfolios spanning multiple phases.

        Sponsor-level portfolios remain the most specific shape.  A topic-level
        cross-sponsor portfolio is also emitted when at least two named studies
        support it, which keeps sparse registries useful without implying that
        a particular trial advanced. ``studies`` contains ClinicalTrials.gov
        v2 records.
        """
        now = now or datetime.now(timezone.utc)
        topic_labels = topic_labels or {}
        sponsor_phases: dict[tuple[str | None, str], set[str]] = defaultdict(set)
        sponsor_studies: dict[tuple[str | None, str], dict[str, dict[str, Any]]] = (
            defaultdict(dict)
        )
        topic_phases: dict[str, set[str]] = defaultdict(set)
        topic_studies: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        topic_sponsors: dict[str, set[str]] = defaultdict(set)
        for s in studies:
            ps = s.get("protocolSection") or {}
            sponsor = (
                (ps.get("sponsorCollaboratorsModule") or {})
                .get("leadSponsor", {})
                .get("name")
            )
            phases = (ps.get("designModule") or {}).get("phases") or []
            if not sponsor:
                continue
            topic_ids: list[str | None] = _monitoring_topic_ids(s) or [None]
            evidence = _study_evidence(s)
            for topic_id in topic_ids:
                key = (topic_id, str(sponsor).strip())
                sponsor_phases[key].update(str(phase) for phase in phases)
                if evidence:
                    sponsor_studies[key][evidence["id"]] = evidence
                if topic_id:
                    topic_phases[topic_id].update(str(phase) for phase in phases)
                    topic_sponsors[topic_id].add(str(sponsor).strip())
                    if evidence:
                        topic_studies[topic_id][evidence["id"]] = evidence

        candidates = []
        phase_rank = {
            "EARLY_PHASE1": 1,
            "PHASE1": 1,
            "PHASE2": 2,
            "PHASE3": 3,
            "PHASE4": 4,
        }
        for (topic_id, sponsor), phases in sorted(
            sponsor_phases.items(),
            key=lambda item: (item[0][0] or "", item[0][1]),
        ):
            ranks = [phase_rank.get(p, 0) for p in phases if p in phase_rank]
            evidence = list(sponsor_studies[(topic_id, sponsor)].values())
            if len({r for r in ranks if r}) >= 2 and len(evidence) >= 2:
                candidates.append(
                    _stage_portfolio_candidate(
                        topic_id=topic_id,
                        topic_label=topic_labels.get(topic_id or ""),
                        entity=sponsor,
                        phases=phases,
                        studies=evidence,
                        now=now,
                        phase_rank=phase_rank,
                        portfolio_scope="sponsor",
                        baseline_definition=(
                            "registered sponsor portfolio phase distribution"
                        ),
                        sponsor=sponsor,
                        sponsor_count=1,
                    )
                )

        for topic_id, phases in sorted(topic_phases.items()):
            ranks = [phase_rank.get(phase, 0) for phase in phases]
            evidence = list(topic_studies[topic_id].values())
            sponsors = topic_sponsors[topic_id]
            if (
                len({rank for rank in ranks if rank}) >= 2
                and len(evidence) >= 2
                and len(sponsors) >= 2
            ):
                candidates.append(
                    _stage_portfolio_candidate(
                        topic_id=topic_id,
                        topic_label=topic_labels.get(topic_id),
                        entity=_cross_sponsor_entity(sponsors),
                        phases=phases,
                        studies=evidence,
                        now=now,
                        phase_rank=phase_rank,
                        portfolio_scope="topic",
                        baseline_definition=(
                            "registered topic portfolio phase distribution across sponsors"
                        ),
                        sponsor_count=len(sponsors),
                        sponsors=sorted(sponsors),
                    )
                )
        return candidates

    def detect_cross_topic_relation(
        self,
        works: list[dict[str, Any]],
        *,
        topic_concepts: dict[str, list[str]],
        window_years: int = 2,
        now: datetime | None = None,
        topic_labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Growth in co-occurrence between two topics' concepts."""
        now = now or datetime.now(timezone.utc)
        year_now = now.year
        start_year = year_now - window_years + 1
        topic_labels = topic_labels or {}
        recent: Counter[tuple[str, str]] = Counter()
        prior: Counter[tuple[str, str]] = Counter()
        recent_evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for w in works:
            pub = (w.get("publication_date") or "")[:4]
            try:
                y = int(pub)
            except (TypeError, ValueError):
                continue
            concepts = {c.get("display_name", "") for c in w.get("concepts") or []}
            pairs = set()
            for tid, names in topic_concepts.items():
                if concepts & set(names):
                    pairs.add(tid)
            if len(pairs) >= 2:
                for a, b in _pair_combinations(sorted(pairs)):
                    if y >= start_year:
                        recent[(a, b)] += 1
                        evidence = _work_evidence(w)
                        if evidence:
                            recent_evidence[(a, b)].append(evidence)
                    else:
                        prior[(a, b)] += 1

        candidates = []
        for (a, b), count in recent.items():
            base = prior.get((a, b), 0)
            if count >= 2 and count > base:
                labels = [topic_labels.get(a), topic_labels.get(b)]
                candidates.append(
                    {
                        "candidate_type": "cross_topic_relation",
                        "subject_ids": [],
                        "observation_window_start": f"{start_year}-01-01",
                        "observation_window_end": now.date().isoformat(),
                        "baseline_definition": f"co-occurrences before {start_year}: {base}",
                        "derived_metrics": {
                            "topics": [a, b],
                            "topic_labels": labels if all(labels) else [],
                            "recent_cooccurrences": count,
                            "prior_cooccurrences": base,
                            "representative_works": _representative_evidence(
                                recent_evidence[(a, b)]
                            ),
                            "evidence_count": count,
                            "window_label": _publication_window_label(
                                year_now, window_years
                            ),
                            "baseline_label": f"Before {start_year}",
                        },
                        "evidence_relation_ids": [],
                        "status": "generated",
                    }
                )
        return candidates

    # --------------------------------------------------------------- storage
    def persist(
        self, candidates: list[dict[str, Any]], section_id: str = "research-frontier"
    ) -> int:
        del section_id  # retained for compatibility; table is Research-specific
        stored = 0
        with self.engine.begin() as conn:
            for c in candidates:
                subject_ids = c.get("subject_ids") or []
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "type": c["candidate_type"],
                            "subjects": subject_ids,
                            "start": c["observation_window_start"],
                            "baseline": c["baseline_definition"],
                            "metrics": _material_metrics(c["derived_metrics"]),
                            "version": CANDIDATE_VERSION,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest()
                result = conn.execute(
                    text(
                        """
                        INSERT INTO research_signal_candidates
                          (candidate_type, subject_ids, observation_window_start,
                           observation_window_end, baseline_definition, derived_metrics,
                           evidence_relation_ids, candidate_generator_version, status,
                           idempotency_key)
                        VALUES
                          (:type, CAST(:subjects AS uuid[]), CAST(:start AS timestamptz),
                           CAST(:end AS timestamptz), :baseline, CAST(:metrics AS jsonb),
                           CAST(:evidence AS uuid[]), :ver, 'generated', :key)
                        ON CONFLICT DO NOTHING
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
                        "key": f"research:{fingerprint}",
                    },
                )
                stored += result.rowcount
        return stored

    def recent_candidates(
        self, candidate_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
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
            {
                "candidate_type": r[0],
                "derived_metrics": r[1],
                "baseline_definition": r[2],
                "status": r[3],
            }
            for r in rows
        ]

    def publication_candidates(self, limit: int = 500) -> list[dict[str, Any]]:
        """Current-version rows considered by the public qualification gate."""

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, candidate_type, derived_metrics, status, created_at,
                           observation_window_start, observation_window_end,
                           baseline_definition, evidence_relation_ids,
                           candidate_generator_version
                    FROM research_signal_candidates
                    WHERE candidate_generator_version = :version
                      AND status IN (
                        'generated', 'shadow_investigation', 'abstained', 'rejected'
                      )
                      AND created_at >= now() - interval '30 days'
                    ORDER BY (status = 'shadow_investigation') DESC,
                             created_at DESC, id
                    LIMIT :limit
                    """
                ),
                {"version": CANDIDATE_VERSION, "limit": limit},
            ).fetchall()
        return [
            {
                "id": str(row[0]),
                "candidate_type": row[1],
                "derived_metrics": row[2],
                "status": row[3],
                "created_at": row[4],
                "observation_window_start": row[5],
                "observation_window_end": row[6],
                "baseline_definition": row[7],
                "evidence_relation_ids": list(row[8] or []),
                "candidate_generator_version": row[9],
            }
            for row in rows
        ]


def _pair_combinations(items: list[str]) -> list[tuple[str, str]]:
    return [
        (items[i], items[j])
        for i in range(len(items))
        for j in range(i + 1, len(items))
    ]


def _material_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Exclude observation-clock labels from semantic candidate identity."""

    return {
        key: value
        for key, value in metrics.items()
        if key not in {"window_label", "baseline_label"}
    }


def _stage_portfolio_candidate(
    *,
    topic_id: str | None,
    topic_label: str | None,
    entity: str,
    phases: set[str],
    studies: list[dict[str, Any]],
    now: datetime,
    phase_rank: dict[str, int],
    portfolio_scope: str,
    baseline_definition: str,
    sponsor: str | None = None,
    sponsor_count: int,
    sponsors: list[str] | None = None,
) -> dict[str, Any]:
    ordered_phases = sorted(
        phases,
        key=lambda phase: (phase_rank.get(phase, 99), phase),
    )
    evidence = studies[:REPRESENTATIVE_EVIDENCE_LIMIT]
    metrics: dict[str, Any] = {
        "entity": entity,
        "portfolio_scope": portfolio_scope,
        "phases": ordered_phases,
        "phase_labels": [_phase_label(phase) for phase in ordered_phases],
        "representative_studies": evidence,
        "study_count": len(studies),
        "sponsor_count": sponsor_count,
        "evidence_count": len(studies),
        "window_label": f"Registry portfolio as of {now:%b %Y}",
        "baseline_label": "Cross-sectional phase coverage",
    }
    if sponsor:
        metrics["sponsor"] = sponsor
    if sponsors:
        metrics["sponsors"] = sponsors
    if topic_id:
        metrics["topic_id"] = topic_id
    if topic_label:
        metrics["topic_label"] = topic_label
    return {
        "candidate_type": "stage_transition",
        "subject_ids": [],
        "observation_window_start": "2020-01-01",
        "observation_window_end": now.date().isoformat(),
        "baseline_definition": baseline_definition,
        "derived_metrics": metrics,
        "evidence_relation_ids": [],
        "status": "generated",
    }


def _monitoring_topic_ids(record: dict[str, Any]) -> list[str]:
    metadata = record.get("_open_signal")
    if not isinstance(metadata, dict):
        return []
    values = metadata.get("monitoring_topic_ids")
    if not isinstance(values, list):
        return []
    return sorted({str(value) for value in values if value})


def _work_evidence(work: dict[str, Any]) -> dict[str, Any] | None:
    identifier = work.get("id") or work.get("doi")
    title = work.get("display_name") or work.get("title")
    if not identifier or not title:
        return None
    return {
        "id": str(identifier),
        "title": str(title)[:240],
        "publication_date": str(work.get("publication_date") or "") or None,
        "cited_by_count": int(work.get("cited_by_count") or 0),
    }


def _study_evidence(study: dict[str, Any]) -> dict[str, Any] | None:
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    identifier = identification.get("nctId")
    title = identification.get("briefTitle") or identification.get("officialTitle")
    if not identifier or not title:
        return None
    status = protocol.get("statusModule") or {}
    sponsor = (
        (protocol.get("sponsorCollaboratorsModule") or {})
        .get("leadSponsor", {})
        .get("name")
    )
    return {
        "id": str(identifier),
        "title": str(title)[:240],
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "sponsor": str(sponsor).strip() if sponsor else None,
        "phases": [
            _phase_label(str(phase))
            for phase in (protocol.get("designModule") or {}).get("phases") or []
        ],
    }


def _cross_sponsor_entity(sponsors: set[str]) -> str:
    ordered = sorted(sponsors)
    if len(ordered) == 2:
        return f"{ordered[0]} + {ordered[1]}"
    return f"{ordered[0]} + {len(ordered) - 1} other sponsors"


def _representative_evidence(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {str(value["id"]): value for value in values if value.get("id")}
    ordered = sorted(
        unique.values(),
        key=lambda value: (
            str(value.get("publication_date") or ""),
            int(value.get("cited_by_count") or 0),
            str(value.get("id") or ""),
        ),
        reverse=True,
    )
    return ordered[:REPRESENTATIVE_EVIDENCE_LIMIT]


def _publication_window_label(year_now: int, window_years: int) -> str:
    start_year = year_now - window_years + 1
    return f"{start_year}–{year_now} YTD"


def _phase_label(value: str) -> str:
    labels = {
        "EARLY_PHASE1": "Early Phase 1",
        "PHASE1": "Phase 1",
        "PHASE2": "Phase 2",
        "PHASE3": "Phase 3",
        "PHASE4": "Phase 4",
        "NA": "Not applicable",
    }
    return labels.get(value, value.replace("_", " ").title())
