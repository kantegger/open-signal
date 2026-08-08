"""Immutable R2 snapshot delivery tests (database-free)."""

from __future__ import annotations

import json

import httpx
import pytest
from open_signal.publication.delivery import PublicationDelivery
from open_signal.sources.artifact_store import ArtifactStore


class MemoryStore(ArtifactStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_order: list[str] = []

    def put(self, key, data, *, content_type=None):
        assert content_type is not None
        self.objects[key] = data
        self.put_order.append(key)

    def get(self, key):
        return self.objects[key]

    def exists(self, key):
        return key in self.objects

    def delete(self, key):
        self.objects.pop(key, None)

    def sign_url(self, key, expires_in=3600):
        del expires_in
        return f"memory://{key}"


class FrontPage:
    def __init__(self, edition_id="edition-1") -> None:
        self.edition_id = edition_id

    def build(self, *, locale):
        return {
            "snapshot": {
                "id": self.edition_id,
                "published_at": "2026-08-08T10:00:00+00:00",
            },
            "slots": [
                {
                    "items": [
                        {"claim_ids": ["claim-1", "claim-2"]},
                        {"claim_ids": ["claim-1"]},
                    ]
                }
            ],
            "locale": {"requested": locale, "published": "en"},
        }


class ClaimPage:
    def __init__(self, missing=None, version="v1") -> None:
        self.missing = missing
        self.version = version

    def build(self, claim_id, *, locale):
        if claim_id == self.missing:
            return None
        return {
            "claim": {"id": claim_id},
            "locale": locale,
            "version": self.version,
        }


class Response:
    def __init__(self, error=False) -> None:
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise httpx.HTTPStatusError(
                "failed",
                request=httpx.Request("POST", "https://example.test"),
                response=httpx.Response(503),
            )


class Client:
    def __init__(self, *, error=False) -> None:
        self.error = error
        self.calls: list[dict] = []

    def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return Response(self.error)


def delivery(store, client, *, claim_page=None, front_page=None):
    return PublicationDelivery(
        object(),
        store,
        revalidate_url="https://open-signal.test/api/revalidate",
        revalidate_token="secret",
        client=client,
        front_page=front_page or FrontPage(),
        claim_page=claim_page or ClaimPage(),
    )


def test_delivery_writes_current_pointer_last_then_notifies() -> None:
    store = MemoryStore()
    client = Client()

    result = delivery(store, client).deliver()

    assert result["status"] == "delivered"
    pointer_key = "public/publications/channels/front-page/en.json"
    receipt_key = "public/publications/deliveries/edition-1/vercel.en.json"
    assert store.put_order[-2:] == [pointer_key, receipt_key]
    pointer = json.loads(store.get(pointer_key))
    assert pointer["edition_id"] == "edition-1"
    assert client.calls[0]["json"]["claim_ids"] == ["claim-1", "claim-2"]
    assert client.calls[0]["headers"] == {"Authorization": "Bearer secret"}


def test_delivery_is_unchanged_after_receipt_exists() -> None:
    store = MemoryStore()
    client = Client()
    service = delivery(store, client)

    service.deliver()
    result = service.deliver()

    assert result["status"] == "unchanged"
    assert len(client.calls) == 1


def test_failed_notification_is_retried_without_changing_snapshot() -> None:
    store = MemoryStore()
    failing = Client(error=True)
    with pytest.raises(httpx.HTTPStatusError):
        delivery(store, failing).deliver()

    pointer_key = "public/publications/channels/front-page/en.json"
    pointer_before = store.get(pointer_key)
    healthy = Client()
    result = delivery(store, healthy).deliver()

    assert result["status"] == "delivered"
    assert store.get(pointer_key) == pointer_before
    assert len(healthy.calls) == 1


def test_missing_claim_never_advances_current_pointer() -> None:
    store = MemoryStore()

    with pytest.raises(RuntimeError, match="missing claim claim-2"):
        delivery(store, Client(), claim_page=ClaimPage("claim-2")).deliver()

    assert "public/publications/channels/front-page/en.json" not in store.objects


def test_claim_projection_updates_without_rewriting_edition_snapshot() -> None:
    store = MemoryStore()

    delivery(store, Client(), claim_page=ClaimPage(version="v1")).deliver()
    edition_one_key = (
        "public/publications/editions/edition-1/claims/claim-1.en.json"
    )
    edition_one = store.get(edition_one_key)

    delivery(
        store,
        Client(),
        claim_page=ClaimPage(version="v2"),
        front_page=FrontPage("edition-2"),
    ).deliver()

    current_key = "public/publications/claims/claim-1/en.json"
    edition_two_key = (
        "public/publications/editions/edition-2/claims/claim-1.en.json"
    )
    assert json.loads(store.get(current_key))["version"] == "v2"
    assert json.loads(store.get(edition_two_key))["version"] == "v2"
    assert store.get(edition_one_key) == edition_one
