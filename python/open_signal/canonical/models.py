"""Canonical layer contracts (spec §98–§107).

OS-002 first-batch objects: CanonicalExpectation, MarketObservation,
CanonicalRule, ResearchWork (+ RuleState shared enum).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# spec §33.4 Rule State Model
RuleState = Literal[
    "announced",
    "draft",
    "consultation",
    "committee_review",
    "adopted",
    "signed",
    "effective",
    "enforced",
    "delayed",
    "withdrawn",
    "superseded",
]


class CanonicalExpectation(BaseModel):
    """spec §100."""

    model_config = ConfigDict(extra="forbid")

    id: str

    canonicalQuestion: str
    subjectEntityIds: list[str] = Field(default_factory=list)

    eventType: str

    outcomeType: Literal["binary", "categorical", "threshold", "range"]

    threshold: float | None = None
    thresholdUnit: str | None = None

    observationStartAt: str | None = None
    resolutionDeadlineAt: str

    resolutionAuthority: str | None = None
    resolutionRuleSummary: str
    resolutionRuleHash: str

    sourceMarketIds: list[str] = Field(default_factory=list)

    status: Literal["active", "resolved", "void", "ambiguous", "retired"]

    canonicalizationVersion: str


class MarketObservation(BaseModel):
    """spec §102."""

    model_config = ConfigDict(extra="forbid")

    id: str
    sourceMarketId: str

    observedAt: str

    probability: float | None = None

    bestBid: float | None = None
    bestAsk: float | None = None
    midpoint: float | None = None
    lastTradePrice: float | None = None

    spread: float | None = None
    volume: float | None = None
    openInterest: float | None = None

    priceMethod: Literal["midpoint", "last_trade", "source_probability", "unknown"]

    dataQualityFlags: list[str] = Field(default_factory=list)

    rawSourceRecordId: str | None = None


class CanonicalRule(BaseModel):
    """spec §103."""

    model_config = ConfigDict(extra="forbid")

    id: str

    title: str
    jurisdictionId: str
    issuingAuthorityId: str

    ruleType: str

    currentState: RuleState
    previousState: RuleState | None = None

    officialIdentifier: str | None = None
    docketIdentifiers: list[str] = Field(default_factory=list)

    announcedAt: str | None = None
    adoptedAt: str | None = None
    signedAt: str | None = None
    effectiveAt: str | None = None
    enforcementAt: str | None = None
    delayedAt: str | None = None
    withdrawnAt: str | None = None
    supersededAt: str | None = None

    affectedEntityTypeIds: list[str] = Field(default_factory=list)
    topicIds: list[str] = Field(default_factory=list)

    currentVersionId: str

    status: Literal["active", "withdrawn", "superseded", "expired"]

    ontologyVersion: str


class ResearchWork(BaseModel):
    """spec §106."""

    model_config = ConfigDict(extra="forbid")

    id: str

    title: str
    publicationDate: str | None = None

    workType: Literal[
        "article",
        "preprint",
        "review",
        "dataset",
        "book",
        "conference",
        "other",
    ]

    doi: str | None = None
    externalIds: list[dict[str, str]] = Field(default_factory=list)

    authorEntityIds: list[str] = Field(default_factory=list)
    institutionEntityIds: list[str] = Field(default_factory=list)
    topicIds: list[str] = Field(default_factory=list)

    abstractText: str | None = None
    abstractRights: str | None = None

    openAccessLocations: list[str] = Field(default_factory=list)

    sourceRecordIds: list[str] = Field(default_factory=list)

    status: Literal["active", "retracted", "corrected", "merged"]
