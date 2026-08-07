"""Round-trip sanity check for the 9 first-batch contracts (OS-002)."""

import sys
sys.path.insert(0, "python")

from open_signal.canonical.models import (
    CanonicalExpectation,
    CanonicalRule,
    MarketObservation,
    ResearchWork,
)
from open_signal.claims.models import Claim, StructuredProposition
from open_signal.composer.models import DailyEdition, RenderPlan
from open_signal.sources.models import RawSourceRecord, SourceDefinition

# Minimal valid instances per model.
instances = {
    "SourceDefinition": SourceDefinition(
        id="src-poly-1", name="Polymarket Gamma",
        category="prediction_market", authorityLevel="licensed_aggregator",
        accessMode="rest", adapterId="polymarket-gamma-v1",
        rightsManifestId="rm-poly-1", sourceStatus="active",
        healthCheckInterval="5m",
    ),
    "RawSourceRecord": RawSourceRecord(
        id="raw-1", sourceId="src-poly-1", externalId="mkt-123",
        recordType="market", mimeType="application/json", payload={"a": 1},
        firstSeenAt="2026-08-01T00:00:00Z", lastSeenAt="2026-08-01T00:05:00Z",
        ingestedAt="2026-08-01T00:05:01Z", contentHash="abc123",
        rightsManifestId="rm-poly-1", adapterVersion="0.1.0", status="active",
    ),
    "CanonicalExpectation": CanonicalExpectation(
        id="ce-1", canonicalQuestion="Will X happen?",
        eventType="policy", outcomeType="binary",
        resolutionDeadlineAt="2027-01-01T00:00:00Z",
        resolutionRuleSummary="Official result", resolutionRuleHash="h1",
        sourceMarketIds=["sm-1"], status="active", canonicalizationVersion="0.1.0",
    ),
    "MarketObservation": MarketObservation(
        id="mo-1", sourceMarketId="sm-1", observedAt="2026-08-01T00:00:00Z",
        probability=0.64, midpoint=0.64, priceMethod="midpoint",
        dataQualityFlags=[],
    ),
    "CanonicalRule": CanonicalRule(
        id="cr-1", title="AI Act", jurisdictionId="eu", issuingAuthorityId="ec",
        ruleType="regulation", currentState="adopted", docketIdentifiers=[],
        currentVersionId="rv-1", status="active", ontologyVersion="0.1.0",
    ),
    "ResearchWork": ResearchWork(
        id="rw-1", title="Paper", workType="preprint",
        externalIds=[], authorEntityIds=[], institutionEntityIds=[],
        topicIds=[], openAccessLocations=[], sourceRecordIds=[], status="active",
    ),
    "Claim": Claim(
        id="c-1", institutionId="open-signal", deskId="expectations-desk",
        agentLineageId="lineage-1", modelVersion="m1", charterVersion="v1",
        runId="run-1", sectionId="expectations-moved",
        capabilityId="expectation.probability-change", claimType="derived_observation",
        publicStatement="P moved from 0.64 to 0.85.",
        structuredProposition=StructuredProposition(
            subjectIds=["sm-1"], predicate="probability", operator="increased",
            value=0.21, qualifiers={}, propositionVersion="0.1.0",
        ),
        confidence=0.72, confidenceLabel="high", epistemicStatus="derived",
        evidenceBundleId="eb-1", evidenceSnapshotHash="h2",
        issuedAt="2026-08-04T00:00:00Z", status="published",
        currentVersionId="cv-1", createdAt="2026-08-04T00:00:00Z",
        updatedAt="2026-08-04T00:00:00Z",
    ),
    "RenderPlan": RenderPlan(
        id="rp-1", slotId="lead-region", sectionInstanceId="si-1",
        componentId="time-series.probability-move", componentVersion="1.0.0",
        componentVariant="lead", headline="P moved", displayFields={},
        evidenceBundleId="eb-1", visualPriority=1, mobilePriority=1,
        generatedBy="composer-v1", approvedByVerificationRunId="vr-1",
    ),
}

render_plan = instances["RenderPlan"]
instances["DailyEdition"] = DailyEdition(
    id="ed-1", editionDate="2026-08-04", generatedAt="2026-08-04T01:00:00Z",
    status="published", leadRegion=render_plan,
    liveFeed=render_plan, digest=render_plan,
    archivePreview=render_plan, composerVersion="0.1.0",
    generationCostUsd=0.05,
)

failures = []
for name, inst in instances.items():
    try:
        data = inst.model_dump(mode="json")
        restored = type(inst).model_validate(data)
        assert restored == inst, f"{name}: round-trip mismatch"
        print(f"OK  {name}  (round-trip, {len(type(inst).model_fields)} fields)")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{name}: {exc}")
        print(f"FAIL {name}: {exc}")

print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
