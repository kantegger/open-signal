"""Production Job handler registry (OS-049)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from open_signal.composer.edition_writer import EditionWriter
from open_signal.jobs.queue import ClaimedJob
from open_signal.orchestration.expectations import ExpectationsSectionService
from open_signal.orchestration.research import ResearchSectionService
from open_signal.orchestration.rules import RulesSectionService
from open_signal.orchestration.sources import SourceDiscoveryService


class ProductionHandlers:
    def __init__(
        self,
        engine: Any,
        *,
        offline: bool = False,
        fixture_root: Path | None = None,
    ) -> None:
        self.engine = engine
        self.sources = SourceDiscoveryService(
            engine,
            offline=offline,
            fixture_root=fixture_root,
        )
        self.expectations = ExpectationsSectionService(engine)
        self.rules = RulesSectionService(engine)
        self.research = ResearchSectionService(engine)

    def registry(self) -> dict[str, Any]:
        return {
            "source.discover": self.discover_source,
            "canonical.normalize": self.normalize_expectations,
            "derived.calculate_expectation": self.calculate_expectations,
            "derived.detect_rule_transition": self.detect_rule_transitions,
            "derived.generate_research_candidates": self.generate_research_candidates,
            "agent.investigate": self.investigate,
            "composer.generate_edition": self.reconcile_publication,
        }

    def discover_source(self, job: ClaimedJob) -> dict[str, Any]:
        return self.sources.discover(job.payload)

    def normalize_expectations(self, job: ClaimedJob) -> dict[str, Any]:
        _require_section(job, "expectations-moved")
        return self.expectations.ingest_observations(job.payload)

    def calculate_expectations(self, job: ClaimedJob) -> dict[str, Any]:
        _require_section(job, "expectations-moved")
        return self.expectations.run_editorial_batch(job.payload)

    def detect_rule_transitions(self, job: ClaimedJob) -> dict[str, Any]:
        _require_section(job, "rules-moved")
        return self.rules.run_editorial_batch(job.payload)

    def generate_research_candidates(self, job: ClaimedJob) -> dict[str, Any]:
        _require_section(job, "research-frontier")
        return self.research.generate_candidates(job.payload)

    def investigate(self, job: ClaimedJob) -> dict[str, Any]:
        section_id = str(job.payload.get("section_id") or "")
        if section_id != "research-frontier":
            raise ValueError(
                f"no agent.investigate handler for section {section_id!r}"
            )
        return self.research.investigate_shadow(job.payload)

    def reconcile_publication(self, job: ClaimedJob) -> dict[str, Any]:
        reason = str(job.payload.get("reason") or "")
        if reason != "freshness_reconcile":
            raise ValueError(f"unsupported publication reason {reason!r}")
        return EditionWriter(self.engine).reconcile_freshness()


def _require_section(job: ClaimedJob, expected: str) -> None:
    actual = str(job.payload.get("section_id") or "")
    if actual != expected:
        raise ValueError(
            f"{job.job_type} expected section {expected!r}, got {actual!r}"
        )
