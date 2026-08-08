"""Registry YAML loader and operations read view (spec §275.2, OS-005).

Loads the machine-readable registries from ``infra/registries`` and
exposes read-only views plus reference-integrity validation. Production
code reads these registries, never the natural-language spec (appendix A.0).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRIES_DIR = REPO_ROOT / "infra" / "registries"

EvidenceLevel = Literal[
    "observed",
    "verified",
    "derived_verified",
    "authoritative_primary",
    "published",
    "multi_source_with_counterevidence",
]


class SectionDefinition(BaseModel):
    """section-registry.yaml entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    short_title: str
    editorial_question: str
    editorial_mission: str
    user_value: str | None = None

    maturity: Literal["concept", "shadow", "beta", "production", "restricted", "suspended", "retired"]
    runtime: Literal["deterministic", "analytical", "agentic", "hybrid"]

    desk_id: str
    agent_charter_id: str

    capability_ids: list[str] = Field(default_factory=list)
    required_source_types: list[str] = Field(default_factory=list)
    optional_source_types: list[str] = Field(default_factory=list)
    allowed_claim_types: list[str] = Field(default_factory=list)
    allowed_component_ids: list[str] = Field(default_factory=list)
    allowed_slot_types: list[str] = Field(default_factory=list)

    can_be_hero: bool = False
    can_appear_daily: bool = False
    can_run_without_agent: bool = False

    minimum_evidence_level: EvidenceLevel
    minimum_agent_maturity: str | None = None
    refresh_cadence: str
    daily_cost_budget_usd: float

    repetition_policy: dict[str, Any] = Field(default_factory=dict)
    known_failure_modes: list[str] = Field(default_factory=list)
    suspension_conditions: list[str] = Field(default_factory=list)


class CapabilityDefinition(BaseModel):
    """capability-registry.yaml entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    section_id: str
    title: str
    maturity: Literal["disabled", "laboratory", "shadow", "beta", "production"]
    runtime: Literal["deterministic", "analytical", "agentic", "hybrid"]

    required_inputs: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    output_claim_types: list[str] = Field(default_factory=list)
    supported_components: list[str] = Field(default_factory=list)

    validation_mode: Literal[
        "exact_replay",
        "source_reconciliation",
        "statistical_validation",
        "agent_evaluation",
        "retrospective_evaluation",
    ]
    minimum_evidence_items: int = 1
    requires_counter_evidence: bool = False
    requires_resolution_contract: bool = False
    may_enter_hero: bool = False
    maximum_confidence: float
    cost_class: Literal["low", "medium", "high"]


class SlotDefinition(BaseModel):
    """slot-registry.yaml entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["lead", "secondary", "live_feed", "digest", "main", "utility", "archive"]
    size: Literal["lead_large", "lead_split", "medium", "small", "strip", "full_width"]
    required: bool = False
    collapsible: bool = False

    minimum_section_maturity: str
    minimum_capability_maturity: str

    allowed_section_ids: list[str] = Field(default_factory=list)
    allowed_component_family_ids: list[str] = Field(default_factory=list)

    allows_observation: bool = False
    allows_analysis: bool = False
    allows_editorial_judgment: bool = False
    allows_experimental_judgment: bool = False

    minimum_evidence_level: EvidenceLevel
    maximum_items: int

    desktop_order: int
    mobile_order: int


class ComponentDefinition(BaseModel):
    """component-registry.yaml entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    family_id: str
    version: str

    supported_section_ids: list[str] = Field(default_factory=list)
    supported_capability_ids: list[str] = Field(default_factory=list)
    supported_claim_types: list[str] = Field(default_factory=list)
    supported_slot_types: list[str] = Field(default_factory=list)

    narrative_mode: Literal["observation", "analysis", "judgment", "mixed"]

    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)

    fallback_component_id: str | None = None
    fallback_conditions: list[str] = Field(default_factory=list)
    prohibited_uses: list[str] = Field(default_factory=list)


class ResolutionTemplateDefinition(BaseModel):
    """resolution-template-registry.yaml entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    claim_type: str
    section_ids: list[str] = Field(default_factory=list)
    description: str
    required_proposition_fields: list[str] = Field(default_factory=list)
    default_evaluation_window: str | None = None
    scoring_rule_id: str
    partial_credit_allowed: bool = False
    maturity: str
    activated_at: str | None = None


