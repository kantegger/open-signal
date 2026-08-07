"""Claim ledger contracts (spec §153–§157).

OS-002 first-batch object: Claim (+ ClaimType, ClaimStatus,
StructuredProposition shared types).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# spec §154
ClaimType = Literal[
    "source_fact",
    "derived_observation",
    "attributed_interpretation",
    "analytical_inference",
    "editorial_judgment",
    "forecast",
    "structural_hypothesis",
]

# spec §153 (single shared state machine; also §171 lifecycle)
ClaimStatus = Literal[
    "draft",
    "verified",
    "published",
    "active",
    "degraded",
    "amended",
    "withdrawn",
    "expired",
    "resolution_due",
    "resolution_observed",
    "resolved",
    "ambiguous",
    "unresolvable",
]

ConfidenceLabel = Literal["low", "medium", "high", "very_high"]


class StructuredProposition(BaseModel):
    """spec §157."""

    model_config = ConfigDict(extra="forbid")

    subjectIds: list[str] = Field(default_factory=list)
    predicate: str

    objectIds: list[str] | None = None

    operator: Literal[
        "equals",
        "greater_than",
        "less_than",
        "increased",
        "decreased",
        "transitioned_to",
        "will_occur",
        "will_persist",
        "is_forming",
        "is_associated_with",
    ] | None = None

    value: float | None = None
    unit: str | None = None

    baseline: dict[str, object] | None = None
    observationWindow: dict[str, str] | None = None

    qualifiers: dict[str, object] = Field(default_factory=dict)

    propositionVersion: str


class Claim(BaseModel):
    """spec §156."""

    model_config = ConfigDict(extra="forbid")

    id: str

    # 所属身份
    institutionId: str
    deskId: str
    agentLineageId: str
    modelVersion: str
    charterVersion: str
    runId: str

    # 内容分类
    sectionId: str
    capabilityId: str
    claimType: ClaimType
    claimFamilyId: str | None = None

    publicStatement: str
    structuredProposition: StructuredProposition

    # 认识论状态
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidenceLabel: ConfidenceLabel | None = None

    epistemicStatus: Literal[
        "observed",
        "derived",
        "attributed",
        "inferred",
        "assessed",
        "forecasted",
        "hypothesized",
    ]

    # 证据与限制
    evidenceBundleId: str
    primaryEvidenceIds: list[str] = Field(default_factory=list)
    counterEvidenceIds: list[str] = Field(default_factory=list)
    alternativeExplanationIds: list[str] = Field(default_factory=list)

    evidenceSnapshotHash: str

    # 时间
    issuedAt: str
    validFrom: str | None = None
    validUntil: str | None = None

    # 结算
    resolutionContractId: str | None = None

    # 生命周期（与 §153 ClaimStatus 共用同一状态机）
    status: ClaimStatus

    currentVersionId: str

    createdAt: str
    updatedAt: str
