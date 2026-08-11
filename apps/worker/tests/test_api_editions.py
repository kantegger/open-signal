"""HTTP contract for the permanent Edition archive."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from apps.api import main as api_main


class _StubArchivePresenter:
    last_params: dict | None = None

    def __init__(self, engine: object) -> None:
        self.engine = engine

    def build(self, **params) -> dict:
        type(self).last_params = params
        if params.get("cursor") == "bad":
            raise ValueError("invalid archive cursor")
        return {
            "items": [],
            "next_cursor": None,
            "has_more": False,
            "page_size": params["limit"],
            "total_count": 0,
            "filters": {
                "year": params.get("year"),
                "section": params.get("section"),
                "status": params.get("status"),
            },
            "facets": {"years": [], "sections": [], "statuses": []},
        }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_main, "_engine", lambda: object())
    monkeypatch.setattr(api_main, "EditionArchivePresenter", _StubArchivePresenter)
    with TestClient(api_main.app) as test_client:
        yield test_client


def test_archive_list_route_forwards_filters_and_sets_cache(client: TestClient) -> None:
    response = client.get(
        "/api/editions?limit=25&year=2026&section=rules-moved&status=sparse"
    )

    assert response.status_code == 200
    assert response.json()["page_size"] == 25
    assert _StubArchivePresenter.last_params == {
        "cursor": None,
        "limit": 25,
        "year": 2026,
        "section": "rules-moved",
        "status": "sparse",
    }
    assert response.headers["Cache-Control"] == (
        "public, max-age=300, stale-while-revalidate=900"
    )


def test_archive_list_rejects_malformed_cursor(client: TestClient) -> None:
    response = client.get("/api/editions?cursor=bad")
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid archive cursor"}


def test_archive_list_validates_page_size_before_presenter(client: TestClient) -> None:
    assert client.get("/api/editions?limit=0").status_code == 422
    assert client.get("/api/editions?limit=101").status_code == 422
