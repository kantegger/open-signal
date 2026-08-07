"""Publication layer contracts (spec §63–§64, appendix D.5).

OS-002 first-batch objects: RenderPlan, DailyEdition.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RenderPlan(BaseModel):
    """spec §64 / D.5."""

    model_config = ConfigDict(extra="forbid")

    id: str

    slotId: str
    sectionInstanceId: str
    claimIds: list[str] = Field(default_factory=list)

    componentId: str
    componentVersion: str
    componentVariant: Literal["compact", "standard", "lead", "mobile"]

    headline: str
    dek: str | None = None

    displayFields: dict[str, object] = Field(default_factory=dict)
    hiddenDetailFields: dict[str, object] = Field(default_factory=dict)

    evidenceBundleId: str

    visualPriority: int
    mobilePriority: int

    generatedBy: str
    approvedByVerificationRunId: str


class DailyEdition(BaseModel):
    """spec §63."""

    model_config = ConfigDict(extra="forbid")

    id: str
    editionDate: str
    generatedAt: str

    status: Literal["draft", "shadow", "published", "corrected", "archived"]

    leadRegion: RenderPlan
    secondarySignals: list[RenderPlan] = Field(default_factory=list)

    liveFeed: RenderPlan
    digest: RenderPlan

    mainContent: list[RenderPlan] = Field(default_factory=list)
    utilityContent: list[RenderPlan] = Field(default_factory=list)

    archivePreview: RenderPlan

    includedSectionIds: list[str] = Field(default_factory=list)
    includedClaimIds: list[str] = Field(default_factory=list)

    composerVersion: str
    componentVersions: dict[str, str] = Field(default_factory=dict)

    generationCostUsd: float
    correctionCount: int = 0
