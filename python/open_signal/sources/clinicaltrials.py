"""ClinicalTrials.gov source adapter (spec §88.4, OS-020 supplement).

Read-only clinical trial registry (NIH, public API v2). Covers topic-driven
baseline queries, fixtures for offline tests, and idempotent raw record
storage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from open_signal.sources.artifact_store import sha256_hex

CT_BASE_URL = "https://clinicaltrials.gov/api/v2"
REPO_ROOT = Path(__file__).resolve().parents[3]
TOPICS_PATH = REPO_ROOT / "infra" / "topics" / "research-frontier.yaml"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "clinicaltrials"


class ClinicalTrialsClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=CT_BASE_URL, timeout=timeout)

    def search_studies(self, *, term: str, page_size: int = 25) -> dict[str, Any]:
        resp = self._client.get(
            "/studies",
            params={"query.term": term, "pageSize": page_size},
        )
        resp.raise_for_status()
        return resp.json()

    def health_check(self) -> bool:
        try:
            return self._client.get("/studies", params={"pageSize": 1}).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


class ClinicalTrialsChain:
    def __init__(
        self,
        engine: Any,
        *,
        client: ClinicalTrialsClient | None = None,
        source_id: str | None = None,
        fixture_dir: Path | None = None,
        offline: bool = False,
        topics_path: Path | str | None = None,
    ) -> None:
        self.engine = engine
        self.client = client or ClinicalTrialsClient()
        self.source_id = source_id
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
        self.offline = offline
        with (Path(topics_path) if topics_path else TOPICS_PATH).open(encoding="utf-8") as f:
            self.topics = yaml.safe_load(f)

    def baseline_query(self, topic_id: str) -> str | None:
        for topic in self.topics.get("topics", []):
            if topic["id"] == topic_id:
                return (topic.get("baseline_queries") or {}).get("clinicaltrials")
        return None

    def discover_topic(self, *, topic_id: str) -> dict[str, int]:
        from sqlalchemy import text

        query = self.baseline_query(topic_id)
        if not query:
            return {"studies": 0, "skipped": 1}  # no clinical registry for this topic

        data = self._load(query)
        studies = data.get("studies") or []
        stored = 0
        with self.engine.begin() as conn:
            for study in studies:
                ps = study.get("protocolSection") or {}
                ident = ps.get("identificationModule") or {}
                nct_id = ident.get("nctId")
                if not nct_id:
                    continue
                payload = json.dumps(study, ensure_ascii=False, sort_keys=True)
                result = conn.execute(
                    text(
                        """
                        INSERT INTO raw_source_records
                          (source_id, external_id, record_type, mime_type,
                           payload, source_created_at, content_hash,
                           adapter_version, status)
                        VALUES
                          (:sid, :ext, 'study', 'application/json',
                           CAST(:payload AS jsonb), CAST(:pub AS timestamptz),
                           :hash, 'clinicaltrials-v1', 'active')
                        ON CONFLICT (source_id, external_id, content_hash) DO NOTHING
                        """
                    ),
                    {
                        "sid": self.source_id,
                        "ext": nct_id,
                        "payload": payload,
                        "pub": _normalized_source_date(
                            (ps.get("statusModule") or {})
                            .get("startDateStruct", {})
                            .get("date")
                        ),
                        "hash": sha256_hex(payload.encode()),
                    },
                )
                stored += result.rowcount
        return {"studies": stored, "skipped": 0}

    def _load(self, query: str) -> dict[str, Any]:
        fixture = self.fixture_dir / f"{_slug(query)}.json"
        if fixture.exists():
            with fixture.open(encoding="utf-8") as f:
                return json.load(f)
        if self.offline:
            return {"studies": []}
        return self.client.search_studies(term=query)

    def save_fixture(self, query: str, data: dict[str, Any]) -> Path:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self.fixture_dir / f"{_slug(query)}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def close(self) -> None:
        self.client.close()


def _slug(query: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in query.lower())[:60]


def _normalized_source_date(value: Any) -> str | None:
    """Normalize ClinicalTrials partial ISO dates for PostgreSQL."""
    if not value:
        return None
    raw = str(value).strip()
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-01-01"
    if len(raw) == 7 and raw[4] == "-":
        return f"{raw}-01"
    return raw
