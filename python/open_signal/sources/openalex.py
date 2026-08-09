"""OpenAlex source adapter (spec §88.4, OS-020).

Read-only scholarly metadata from OpenAlex (CC0, free API). Implements
baseline queries per frozen research topic, pagination, fixtures for
offline tests, and idempotent raw record storage.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from open_signal.sources.artifact_store import sha256_hex

OPENALEX_BASE_URL = "https://api.openalex.org"
REPO_ROOT = Path(__file__).resolve().parents[3]
TOPICS_PATH = REPO_ROOT / "infra" / "topics" / "research-frontier.yaml"
FIXTURE_DIR = REPO_ROOT / "fixtures" / "openalex"

USER_AGENT = "open-signal-dev/0.1 (mailto:dev@example.com)"


class OpenAlexClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=OPENALEX_BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )

    def search_works(
        self,
        *,
        query: str,
        page: int = 1,
        per_page: int = 25,
        from_date: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"search": query, "page": page, "per-page": per_page}
        if from_date:
            params["filter"] = f"from_publication_date:{from_date}"
        resp = self._client.get("/works", params=params)
        resp.raise_for_status()
        return resp.json()

    def health_check(self) -> bool:
        try:
            return self._client.get("/works", params={"per-page": 1}).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


class OpenAlexChain:
    """Topic-driven discovery into raw_source_records (idempotent)."""

    def __init__(
        self,
        engine: Any,
        *,
        client: OpenAlexClient | None = None,
        source_id: str | None = None,
        fixture_dir: Path | None = None,
        offline: bool = False,
        topics_path: Path | str | None = None,
    ) -> None:
        self.engine = engine
        self.client = client or OpenAlexClient()
        self.source_id = source_id
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
        self.offline = offline
        self.topics = self._load_topics(topics_path)

    @staticmethod
    def _load_topics(path: Path | str | None) -> dict[str, Any]:
        with (Path(path) if path else TOPICS_PATH).open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    def baseline_query(self, topic_id: str) -> str | None:
        for topic in self.topics.get("topics", []):
            if topic["id"] == topic_id:
                return (topic.get("baseline_queries") or {}).get("openalex")
        return None

    def list_topics(self) -> list[dict[str, Any]]:
        return self.topics.get("topics", [])

    # --------------------------------------------------------------- discover
    def discover_topic(
        self,
        *,
        topic_id: str,
        max_pages: int | None = None,
        window_years: int | None = None,
    ) -> dict[str, int]:
        """Run the baseline query for one topic; store works idempotently."""
        from sqlalchemy import text

        query = self.baseline_query(topic_id)
        if not query:
            raise ValueError(f"no baseline query for topic {topic_id!r}")

        max_pages = max_pages or self.topics.get("max_pages_per_topic", 3)
        window_years = window_years or self.topics.get("default_window_years", 3)
        from_date = (
            (datetime.now(timezone.utc) - timedelta(days=365 * window_years))
            .date()
            .isoformat()
        )

        stored = 0
        pages = 0
        for page in range(1, max_pages + 1):
            data = self._load_page(topic_id, page, query, from_date)
            results = data.get("results") or []
            if not results:
                break
            pages += 1
            with self.engine.begin() as conn:
                for work in results:
                    work_id = str(work.get("id") or work.get("doi") or uuid.uuid4())
                    payload = json.dumps(work, ensure_ascii=False, sort_keys=True)
                    content_hash = sha256_hex(payload.encode())
                    result = conn.execute(
                        text(
                            """
                            INSERT INTO raw_source_records
                              (source_id, external_id, record_type, mime_type,
                               payload, source_created_at, content_hash,
                               transport_metadata, adapter_version, status)
                            VALUES
                              (:sid, :ext, 'work', 'application/json',
                               CAST(:payload AS jsonb),
                               CAST(:pub AS timestamptz), :hash,
                               CAST(:metadata AS jsonb), 'openalex-v2', 'active')
                            ON CONFLICT (source_id, external_id, content_hash)
                            DO UPDATE SET
                              transport_metadata = jsonb_set(
                                COALESCE(raw_source_records.transport_metadata, '{}'::jsonb)
                                  || EXCLUDED.transport_metadata,
                                '{monitoring_topics}',
                                COALESCE(
                                  raw_source_records.transport_metadata -> 'monitoring_topics',
                                  '{}'::jsonb
                                ) || COALESCE(
                                  EXCLUDED.transport_metadata -> 'monitoring_topics',
                                  '{}'::jsonb
                                ),
                                true
                              ),
                              last_seen_at = now(),
                              adapter_version = EXCLUDED.adapter_version
                            RETURNING (xmax = 0) AS inserted
                            """
                        ),
                        {
                            "sid": self.source_id,
                            "ext": work_id,
                            "payload": payload,
                            "pub": f"{work.get('publication_date')}T00:00:00Z"
                            if work.get("publication_date")
                            else None,
                            "hash": content_hash,
                            "metadata": json.dumps(
                                {"monitoring_topics": {topic_id: True}},
                                sort_keys=True,
                            ),
                        },
                    )
                    stored += int(bool(result.scalar_one()))
        return {"works": stored, "pages": pages}

    # --------------------------------------------------------------- fixtures
    def _load_page(
        self, topic_id: str, page: int, query: str, from_date: str
    ) -> dict[str, Any]:
        fixture = self.fixture_dir / f"{topic_id}_page_{page}.json"
        if fixture.exists():
            with fixture.open(encoding="utf-8") as f:
                return json.load(f)
        if self.offline:
            return {"results": []}
        return self.client.search_works(
            query=query, page=page, per_page=25, from_date=from_date
        )

    def save_fixture(self, topic_id: str, page: int, data: dict[str, Any]) -> Path:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self.fixture_dir / f"{topic_id}_page_{page}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def close(self) -> None:
        self.client.close()
