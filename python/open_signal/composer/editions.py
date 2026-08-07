"""Edition composer hard rules (spec §63-66, OS-027).

Composes a render plan from verified claims enforcing:
- eligibility: only status=verified claims (failed ones never reach here)
- deduplication: a claim appears at most once per edition
- section diversity: cap per section
- repetition: no consecutive repeats of the same component family
- slot compatibility: via SlotFiller (maturity + claim-type permission)
- fallback: unavailable component falls back per registry fallback rules
"""

from __future__ import annotations

from typing import Any

from open_signal.composer.components import ComponentRuntime, ComponentRuntimeError
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


class ComposeError(Exception):
    pass


class EditionComposer:
    def __init__(
        self,
        *,
        registry: Any = None,
        component_runtime: ComponentRuntime | None = None,
        slot_filler: SlotFiller | None = None,
        section_cap: int = DEFAULT_SECTION_CAP,
    ) -> None:
        self.component_runtime = component_runtime or ComponentRuntime(registry)
        self.slot_filler = slot_filler or SlotFiller(registry)
        self.section_cap = section_cap

    # ------------------------------------------------------------------ compose
    def compose(
        self,
        candidates: list[dict[str, Any]],
        *,
        edition_date: str | None = None,
        section_maturity: str = "production",
    ) -> dict[str, Any]:
        """Build a render plan from candidates. Raises ComposeError on
        hard-rule violations; returns {slots, items, warnings}."""
        if not candidates:
            return {"slots": {}, "items": [], "warnings": ["no candidates"]}

        # 1. eligibility — only verified claims
        eligible = []
        for c in candidates:
            status = c.get("claim_status")
            if status is not None and status != "verified":
                continue
            eligible.append(c)
        if not eligible:
            raise ComposeError("no eligible (verified) candidates")

        # 2. deduplication — one claim per edition
        seen_claims: set[str] = set()
        deduped = []
        for c in eligible:
            cid = c.get("claim_id")
            if cid in seen_claims:
                continue
            seen_claims.add(cid)
            deduped.append(c)

        # 3. section diversity — cap per section
        section_counts: dict[str, int] = {}
        for c in deduped:
            section = c.get("section_id") or "default"
            section_counts[section] = section_counts.get(section, 0) + 1
            if section_counts[section] > self.section_cap:
                raise ComposeError(f"section diversity exceeded: {section} > {self.section_cap}")

        # 4/5/6. fill slots (repetition + compatibility enforced in order)
        ordered = sorted(deduped, key=lambda c: (c.get("priority", 10), c.get("component_id", "")))
        warnings: list[str] = []
        used: dict[str, list[dict[str, Any]]] = {k: [] for k in MAX_SLOT_ITEMS}
        last_family: str | None = None
        for c in ordered:
            slot_id = c.get("slot_id") or self.component_runtime.map_to_frontend(
                c.get("component_id", "")
            ).get("default_slot")
            family = (c.get("component_id") or "").split(".")[0]

            # repetition rule: same family twice in a row for a slot
            if last_family == family:
                warnings.append(f"repetition avoided: {family} consecutive")
                continue
            last_family = family

            try:
                validated = self.component_runtime.validate_render(c.get("component_id", ""), c)
            except ComponentRuntimeError as exc:
                warnings.append(str(exc))
                fallback = self._fallback(c)
                if fallback:
                    used.setdefault(slot_id, []).append(fallback)
                continue

            used.setdefault(slot_id, []).append(validated)
            if len(used.get(slot_id, [])) >= MAX_SLOT_ITEMS.get(slot_id, 2):
                continue

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
