"""Rolling publication freshness and retirement rules.

Freshness is deliberately independent from calendar dates.  The evaluator
applies Claim validity and semantic invalidators first, then the registry's
soft/hard elapsed-age policy.  It never mutates Claims; it only decides whether
a Render Plan candidate may enter the next immutable edition snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from open_signal.sources.registry import FreshnessPolicyDefinition, Registry


@dataclass(frozen=True)
class FreshnessDecision:
    state: str
    policy_id: str
    anchor_at: datetime | None
    expires_at: datetime | None
    reason: str | None = None
    demote_from_lead: bool = False

    @property
    def eligible(self) -> bool:
        return self.state != "expired"


class FreshnessEvaluator:
    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry.load()

    @property
    def policy_version(self) -> str:
        return self.registry.freshness_policy_version

    def policy_for(self, candidate: dict[str, Any]) -> FreshnessPolicyDefinition:
        section_id = str(candidate.get("section_id") or "default")
        slot_type = str(candidate.get("slot_id") or "main")
        for policy in self.registry.freshness_policies():
            section_match = not policy.section_ids or section_id in policy.section_ids or "*" in policy.section_ids
            slot_match = not policy.slot_types or slot_type in policy.slot_types or "*" in policy.slot_types
            if section_match and slot_match:
                return policy
        default = self.registry.freshness_policy("default")
        if default is None:  # Registry.validate reports this; keep runtime failure explicit.
            raise RuntimeError("freshness registry has no default policy")
        return default

    def evaluate(
        self,
        candidate: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> FreshnessDecision:
        now = _utc(now or datetime.now(timezone.utc))
        policy = self.policy_for(candidate)

        semantic_states = {
            str(value).lower()
            for value in (
                candidate.get("claim_status"),
                candidate.get("semantic_state"),
                candidate.get("source_status"),
            )
            if value
        }
        invalidator = next((state for state in semantic_states if state in policy.semantic_invalidators), None)
        if invalidator:
            return FreshnessDecision(
                state="expired",
                policy_id=policy.id,
                anchor_at=self._anchor(candidate),
                expires_at=now,
                reason=f"semantic invalidator: {invalidator}",
            )

        valid_until = _parse_time(candidate.get("valid_until"))
        if valid_until is not None and valid_until <= now:
            return FreshnessDecision(
                state="expired",
                policy_id=policy.id,
                anchor_at=self._anchor(candidate),
                expires_at=valid_until,
                reason="claim validity ended",
            )

        anchor = self._anchor(candidate)
        hard_expires = (
            anchor + timedelta(hours=policy.hard_age_hours)
            if anchor is not None and policy.hard_age_hours is not None
            else None
        )
        expires_at = _earliest(valid_until, hard_expires)
        if hard_expires is not None and hard_expires <= now:
            return FreshnessDecision(
                state="expired",
                policy_id=policy.id,
                anchor_at=anchor,
                expires_at=expires_at,
                reason=f"hard age exceeded ({policy.hard_age_hours:g}h)",
            )

        soft_at = (
            anchor + timedelta(hours=policy.soft_age_hours)
            if anchor is not None and policy.soft_age_hours is not None
            else None
        )
        state = "aging" if soft_at is not None and soft_at <= now else "current"
        demote = bool(
            candidate.get("slot_id") == "lead"
            and anchor is not None
            and policy.lead_tenure_hours is not None
            and anchor + timedelta(hours=policy.lead_tenure_hours) <= now
        )
        reason = "soft age exceeded" if state == "aging" else None
        if demote:
            reason = "lead tenure exceeded without material evidence"
        return FreshnessDecision(
            state=state,
            policy_id=policy.id,
            anchor_at=anchor,
            expires_at=expires_at,
            reason=reason,
            demote_from_lead=demote,
        )

    @staticmethod
    def _anchor(candidate: dict[str, Any]) -> datetime | None:
        fields = candidate.get("display_fields") or {}
        for value in (
            candidate.get("materially_updated_at"),
            fields.get("materially_updated_at"),
            candidate.get("data_as_of"),
            fields.get("data_as_of"),
            fields.get("updated_at"),
            candidate.get("assessed_at"),
            candidate.get("issued_at"),
        ):
            parsed = _parse_time(value)
            if parsed is not None:
                return parsed
        return None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _earliest(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None
