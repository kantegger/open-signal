"""Source layer contracts (spec §85–§95).

OS-002 first-batch objects: SourceDefinition, RawSourceRecord (+RightsManifest).
Field names follow the spec camelCase; types follow the spec TS interfaces.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# spec §85: allowedOperations keys
_ALLOWED_OPS = (
    "internalAnalysis",
    "rawCaching",
    "metadataDisplay",
    "headlineDisplay",
    "excerptDisplay",
    "fullTextStorage",
    "historicalDisplay",
    "derivedMetrics",
    "commercialUse",
    "publicApiRedistribution",
)


class RightsManifest(BaseModel):
    """spec §85."""

    model_config = ConfigDict(extra="forbid")

    id: str
    sourceId: str

    accessBasis: Literal[
        "public_api",
        "open_license",
        "written_permission",
        "commercial_license",
        "government_open_data",
        "unknown",
    ]

    licenseName: str | None = None
    licenseUrl: str | None = None

    allowedOperations: dict[Literal[_ALLOWED_OPS[0], *_ALLOWED_OPS[1:]], bool | None]

    attributionRequired: bool
    attributionFormat: str | None = None

    maximumRetentionDays: int | None = None
    excerptCharacterLimit: int | None = None

    territorialRestrictions: list[str] = Field(default_factory=list)
    additionalConditions: list[str] = Field(default_factory=list)

    reviewedAt: str
    reviewedBy: str
    sourceDocumentHash: str | None = None


class SourceDefinition(BaseModel):
    """spec §84."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str

    category: Literal[
        "prediction_market",
        "official_legal",
        "official_government",
        "scholarly_metadata",
        "open_access_literature",
        "clinical_registry",
        "patent_data",
        "news_metadata",
        "other",
    ]

    authorityLevel: Literal[
        "primary_official",
        "official_repository",
        "licensed_aggregator",
        "open_aggregator",
        "secondary_source",
    ]

    accessMode: Literal[
        "rest",
        "graphql",
        "websocket",
        "rss",
        "atom",
        "sparql",
        "bulk_snapshot",
        "file_download",
        "web_fetch",
    ]

    baseUrl: str | None = None
    documentationUrl: str | None = None

    adapterId: str
    rightsManifestId: str

    updateCadence: str | None = None
    expectedLatency: str | None = None

    sourceStatus: Literal[
        "candidate",
        "shadow",
        "active",
        "degraded",
        "suspended",
        "retired",
    ]

    healthCheckInterval: str
    lastSuccessfulFetchAt: str | None = None


class RawSourceRecord(BaseModel):
    """spec §94."""

    model_config = ConfigDict(extra="forbid")

    id: str
    sourceId: str

    externalId: str
    externalParentId: str | None = None

    recordType: str
    mimeType: str

    payload: Any

    sourceCreatedAt: str | None = None
    sourceUpdatedAt: str | None = None

    firstSeenAt: str
    lastSeenAt: str
    ingestedAt: str

    contentHash: str
    transportMetadata: dict[str, Any] = Field(
        default_factory=dict,
        description="statusCode/etag/lastModified/requestId (spec §94)",
    )

    rightsManifestId: str
    adapterVersion: str

    status: Literal["active", "changed", "deleted", "retracted", "unavailable"]