class FreshnessPolicyDefinition(BaseModel):
    """freshness-policy-registry.yaml entry.

    Policies are deliberately expressed in elapsed hours rather than calendar
    days: the front page is rolling and has no global midnight reset.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    section_ids: list[str] = Field(default_factory=list)
    slot_types: list[str] = Field(default_factory=list)
    soft_age_hours: float | None = None
    hard_age_hours: float | None = None
    lead_tenure_hours: float | None = None
    semantic_invalidators: list[str] = Field(default_factory=list)
    priority: int = 100


class Registry:
    """Loaded registries with read views and reference-integrity validation."""

    def __init__(
        self,
        sections: list[SectionDefinition],
        capabilities: list[CapabilityDefinition],
        slots: list[SlotDefinition],
        components: list[ComponentDefinition],
        templates: list[ResolutionTemplateDefinition],
        freshness_policies: list[FreshnessPolicyDefinition],
        freshness_policy_version: str,
    ) -> None:
        self._sections = {s.id: s for s in sections}
        self._capabilities = {c.id: c for c in capabilities}
        self._slots = {s.id: s for s in slots}
        self._components = {c.id: c for c in components}
        self._templates = {t.id: t for t in templates}
        self._freshness_policies = {p.id: p for p in freshness_policies}
        self.freshness_policy_version = freshness_policy_version

    # ------------------------------------------------------------- loading
    @classmethod
    def load(cls, registries_dir: Path | str | None = None) -> Registry:
        base = Path(registries_dir) if registries_dir else DEFAULT_REGISTRIES_DIR
        freshness_version, freshness_policies = _parse_versioned_file(
            base / "freshness-policy-registry.yaml",
            "policies",
            FreshnessPolicyDefinition,
        )
        return cls(
            sections=_parse_file(base / "section-registry.yaml", "sections", SectionDefinition),
            capabilities=_parse_file(base / "capability-registry.yaml", "capabilities", CapabilityDefinition),
            slots=_parse_file(base / "slot-registry.yaml", "slots", SlotDefinition),
            components=_parse_file(base / "component-registry.yaml", "components", ComponentDefinition),
            templates=_parse_file(base / "resolution-template-registry.yaml", "templates", ResolutionTemplateDefinition),
            freshness_policies=freshness_policies,
            freshness_policy_version=freshness_version,
        )

    # ------------------------------------------------------------ read views
    def sections(self) -> list[SectionDefinition]:
        return list(self._sections.values())

    def section(self, section_id: str) -> SectionDefinition | None:
        return self._sections.get(section_id)

    def capabilities(self) -> list[CapabilityDefinition]:
        return list(self._capabilities.values())

    def capability(self, capability_id: str) -> CapabilityDefinition | None:
        return self._capabilities.get(capability_id)

    def slots(self) -> list[SlotDefinition]:
        return list(self._slots.values())

    def slot(self, slot_id: str) -> SlotDefinition | None:
        return self._slots.get(slot_id)

    def components(self) -> list[ComponentDefinition]:
        return list(self._components.values())

    def component(self, component_id: str) -> ComponentDefinition | None:
        return self._components.get(component_id)

    def templates(self) -> list[ResolutionTemplateDefinition]:
        return list(self._templates.values())

    def freshness_policies(self) -> list[FreshnessPolicyDefinition]:
        return sorted(self._freshness_policies.values(), key=lambda p: p.priority)

    def freshness_policy(self, policy_id: str) -> FreshnessPolicyDefinition | None:
        return self._freshness_policies.get(policy_id)

    def capabilities_for_section(self, section_id: str) -> list[CapabilityDefinition]:
        return [c for c in self._capabilities.values() if c.section_id == section_id]

    def components_for_section(self, section_id: str) -> list[ComponentDefinition]:
        section = self.section(section_id)
        if section is None:
            return []
        return [self._components[i] for i in section.allowed_component_ids if i in self._components]

    # ----------------------------------------------------------- validation
    def validate(self) -> list[str]:
        """Return reference-integrity errors (empty means valid)."""
        errors: list[str] = []

        for section in self._sections.values():
            for cap_id in section.capability_ids:
                if cap_id not in self._capabilities:
                    errors.append(f"section {section.id}: unknown capability {cap_id}")
            for comp_id in section.allowed_component_ids:
                if comp_id not in self._components:
                    errors.append(f"section {section.id}: unknown component {comp_id}")
            for slot_type in section.allowed_slot_types:
                if slot_type not in {s.type for s in self._slots.values()}:
                    errors.append(f"section {section.id}: unknown slot type {slot_type}")

        for cap in self._capabilities.values():
            if cap.section_id not in self._sections:
                errors.append(f"capability {cap.id}: unknown section {cap.section_id}")
            for comp_id in cap.supported_components:
                if comp_id not in self._components:
                    errors.append(f"capability {cap.id}: unknown component {comp_id}")

        for comp in self._components.values():
            for cap_id in comp.supported_capability_ids:
                if cap_id not in self._capabilities:
                    errors.append(f"component {comp.id}: unknown capability {cap_id}")
            if comp.fallback_component_id and comp.fallback_component_id not in self._components:
                errors.append(f"component {comp.id}: unknown fallback {comp.fallback_component_id}")

        if "default" not in self._freshness_policies:
            errors.append("freshness policies: missing default policy")
        for policy in self._freshness_policies.values():
            for section_id in policy.section_ids:
                if section_id != "*" and section_id not in self._sections:
                    errors.append(f"freshness policy {policy.id}: unknown section {section_id}")
            for slot_type in policy.slot_types:
                if slot_type != "*" and slot_type not in {s.type for s in self._slots.values()}:
                    errors.append(f"freshness policy {policy.id}: unknown slot type {slot_type}")
            if (
                policy.soft_age_hours is not None
                and policy.hard_age_hours is not None
                and policy.soft_age_hours > policy.hard_age_hours
            ):
                errors.append(f"freshness policy {policy.id}: soft age exceeds hard age")

        return errors

    # ------------------------------------------------------------- desk sync
    def sync_desks(self, engine: Any) -> None:
        """Upsert agent_desks from section definitions (appendix C.8)."""
        from sqlalchemy import text

        with engine.begin() as conn:
            for section in self._sections.values():
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_desks (id, title, editorial_mission, charter_version, maturity)
                        VALUES (:id, :title, :mission, :charter, :maturity)
                        ON CONFLICT (id) DO UPDATE SET
                          title = EXCLUDED.title,
                          editorial_mission = EXCLUDED.editorial_mission,
                          charter_version = EXCLUDED.charter_version,
                          maturity = EXCLUDED.maturity
                        """
                    ),
                    {
                        "id": section.desk_id,
                        "title": section.title,
                        "mission": section.editorial_mission,
                        "charter": section.agent_charter_id,
                        "maturity": section.maturity,
                    },
                )


def _parse_file(path: Path, key: str, model: type) -> list:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [model.model_validate(item) for item in data[key]]


def _parse_versioned_file(path: Path, key: str, model: type) -> tuple[str, list]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return str(data["version"]), [model.model_validate(item) for item in data[key]]
