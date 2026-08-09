"""HTTP-level coverage for the operations authentication boundary."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from apps.api import main as api_main


class _StubOpsPresenter:
    def __init__(self, engine: object) -> None:
        self.engine = engine

    def current_edition(self) -> dict[str, str]:
        return {"id": "current"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SIGNAL_OPS_TOKEN", "ops-secret")
    monkeypatch.setattr(api_main, "_engine", lambda: object())
    monkeypatch.setattr(api_main, "OpsPresenter", _StubOpsPresenter)
    with TestClient(api_main.app) as test_client:
        yield test_client


def test_ops_endpoint_requires_bearer_auth(client: TestClient) -> None:
    response = client.get("/api/ops/current-edition")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_ops_endpoint_declares_bearer_security() -> None:
    schema = api_main.app.openapi()
    operation = schema["paths"]["/api/ops/current-edition"]["get"]
    assert operation["security"] == [{"OpsBearer": []}]
    assert schema["components"]["securitySchemes"]["OpsBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }


def test_ops_endpoint_accepts_standard_authorization(client: TestClient) -> None:
    response = client.get(
        "/api/ops/current-edition",
        headers={"Authorization": "Bearer ops-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"id": "current"}


@pytest.mark.parametrize("header_value", ["ops-secret", "Bearer ops-secret"])
def test_ops_endpoint_accepts_legacy_header(
    client: TestClient,
    header_value: str,
) -> None:
    response = client.get(
        "/api/ops/current-edition",
        headers={"X-Ops-Token": header_value},
    )
    assert response.status_code == 200


def test_ops_endpoint_rejects_conflicting_credentials(client: TestClient) -> None:
    response = client.get(
        "/api/ops/current-edition",
        headers={
            "Authorization": "Bearer ops-secret",
            "X-Ops-Token": "different-secret",
        },
    )
    assert response.status_code == 401
