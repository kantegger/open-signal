"""Federal Register official source chain (spec §33.10, §88.5, OS-012).

Implements discovery metadata, authoritative artifact download, version
hash and dates for US Federal Register rules:

- discover: page documents (type=RULE) -> raw_source_records (idempotent
  by document_number)
- fetch_artifact: download the authoritative HTML of a document into the
  content-addressed artifact store (public bucket) and link it to the raw
  record
- version hash: SHA-256 content hash computed by the artifact store
- dates: publication_date tracked on the raw record

Fixtures under ``fixtures/federal_register/`` enable offline tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from open_signal.sources.artifact_store import sha256_hex

FR_BASE_URL = "https://www.federalregister.gov"
FR_API_URL = "https://www.federalregister.gov/api/v1"

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "federal_register"

USER_AGENT = "open-signal-dev/0.1 (research; contact: dev@example.com)"


class FederalRegisterClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=FR_API_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def search_documents(
        self, *, page: int = 1, per_page: int = 10, doc_type: str = "RULE", query: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "per_page": per_page,
            "page": page,
            "conditions[type][]": doc_type,
        }
        if query:
            params["conditions[term]"] = query
        resp = self._client.get("/documents.json", params=params)
        resp.raise_for_status()
        return resp.json()

    def fetch_document_html(self, html_url: str) -> bytes:
        resp = httpx.get(
            html_url,
            timeout=30,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._client.close()


class FederalRegisterChain:
    """Discover + artifact pipeline for Federal Register rules."""

    def __init__(
        self,
        engine: Any,
        *,
        client: FederalRegisterClient | None = None,
        source_id: str | None = None,
        artifact_repo: Any = None,
        fixture_dir: Path | None = None,
        offline: bool = False,
    ) -> None:
        self.engine = engine
        self.client = client or FederalRegisterClient()
        self.source_id = source_id
        self.artifact_repo = artifact_repo
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
        self.offline = offline

    # ----------------------------------------------------------------- discovery
    def discover(self, *, max_pages: int = 5, per_page: int = 10) -> dict[str, int]:
        """Store document metadata rows idempotently. Returns counts."""
        from sqlalchemy import text

        stored = 0
        pages = 0
        for page in range(1, max_pages + 1):
            data = self._load_page(page, per_page)
            results = data.get("results") or []
            if not results:
                break
            pages += 1
            with self.engine.begin() as conn:
                for doc in results:
                    doc_number = str(doc.get("document_number"))
                    if not doc_number:
                        continue
                    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True)
                    content_hash = sha256_hex(payload.encode())
                    pub_date = doc.get("publication_date")
                    result = conn.execute(
                        text(
                            """
                            INSERT INTO raw_source_records
                              (source_id, external_id, record_type, mime_type,
                               payload, source_created_at, source_updated_at,
                               content_hash, adapter_version, status)
                            VALUES
                              (:sid, :ext, 'document', 'application/json',
                               CAST(:payload AS jsonb),
                               CAST(:pub AS timestamptz), NULL, :hash,
                               'federal-register-v1', 'active')
                            ON CONFLICT (source_id, external_id, content_hash) DO NOTHING
                            """
                        ),
                        {
                            "sid": self.source_id,
                            "ext": doc_number,
                            "payload": payload,
                            "pub": f"{pub_date}T00:00:00Z" if pub_date else None,
                            "hash": content_hash,
                        },
                    )
                    stored += result.rowcount
        return {"documents": stored, "pages": pages}

    # ----------------------------------------------------------------- artifact
    def fetch_artifact(
        self,
        *,
        raw_source_record_id: str,
        html_url: str,
        source_id: str,
        rights_manifest_id: str | None = None,
    ) -> dict[str, Any]:
        """Download the authoritative HTML, store content-addressed, link."""
        html = self._load_document_html(html_url)
        record = self.artifact_repo.store_artifact(
            source_id=source_id,
            artifact_type="html",
            data=html,
            source_url=html_url,
            raw_source_record_id=raw_source_record_id,
            rights_manifest_id=rights_manifest_id,
            retention_policy_id="federal-register",
            public=True,
        )
        return {
            "artifact_id": record.id,
            "content_hash": record.content_hash,
            "byte_size": record.byte_size,
            "storage_key": record.storage_key,
        }

    # ------------------------------------------------------------------- dates
    def latest_publication_date(self, source_id: str | None = None) -> str | None:
        from sqlalchemy import text

        sid = source_id or self.source_id
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT max(source_created_at) FROM raw_source_records "
                    "WHERE source_id = :sid AND source_created_at IS NOT NULL"
                ),
                {"sid": sid},
            ).fetchone()
        return row[0].isoformat() if row and row[0] else None

    # ----------------------------------------------------------------- fixtures
    def _load_page(self, page: int, per_page: int) -> dict[str, Any]:
        fixture = self.fixture_dir / f"documents_page_{page}.json"
        if fixture.exists():
            with fixture.open(encoding="utf-8") as f:
                return json.load(f)
        if self.offline:
            return {"results": []}
        return self.client.search_documents(page=page, per_page=per_page)

    def _load_document_html(self, html_url: str) -> bytes:
        fixture = self.fixture_dir / "document_sample.html"
        if fixture.exists():
            return fixture.read_bytes()
        if self.offline:
            return b""
        return self.client.fetch_document_html(html_url)

    def save_fixture(self, page: int, data: dict[str, Any]) -> Path:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self.fixture_dir / f"documents_page_{page}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def close(self) -> None:
        self.client.close()
