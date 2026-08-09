"""Launch-source discovery handlers with one failure boundary per source."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from open_signal.orchestration.metadata import ensure_runtime_metadata
from open_signal.sources.clinicaltrials import ClinicalTrialsChain
from open_signal.sources.federal_register import FederalRegisterChain
from open_signal.sources.openalex import OpenAlexChain
from open_signal.sources.polymarket import PolymarketAdapter


class SourceDiscoveryService:
    def __init__(
        self,
        engine: Any,
        *,
        offline: bool = False,
        fixture_root: Path | None = None,
    ) -> None:
        self.engine = engine
        self.offline = offline
        self.fixture_root = fixture_root

    def discover(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        source_slug = str(payload.get("source_slug") or "")
        source_ids = ensure_runtime_metadata(self.engine)
        if source_slug not in source_ids:
            raise ValueError(f"unsupported source {source_slug!r}")
        source_id = source_ids[source_slug]
        max_pages = int(payload.get("max_pages") or 3)

        if source_slug == "polymarket-gamma":
            fixture_dir = self._fixtures("polymarket")
            adapter = PolymarketAdapter(
                self.engine,
                source_id=source_id,
                adapter_version="production-1.0.0",
                fixture_dir=fixture_dir,
                offline=self.offline,
            )
            try:
                return {
                    "source_slug": source_slug,
                    **adapter.refresh(max_pages=max_pages),
                }
            finally:
                adapter.close()

        if source_slug == "federal-register":
            chain = FederalRegisterChain(
                self.engine,
                source_id=source_id,
                fixture_dir=self._fixtures("federal_register"),
                offline=self.offline,
            )
            try:
                queries = payload.get("queries") or [None]
                documents = pages = 0
                for query in queries:
                    result = chain.discover(
                        max_pages=max_pages,
                        per_page=10,
                        query=str(query) if query else None,
                    )
                    documents += result["documents"]
                    pages += result["pages"]
                return {
                    "source_slug": source_slug,
                    "documents": documents,
                    "pages": pages,
                }
            finally:
                chain.close()

        if source_slug == "openalex":
            chain = OpenAlexChain(
                self.engine,
                source_id=source_id,
                fixture_dir=self._fixtures("openalex"),
                offline=self.offline,
            )
            try:
                requested = set(payload.get("topic_ids") or ())
                works = pages = topics = 0
                for topic in chain.list_topics():
                    if requested and topic["id"] not in requested:
                        continue
                    result = chain.discover_topic(
                        topic_id=topic["id"],
                        max_pages=max_pages,
                    )
                    works += result["works"]
                    pages += result["pages"]
                    topics += 1
                return {
                    "source_slug": source_slug,
                    "works": works,
                    "pages": pages,
                    "topics": topics,
                }
            finally:
                chain.close()

        chain = ClinicalTrialsChain(
            self.engine,
            source_id=source_id,
            fixture_dir=self._fixtures("clinicaltrials"),
            offline=self.offline,
        )
        try:
            requested = set(payload.get("topic_ids") or ())
            studies = skipped = topics = 0
            for topic in chain.topics.get("topics", []):
                if requested and topic["id"] not in requested:
                    continue
                result = chain.discover_topic(topic_id=topic["id"])
                studies += result["studies"]
                skipped += result.get("skipped", 0)
                topics += 1
            return {
                "source_slug": source_slug,
                "studies": studies,
                "skipped": skipped,
                "topics": topics,
            }
        finally:
            chain.close()

    def _fixtures(self, name: str) -> Path | None:
        return self.fixture_root / name if self.fixture_root else None
