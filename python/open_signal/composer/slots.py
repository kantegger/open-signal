"""Slot filler (spec §47-50, OS-026).

Fills the seven slot types (lead / secondary / live_feed / digest / main /
utility / archive) from validated render candidates, enforcing maturity and
claim-type permissions from the slot registry.
"""

from __future__ import annotations

from typing import Any

from open_signal.sources.registry import Registry

# claim_type -> permission key on the slot definition
CLAIM_PERMISSION = {
    "derived_observation": "allows_observation",
    "agent_observation": "allows_analysis",
    "rule_change_observation": "allows_analysis",
    "research_observation": "allows_analysis",
}

MATURITY_RANK = {"concept": 0, "shadow": 1, "beta": 2, "production": 3}


class SlotFillError(Exception):
    pass


class SlotFiller:
    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry.load()
        self._by_type: dict[str, Any] = {}
        for slot in self.registry.slots():
            self._by_type.setdefault(slot.type, slot)

    def _resolve(self, slot_ref: str) -> Any:
        slot = self.registry.slot(slot_ref)
        if slot is None:
            slot = self._by_type.get(slot_ref)
        if slot is None:
            raise SlotFillError(f"unknown slot {slot_ref!r}")
        return slot

    # ------------------------------------------------------------ permissions
    def check_maturity(self, slot_ref: str, section_maturity: str) -> bool:
        slot = self._resolve(slot_ref)
        required = slot.minimum_section_maturity
        return MATURITY_RANK.get(section_maturity, 0) >= MATURITY_RANK.get(required, 0)

    def check_claim_permission(self, slot_ref: str, claim_type: str) -> bool:
        slot = self._resolve(slot_ref)
        permission = CLAIM_PERMISSION.get(claim_type)
        if permission is None:
            return False
        return bool(getattr(slot, permission))

    # ------------------------------------------------------------------ fill
    def fill_slot(
        self,
        slot_ref: str,
        candidates: list[dict[str, Any]],
        *,
        section_maturity: str = "production",
    ) -> list[dict[str, Any]]:
        """Pick candidates for one slot: maturity + permission + capacity."""
        if not self.check_maturity(slot_ref, section_maturity):
            raise SlotFillError(
                f"slot {slot_ref} requires maturity "
                f"{self._resolve(slot_ref).minimum_section_maturity}, section is {section_maturity}"
            )
        slot = self._resolve(slot_ref)
        capacity = slot.maximum_items

        eligible = []
        for c in candidates:
            claim_type = c.get("claim_type") or "derived_observation"
            if not self.check_claim_permission(slot_ref, claim_type):
                continue
            if slot.allowed_component_family_ids:
                family = (c.get("component_id") or "").split(".")[0]
                if family not in slot.allowed_component_family_ids:
                    continue
            eligible.append(c)

        # heroes for the lead slot; priority order otherwise
        if slot.type == "lead":
            heroes = [c for c in eligible if c.get("is_hero")]
            chosen = heroes[:capacity] if heroes else eligible[:capacity]
        else:
            chosen = eligible[:capacity]
        return chosen

    def fill_page(
        self,
        candidates: list[dict[str, Any]],
        *,
        section_maturity: str = "production",
    ) -> dict[str, list[dict[str, Any]]]:
        """Fill all seven slots from a candidate pool (dedup by claim_id)."""
        seen: set[str] = set()
        used: dict[str, list[dict[str, Any]]] = {}
        for slot_id in ("lead", "secondary", "live_feed", "digest", "main", "utility", "archive"):
            remaining = [c for c in candidates if c.get("claim_id") not in seen]
            try:
                chosen = self.fill_slot(slot_id, remaining, section_maturity=section_maturity)
            except SlotFillError:
                chosen = []
            used[slot_id] = chosen
            for c in chosen:
                if c.get("claim_id"):
                    seen.add(c["claim_id"])
        return used

    def slot_definition(self, slot_ref: str) -> dict[str, Any] | None:
        try:
            slot = self._resolve(slot_ref)
        except SlotFillError:
            return None
        return {
            "id": slot.id,
            "type": slot.type,
            "size": slot.size,
            "required": slot.required,
            "maximum_items": slot.maximum_items,
            "minimum_section_maturity": slot.minimum_section_maturity,
        }
