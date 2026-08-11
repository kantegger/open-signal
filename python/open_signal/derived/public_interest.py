"""Versioned editorial-scope policy for Expectations.

Numerical movement detects that something changed.  This module separately
decides where that change may appear.  The separation is deliberate: a large
move in a routine contract must never outrank a smaller but consequential
public-affairs signal merely because it moved more.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "infra" / "registries" / "editorial-scope-registry.yaml"


@dataclass(frozen=True, slots=True)
class EditorialScopeDecision:
    policy_version: str
    rule_id: str
    category: str
    maximum_surface: str
    importance_score: int
    reasons: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()

    def allows(self, surface: str) -> bool:
        return surface_rank(self.maximum_surface) >= surface_rank(surface)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "rule_id": self.rule_id,
            "category": self.category,
            "maximum_surface": self.maximum_surface,
            "importance_score": self.importance_score,
            "reasons": list(self.reasons),
            "matched_terms": list(self.matched_terms),
        }


@lru_cache(maxsize=1)
def load_editorial_scope_policy() -> dict[str, Any]:
    with POLICY_PATH.open(encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    order = policy.get("surface_order")
    if not isinstance(order, list) or order != [
        "monitor",
        "explore",
        "live_feed",
        "secondary",
        "hero",
    ]:
        raise ValueError("editorial scope policy has an invalid surface_order")
    if not str(policy.get("version") or "").strip():
        raise ValueError("editorial scope policy requires a version")
    return policy


def surface_rank(surface: str) -> int:
    order = load_editorial_scope_policy()["surface_order"]
    try:
        return order.index(surface)
    except ValueError:
        return -1


def classify_expectation_scope(
    *,
    title: str,
    as_of: datetime,
    deadline_at: datetime | None = None,
    event_title: str | None = None,
    event_slug: str | None = None,
    event_type: str | None = None,
    tags: Iterable[str] = (),
    current_probability: float | None = None,
    delta_24h: float | None = None,
) -> EditorialScopeDecision:
    """Return the highest public surface an expectation may occupy."""

    policy = load_editorial_scope_policy()
    as_of = _utc(as_of)
    deadline = _utc(deadline_at) if deadline_at is not None else None
    tag_terms = _normalized_terms([*tags, event_type or ""])
    text_value = " ".join(
        value
        for value in (title, event_title, event_slug, event_type)
        if isinstance(value, str) and value.strip()
    )

    selected: Mapping[str, Any] | None = None
    matched: tuple[str, ...] = ()
    for rule in policy.get("routine_rules") or []:
        matched = _match_rule(
            rule,
            text_value=text_value,
            tag_terms=tag_terms,
            as_of=as_of,
            deadline_at=deadline,
        )
        if matched:
            selected = rule
            break

    if selected is None:
        matches: list[tuple[int, Mapping[str, Any], tuple[str, ...]]] = []
        for rule in policy.get("public_interest_rules") or []:
            rule_match = _match_rule(
                rule,
                text_value=text_value,
                tag_terms=tag_terms,
                as_of=as_of,
                deadline_at=deadline,
            )
            if rule_match:
                matches.append((int(rule.get("importance_score") or 0), rule, rule_match))
        if matches:
            _, selected, matched = max(matches, key=lambda item: item[0])

    if selected is None:
        selected = policy["default"]
        matched = ()

    decision = EditorialScopeDecision(
        policy_version=str(policy["version"]),
        rule_id=str(selected["id"] if "id" in selected else selected["rule_id"]),
        category=str(selected["category"]),
        maximum_surface=str(selected["maximum_surface"]),
        importance_score=int(selected["importance_score"]),
        reasons=(str(selected["reason"]),),
        matched_terms=matched,
    )
    return _apply_near_resolution_convergence(
        decision,
        policy=policy,
        as_of=as_of,
        deadline_at=deadline,
        current_probability=current_probability,
        delta_24h=delta_24h,
    )


def decision_from_render_candidate(
    candidate: Mapping[str, Any], *, as_of: datetime
) -> EditorialScopeDecision:
    """Read a persisted decision or conservatively classify a legacy item."""

    hidden = _object(candidate.get("hidden_detail_fields"))
    persisted = _object(hidden.get("public_interest"))
    if persisted:
        try:
            return EditorialScopeDecision(
                policy_version=str(persisted["policy_version"]),
                rule_id=str(persisted["rule_id"]),
                category=str(persisted["category"]),
                maximum_surface=str(persisted["maximum_surface"]),
                importance_score=int(persisted["importance_score"]),
                reasons=tuple(str(value) for value in persisted.get("reasons") or ()),
                matched_terms=tuple(
                    str(value) for value in persisted.get("matched_terms") or ()
                ),
            )
        except (KeyError, TypeError, ValueError):
            pass

    fields = _object(candidate.get("display_fields"))
    calculation = _object(hidden.get("calculation"))
    deadline = candidate.get("resolution_deadline_at") or fields.get(
        "resolution_deadline_at"
    )
    decision = classify_expectation_scope(
        title=str(
            candidate.get("headline")
            or fields.get("expectation_title")
            or fields.get("headline")
            or ""
        ),
        event_title=_text(fields.get("event_title")),
        event_type=_text(fields.get("event_type")),
        tags=fields.get("tags") if isinstance(fields.get("tags"), list) else (),
        deadline_at=_datetime(deadline),
        current_probability=_number(fields.get("current_probability")),
        delta_24h=_number(
            fields.get("delta_percentage_points") or calculation.get("delta_24h")
        ),
        as_of=as_of,
    )
    if decision.rule_id != "contextual-default":
        return decision

    # Editions published before this policy do not carry a persisted scope
    # decision.  Explicit routine/public-interest matches above are safe to
    # reclassify, but an unknown legacy title is not evidence that an editor's
    # previous placement was wrong.  Preserve that placement until the item is
    # naturally refreshed or retired; all newly generated candidates persist
    # a policy decision and therefore never use this compatibility path.
    legacy_surface = {
        "lead": "hero",
        "secondary": "secondary",
        "main": "secondary",
        "live_feed": "live_feed",
        "digest": "live_feed",
        "utility": "explore",
        "archive": "explore",
    }.get(str(candidate.get("slot_id") or ""))
    if legacy_surface and surface_rank(legacy_surface) > surface_rank(
        decision.maximum_surface
    ):
        return replace(
            decision,
            rule_id="legacy-slot-preserved",
            maximum_surface=legacy_surface,
            reasons=(
                *decision.reasons,
                "Legacy edition had no scope metadata; preserve its prior placement.",
            ),
        )
    return decision


def _apply_near_resolution_convergence(
    decision: EditorialScopeDecision,
    *,
    policy: Mapping[str, Any],
    as_of: datetime,
    deadline_at: datetime | None,
    current_probability: float | None,
    delta_24h: float | None,
) -> EditorialScopeDecision:
    config = policy.get("near_resolution_convergence") or {}
    if (
        deadline_at is None
        or current_probability is None
        or delta_24h is None
        or surface_rank(decision.maximum_surface) < surface_rank("hero")
    ):
        return decision
    remaining_hours = (deadline_at - as_of).total_seconds() / 3600
    if not 0 <= remaining_hours <= float(config.get("within_hours") or 0):
        return decision
    extreme = float(config.get("extreme_probability") or 0.15)
    converging = (current_probability <= extreme and delta_24h < 0) or (
        current_probability >= 1 - extreme and delta_24h > 0
    )
    if not converging:
        return decision
    return replace(
        decision,
        maximum_surface=str(config.get("maximum_surface") or "secondary"),
        importance_score=max(
            0,
            decision.importance_score - int(config.get("importance_penalty") or 0),
        ),
        reasons=(*decision.reasons, str(config.get("reason") or "Near resolution.")),
        matched_terms=(*decision.matched_terms, "near_resolution_convergence"),
    )


def _match_rule(
    rule: Mapping[str, Any],
    *,
    text_value: str,
    tag_terms: set[str],
    as_of: datetime,
    deadline_at: datetime | None,
) -> tuple[str, ...]:
    match = rule.get("match") or {}
    tags = [str(value) for value in match.get("tags_any") or ()]
    patterns = [str(value) for value in match.get("text_patterns_any") or ()]
    tag_matches = tuple(
        value for value in tags if _normalize_term(value) in tag_terms
    )
    text_matches = tuple(
        pattern for pattern in patterns if re.search(pattern, text_value, re.IGNORECASE)
    )
    if match.get("requires_tag_and_text"):
        if not tag_matches or not text_matches:
            return ()
    elif not tag_matches and not text_matches:
        return ()

    within = match.get("resolution_within_hours")
    if within is not None:
        if deadline_at is None:
            return ()
        remaining = (deadline_at - as_of).total_seconds() / 3600
        if not 0 <= remaining <= float(within):
            return ()
    return (*tag_matches, *text_matches)


def _normalized_terms(values: Iterable[str]) -> set[str]:
    return {
        normalized
        for value in values
        if (normalized := _normalize_term(value))
    }


def _normalize_term(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
