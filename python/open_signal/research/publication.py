"""Public-safe Research Watch contract.

Research candidates are screening records, not Claims.  This module is the
qualification boundary between the internal candidate ledger and the public
front page: it requires an attributed topic, a measurement window, and named
source evidence; writes an event-first headline; and applies diversity caps.
Agent hypotheses and other shadow-ledger prose are intentionally ignored.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

PUBLIC_RESEARCH_LIMIT = 6
MAX_PER_CANDIDATE_TYPE = 2
MAX_PER_TOPIC = 2


def build_public_research_item(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return one qualified public item, or ``None`` for an internal-only row."""

    item, _ = qualify_public_research_item(candidate)
    return item


def qualify_public_research_item(
    candidate: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return a public item or a stable operational rejection reason."""

    candidate_type = str(candidate.get("candidate_type") or "")
    metrics = _mapping(candidate.get("derived_metrics"))
    common = _common_fields(candidate, metrics)
    if common is None:
        return None, _common_rejection_reason(candidate, metrics)

    if candidate_type == "institution_entry":
        institution = _text(metrics.get("institution"))
        topic_id = _text(metrics.get("topic_id"))
        topic_label = _text(metrics.get("topic_label"))
        recent = _number(metrics.get("recent_works"))
        prior = _number(metrics.get("prior_works"))
        evidence = _records(metrics.get("representative_works"))
        if not institution:
            return None, "missing_entity"
        if not topic_id or not topic_label:
            return None, "missing_topic_attribution"
        if not evidence:
            return None, "insufficient_source_evidence"
        if recent is None or prior is None or recent < 1:
            return None, "invalid_metric"
        headline = (
            f"New institutional output appeared in {topic_label}"
            if prior == 0
            else f"Institutional research activity accelerated in {topic_label}"
        )
        return {
            **common,
            "candidate_type": candidate_type,
            "headline": headline,
            "entity": institution,
            "topic_label": topic_label,
            "topic_ids": [topic_id],
            "metric": f"{_count(prior)} → {_count(recent)} works",
            "evidence_count": max(
                len(evidence),
                int(_number(metrics.get("evidence_count")) or 0),
            ),
            "direction": "up" if recent > prior else "neutral",
            "source_label": "OpenAlex",
        }, None

    if candidate_type == "stage_transition":
        entity = _text(metrics.get("sponsor")) or _text(metrics.get("entity"))
        portfolio_scope = _text(metrics.get("portfolio_scope")) or "sponsor"
        topic_id = _text(metrics.get("topic_id"))
        topic_label = _text(metrics.get("topic_label"))
        previous_phases = _texts(metrics.get("previous_phase_labels"))
        phases = _texts(metrics.get("phase_labels")) or [
            _phase_label(value) for value in _texts(metrics.get("phases"))
        ]
        phases = list(dict.fromkeys(phases))
        material_change_at = _iso(metrics.get("material_change_at"))
        evidence = _records(metrics.get("representative_studies"))
        if portfolio_scope == "topic":
            return None, "cross_sponsor_snapshot_is_not_transition"
        if not entity:
            return None, "missing_entity"
        if not topic_id or not topic_label:
            return None, "missing_topic_attribution"
        if len(phases) < 2:
            return None, "insufficient_phase_coverage"
        if len(evidence) < 2:
            return None, "insufficient_source_evidence"
        if not previous_phases or not material_change_at:
            return None, "missing_longitudinal_change"
        added_phases = [phase for phase in phases if phase not in previous_phases]
        if not added_phases:
            return None, "no_material_phase_change"
        study_count = max(
            len(evidence),
            int(_number(metrics.get("study_count")) or 0),
        )
        return {
            **common,
            "candidate_type": candidate_type,
            "headline": (
                f"{topic_label} trial portfolio added {_joined(added_phases)} coverage"
            ),
            "entity": entity,
            "topic_label": topic_label,
            "topic_ids": [topic_id],
            "metric": f"{_joined(previous_phases)} → {_joined(phases)}",
            "evidence_count": study_count,
            "direction": "up",
            "source_label": "ClinicalTrials.gov",
            "material_change_at": material_change_at,
        }, None

    if candidate_type == "cross_topic_relation":
        topic_ids = _texts(metrics.get("topics"))
        topic_labels = _texts(metrics.get("topic_labels"))
        recent = _number(metrics.get("recent_cooccurrences"))
        prior = _number(metrics.get("prior_cooccurrences"))
        evidence = _records(metrics.get("representative_works"))
        if len(topic_ids) != 2 or len(topic_labels) != 2:
            return None, "missing_topic_attribution"
        if not evidence:
            return None, "insufficient_source_evidence"
        if recent is None or prior is None or recent <= prior:
            return None, "invalid_metric"
        return {
            **common,
            "candidate_type": candidate_type,
            "headline": (
                f"Research connections increased: {topic_labels[0]} × {topic_labels[1]}"
            ),
            "entity": "Cross-topic literature",
            "topic_label": " × ".join(topic_labels),
            "topic_ids": topic_ids,
            "metric": f"{_count(prior)} → {_count(recent)} papers",
            "evidence_count": max(
                len(evidence),
                int(_number(metrics.get("evidence_count")) or 0),
            ),
            "direction": "up",
            "source_label": "OpenAlex",
        }, None

    return None, "unsupported_candidate_type"


def public_research_qualification_report(
    candidates: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize why candidate rows did or did not clear the public boundary."""

    reasons: Counter[str] = Counter()
    eligible = 0
    for candidate in candidates:
        item, reason = qualify_public_research_item(candidate)
        if item is not None:
            eligible += 1
        else:
            reasons[reason or "unknown"] += 1
    return {
        "evaluated": len(candidates),
        "eligible": eligible,
        "rejected": len(candidates) - eligible,
        "rejection_reasons": dict(sorted(reasons.items())),
    }


def select_public_research_items(
    candidates: list[Mapping[str, Any]],
    *,
    limit: int = PUBLIC_RESEARCH_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Select a ranked, de-duplicated and topic-diverse public watch list."""

    unique: dict[
        tuple[str, ...],
        tuple[str, float, dict[str, Any], str],
    ] = {}
    for candidate in candidates:
        item = build_public_research_item(candidate)
        if item is None:
            continue
        identity = _identity(item)
        ranked_candidate = (
            str(item.get("detected_at") or ""),
            _selection_score(candidate, item),
            item,
            str(candidate.get("status") or ""),
        )
        if identity not in unique or ranked_candidate[:2] > unique[identity][:2]:
            unique[identity] = ranked_candidate

    ranked = sorted(
        (
            (score, item)
            for _, score, item, status in unique.values()
            if status == "shadow_investigation"
        ),
        key=lambda value: (
            value[0],
            str(value[1].get("detected_at") or ""),
            str(value[1].get("id") or ""),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()

    # Give each available signal shape one opportunity before filling by rank.
    for _, item in ranked:
        if type_counts[item["candidate_type"]] or not _fits(
            item,
            type_counts=type_counts,
            topic_counts=topic_counts,
        ):
            continue
        _append(selected, item, type_counts, topic_counts)
        if len(selected) >= limit:
            return selected, len(unique)

    for _, item in ranked:
        if item in selected or not _fits(
            item,
            type_counts=type_counts,
            topic_counts=topic_counts,
        ):
            continue
        _append(selected, item, type_counts, topic_counts)
        if len(selected) >= limit:
            break
    return selected, sum(
        status == "shadow_investigation"
        for _, _, _, status in unique.values()
    )


def _common_fields(
    candidate: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any] | None:
    window_label = _text(metrics.get("window_label"))
    baseline_label = _text(metrics.get("baseline_label"))
    detected_at = _iso(candidate.get("created_at"))
    candidate_id = _text(candidate.get("id"))
    if not candidate_id or not window_label or not baseline_label or not detected_at:
        return None
    return {
        "id": candidate_id,
        "window_label": window_label,
        "baseline_label": baseline_label,
        "screening_stage": (
            "investigated"
            if candidate.get("status") == "shadow_investigation"
            else "detected"
        ),
        "detected_at": detected_at,
    }


def _common_rejection_reason(
    candidate: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    if not _text(candidate.get("id")):
        return "missing_candidate_id"
    if not _text(metrics.get("window_label")) or not _text(
        metrics.get("baseline_label")
    ):
        return "missing_measurement_window"
    if not _iso(candidate.get("created_at")):
        return "missing_detection_timestamp"
    return "invalid_publication_metadata"


def _selection_score(
    candidate: Mapping[str, Any],
    item: Mapping[str, Any],
) -> float:
    metrics = _mapping(candidate.get("derived_metrics"))
    score = 100.0 if candidate.get("status") == "shadow_investigation" else 0.0
    score += min(20.0, float(item.get("evidence_count") or 0))
    if item.get("candidate_type") == "institution_entry":
        recent = _number(metrics.get("recent_works")) or 0.0
        prior = _number(metrics.get("prior_works")) or 0.0
        score += min(40.0, recent + (recent / max(1.0, prior)) * 4.0)
    elif item.get("candidate_type") == "stage_transition":
        score += len(_texts(metrics.get("phase_labels"))) * 8.0
    else:
        recent = _number(metrics.get("recent_cooccurrences")) or 0.0
        prior = _number(metrics.get("prior_cooccurrences")) or 0.0
        score += min(40.0, recent + max(0.0, recent - prior) * 4.0)
    return score


def _identity(item: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(item.get("candidate_type") or ""),
        *sorted(str(value) for value in item.get("topic_ids") or []),
        str(item.get("entity") or "").casefold(),
    )


def _fits(
    item: Mapping[str, Any],
    *,
    type_counts: Counter[str],
    topic_counts: Counter[str],
) -> bool:
    candidate_type = str(item["candidate_type"])
    if type_counts[candidate_type] >= MAX_PER_CANDIDATE_TYPE:
        return False
    return all(
        topic_counts[str(topic_id)] < MAX_PER_TOPIC
        for topic_id in item.get("topic_ids") or []
    )


def _append(
    selected: list[dict[str, Any]],
    item: dict[str, Any],
    type_counts: Counter[str],
    topic_counts: Counter[str],
) -> None:
    selected.append(item)
    type_counts[item["candidate_type"]] += 1
    for topic_id in item.get("topic_ids") or []:
        topic_counts[str(topic_id)] += 1


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, Mapping) and entry.get("id")]


def _texts(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(entry).strip()
        for entry in value
        if entry is not None and str(entry).strip()
    ]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _count(value: float) -> str:
    return f"{value:g}"


def _joined(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _phase_label(value: str) -> str:
    labels = {
        "EARLY_PHASE1": "Early Phase 1",
        "PHASE1": "Phase 1",
        "PHASE2": "Phase 2",
        "PHASE3": "Phase 3",
        "PHASE4": "Phase 4",
    }
    return labels.get(value, value.replace("_", " ").title())


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value else None
