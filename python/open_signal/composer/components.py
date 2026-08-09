"""Composer component runtime (spec §78, §52-56, OS-025).

Turns validated Claims into render candidates backed by the component
registry (infra/registries/component-registry.yaml):
- first-batch mapping (8 components for launch)
- runtime validation against registry definitions (required fields,
  allowed slots, narrative mode)
- frontend component mapping (component_id -> frontend key + props)
"""

from __future__ import annotations

from typing import Any

from open_signal.sources.registry import Registry

# launch batch (spec §78 / OS-025): component_id -> frontend key
FIRST_BATCH: dict[str, dict[str, Any]] = {
    "time-series.probability-move": {
        "frontend_key": "ProbabilityMoveChart",
        "default_slot": "secondary",
        "display_type": "line_chart",
        "title": "Probability Move",
    },
    "state-transition.rule-stage": {
        "frontend_key": "RuleStageTimeline",
        "default_slot": "main",
        "display_type": "timeline",
        "title": "Rule Stage Transition",
    },
    "state-transition.effective-timeline": {
        "frontend_key": "EffectiveTimeline",
        "default_slot": "secondary",
        "display_type": "timeline",
        "title": "Effective Timeline",
    },
    "evidence-relationship.evidence-timeline": {
        "frontend_key": "EvidenceTimeline",
        "default_slot": "secondary",
        "display_type": "timeline",
        "title": "Evidence Timeline",
    },
    "evidence-relationship.cross-field-bridge": {
        "frontend_key": "CrossFieldBridge",
        "default_slot": "main",
        "display_type": "relationship",
        "title": "Cross-field Bridge",
    },
    "document-change.rule-diff": {
        "frontend_key": "SignificantChanges",
        "default_slot": "main",
        "display_type": "change_list",
        "title": "Significant Changes",
    },
    "archive-snapshot.archive-card": {
        "frontend_key": "ArchiveSnapshot",
        "default_slot": "archive",
        "display_type": "snapshot",
        "title": "Archive Snapshot",
    },
    "signal-hero.expectations": {
        "frontend_key": "SignalHero",
        "default_slot": "lead",
        "display_type": "hero",
        "title": "Signal Hero",
    },
}

FAMILY_FRONTEND: dict[str, str] = {
    "signal-hero": "SignalHero",
    "time-series": "TimeSeries",
    "state-transition": "StateTransition",
    "document-change": "DocumentChange",
    "signal-feed": "SignalFeed",
    "evidence-relationship": "EvidenceRelationship",
    "resolution-comparison": "ResolutionComparison",
    "archive-snapshot": "ArchiveSnapshot",
}

SLOT_ALIASES = {
    "time-series.probability-move": "time-series",
    "state-transition.rule-stage": "state-transition",
    "state-transition.effective-timeline": "state-transition",
    "evidence-relationship.evidence-timeline": "evidence-relationship",
    "evidence-relationship.cross-field-bridge": "evidence-relationship",
    "document-change.rule-diff": "document-change",
    "archive-snapshot.archive-card": "archive-snapshot",
    "signal-hero.expectations": "signal-hero",
}


class ComponentRuntimeError(Exception):
    pass


class ComponentRuntime:
    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry.load()

    # ------------------------------------------------------------- first batch
    def first_batch(self) -> list[dict[str, Any]]:
        out = []
        for component_id, meta in FIRST_BATCH.items():
            definition = self.registry.component(component_id)
            out.append(
                {
                    "component_id": component_id,
                    "frontend_key": meta["frontend_key"],
                    "default_slot": meta["default_slot"],
                    "display_type": meta["display_type"],
                    "title": meta["title"],
                    "version": definition.version if definition else None,
                    "narrative_mode": definition.narrative_mode if definition else None,
                }
            )
        return out

    # ---------------------------------------------------------------- mapping
    def map_to_frontend(self, component_id: str) -> dict[str, Any]:
        meta = FIRST_BATCH.get(component_id)
        if meta is not None:
            return {"component_id": component_id, **meta}
        definition = self.registry.component(component_id)
        if definition is None:
            raise ComponentRuntimeError(f"unknown component {component_id!r}")
        frontend_key = FAMILY_FRONTEND.get(definition.family_id)
        if frontend_key is None:
            raise ComponentRuntimeError(f"unsupported component family {definition.family_id!r}")
        default_slot = definition.supported_slot_types[0] if definition.supported_slot_types else "main"
        return {
            "component_id": component_id,
            "frontend_key": frontend_key,
            "default_slot": default_slot,
            "display_type": definition.family_id,
            "title": component_id.rsplit(".", 1)[-1].replace("-", " ").title(),
        }

    # --------------------------------------------------------------- validation
    def validate_render(self, component_id: str, render_candidate: dict[str, Any]) -> dict[str, Any]:
        """Validate a render candidate against the registry definition.

        Returns the normalized candidate; raises ComponentRuntimeError on
        missing required fields / disallowed slot / narrative mismatch.
        """
        definition = self.registry.component(component_id)
        if definition is None:
            raise ComponentRuntimeError(f"unknown component {component_id!r}")

        display_fields = render_candidate.get("display_fields") or {}
        missing = [f for f in definition.required_fields if f not in display_fields]
        if missing:
            raise ComponentRuntimeError(f"{component_id}: missing required fields {missing}")

        slot_id = render_candidate.get("slot_id") or FIRST_BATCH.get(component_id, {}).get("default_slot")
        family = definition.family_id
        allowed_slots = {s.type for s in self.registry.slots() if family in s.allowed_component_family_ids}
        if allowed_slots and slot_id not in allowed_slots:
            raise ComponentRuntimeError(
                f"{component_id}: slot {slot_id!r} not allowed (allowed: {sorted(allowed_slots)})"
            )

        narrative = render_candidate.get("narrative_mode")
        if narrative and narrative != definition.narrative_mode:
            raise ComponentRuntimeError(
                f"{component_id}: narrative_mode {narrative!r} != registry {definition.narrative_mode!r}"
            )

        # prohibited uses
        for use in definition.prohibited_uses:
            if use in display_fields and display_fields[use] is not None:
                raise ComponentRuntimeError(f"{component_id}: prohibited use field {use!r} set")

        normalized = dict(render_candidate)
        normalized.setdefault("slot_id", slot_id)
        normalized["component_id"] = component_id
        normalized["component_version"] = definition.version
        normalized["narrative_mode"] = definition.narrative_mode
        return normalized

    # ---------------------------------------------------------------- assembly
    def build_render_plan_item(
        self,
        *,
        component_id: str,
        render_candidate: dict[str, Any],
        claim_id: str,
        section_instance_id: str,
        slot_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate + normalize one item for a render_plans row."""
        requested = dict(render_candidate)
        if slot_id:
            requested["slot_id"] = slot_id
        candidate = self.validate_render(component_id, requested)
        candidate["claim_id"] = claim_id
        candidate["section_instance_id"] = section_instance_id
        return candidate
