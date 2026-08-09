"""Edition composer hard rules (spec §63-66, OS-027).

Composes a render plan from verified claims enforcing:
- eligibility: only status=verified claims (failed ones never reach here)
- deduplication: one full presentation plus at most one compact index echo
- section diversity: cap full editorial surfaces per section
- repetition: no consecutive repeats of the same component family
- slot compatibility: via SlotFiller (maturity + claim-type permission)
- fallback: unavailable component falls back per registry fallback rules
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from open_signal.composer.components import ComponentRuntime, ComponentRuntimeError
from open_signal.composer.freshness import FreshnessEvaluator
from open_signal.composer.slots import SlotFiller

DEFAULT_SECTION_CAP = 3
MAX_SLOT_ITEMS = {
    "lead": 1,
    "secondary": 2,
    "live_feed": 5,
    "digest": 3,
    "main": 1,
    "utility": 2,
    "archive": 2,
}

PUBLIC_CLAIM_STATUSES = {"verified", "published", "active"}
RETIREMENT_STATUSES = {"withdrawn", "expired", "superseded", "retracted"}
ACCOUNTABILITY_FAMILIES = {"resolution", "archive-snapshot"}


class ComposeError(Exception):
    pass


class EditionComposer:
    def __init__(
        self,
        *,
        registry: Any = None,
        component_runtime: ComponentRuntime | None = None,
        slot_filler: SlotFiller | None = None,
        freshness_evaluator: FreshnessEvaluator | None = None,
        section_cap: int = DEFAULT_SECTION_CAP,
    ) -> None:
        self.component_runtime = component_runtime or ComponentRuntime(registry)
        self.slot_filler = slot_filler or SlotFiller(registry)
        self.freshness_evaluator = freshness_evaluator or FreshnessEvaluator(
            self.component_runtime.registry
        )
        self.section_cap = section_cap

    # ------------------------------------------------------------------ compose
    def compose(
        self,
        candidates: list[dict[str, Any]],
        *,
        edition_date: str | None = None,
        section_maturity: str = "production",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build a render plan from candidates. Raises ComposeError on
        hard-rule violations; returns {slots, items, warnings}."""
        if not candidates:
            return {"slots": {}, "items": [], "warnings": ["no candidates"]}

        # 1. eligibility — verification state + semantic/elapsed freshness.
        eligible = []
        warnings: list[str] = []
        handled_candidates = 0
        for c in candidates:
            status = c.get("claim_status")
            family = (c.get("component_id") or "").split(".")[0]
            is_accountability_claim = (
                status == "resolved" and family in ACCOUNTABILITY_FAMILIES
            )
            is_retirement_event = status in RETIREMENT_STATUSES or (
                status == "resolved" and not is_accountability_claim
            )
            if status is not None and not (
                status in PUBLIC_CLAIM_STATUSES
                or is_accountability_claim
                or is_retirement_event
            ):
                continue

            handled_candidates += 1
            if status == "resolved" and not is_accountability_claim:
                warnings.append(
                    f"retired {c.get('claim_id') or 'candidate'}: "
                    "resolved claim requires an accountability component"
                )
                continue

            decision = self.freshness_evaluator.evaluate(c, now=now)
            if not decision.eligible:
                warnings.append(
                    f"retired {c.get('claim_id') or 'candidate'}: {decision.reason}"
                )
                continue
            normalized = dict(c)
            normalized["freshness_state"] = decision.state
            normalized["freshness_policy_id"] = decision.policy_id
            normalized["expires_at"] = (
                decision.expires_at.isoformat() if decision.expires_at else None
            )
            if decision.anchor_at is not None:
                normalized.setdefault(
                    "materially_updated_at", decision.anchor_at.isoformat()
                )
            if decision.demote_from_lead:
                normalized["slot_id"] = "secondary"
                normalized["component_variant"] = "standard"
                warnings.append(
                    f"demoted {c.get('claim_id') or 'candidate'}: lead tenure exceeded"
                )
            eligible.append(normalized)
        if not eligible and handled_candidates:
            # A retirement compile is still a valid compile. Publishing an
            # immutable empty-content snapshot advances the channel away from
            # hard-expired material while the presenter preserves all seven
            # Slot descriptors, Site Shell, status, and archive surfaces.
            return {
                "slots": {slot_id: [] for slot_id in MAX_SLOT_ITEMS},
                "items": [],
                "warnings": warnings or ["all candidates retired"],
            }
        if not eligible:
            raise ComposeError("no eligible (verified) candidates")

        # 2. deduplication — one primary presentation and, optionally, one
        # compact index echo.  The echo makes a featured Claim discoverable in
        # a scan surface without manufacturing a second Claim.
        seen_claims: set[tuple[str, str]] = set()
        deduped = []
        for index, c in enumerate(eligible):
            cid = str(c.get("claim_id") or f"anonymous:{index}")
            role = _presentation_role(c)
            key = (cid, role)
            if key in seen_claims:
                continue
            seen_claims.add(key)
            deduped.append(c)

        # 3. section diversity — cap only full editorial surfaces.  Compact
        # feeds and indices are intentionally list-shaped and may repeat a
        # Section while preserving the editorial cap above them.
        section_counts: dict[str, int] = {}
        for c in deduped:
            if c.get("slot_id") not in {"lead", "secondary", "main"}:
                continue
            section = c.get("section_id") or "default"
            section_counts[section] = section_counts.get(section, 0) + 1
            if section_counts[section] > self.section_cap:
                raise ComposeError(
                    f"section diversity exceeded: {section} > {self.section_cap}"
                )

        # 4/5/6. fill slots (repetition + compatibility enforced in order)
        ordered = sorted(
            deduped, key=lambda c: (c.get("priority", 10), c.get("component_id", ""))
        )
        used: dict[str, list[dict[str, Any]]] = {k: [] for k in MAX_SLOT_ITEMS}
        last_family: dict[str, str | None] = {}  # per-slot repetition tracking
        for c in ordered:
            slot_id = c.get("slot_id") or self.component_runtime.map_to_frontend(
                c.get("component_id", "")
            ).get("default_slot")
            family = (c.get("component_id") or "").split(".")[0]

            definition = self.slot_filler.slot_definition(slot_id)
            capacity = (
                definition["maximum_items"]
                if definition
                else MAX_SLOT_ITEMS.get(slot_id, 2)
            )
            if len(used.setdefault(slot_id, [])) >= capacity:
                warnings.append(f"slot capacity reached: {slot_id}")
                continue

            # Repetition is an editorial-layout rule.  Feed/table slots are
            # intentionally homogeneous and would otherwise collapse to one
            # row despite declaring multi-item capacity.
            if (
                slot_id in {"lead", "secondary", "main"}
                and last_family.get(slot_id) == family
            ):
                warnings.append(
                    f"repetition avoided: {family} consecutive in {slot_id}"
                )
                continue
            last_family[slot_id] = family

            try:
                validated = self.component_runtime.validate_render(
                    c.get("component_id", ""), c
                )
            except ComponentRuntimeError as exc:
                warnings.append(str(exc))
                fallback = self._fallback(c)
                if fallback:
                    used.setdefault(slot_id, []).append(fallback)
                continue

            used.setdefault(slot_id, []).append(validated)

        items = [i for slot_items in used.values() for i in slot_items]
        return {"slots": used, "items": items, "warnings": warnings}

    # ------------------------------------------------------------------ fallback
    def _fallback(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        """Registry fallback: same family fallback component."""
        component_id = candidate.get("component_id", "")
        definition = self.component_runtime.registry.component(component_id)
        if definition is None or not definition.fallback_component_id:
            return None
        fb = self.component_runtime.registry.component(definition.fallback_component_id)
        if fb is None:
            return None
        candidate = dict(candidate)
        candidate["component_id"] = fb.id
        candidate["component_version"] = fb.version
        candidate["_fallback_from"] = component_id
        return candidate


def _presentation_role(candidate: dict[str, Any]) -> str:
    explicit = candidate.get("presentation_role")
    if explicit == "index_echo" or candidate.get("slot_id") == "digest":
        return "index_echo"
    return "primary"
