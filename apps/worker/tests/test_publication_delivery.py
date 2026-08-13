"""Immutable R2 snapshot delivery tests (database-free)."""

from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pytest
from open_signal.publication.delivery import PublicationDelivery
from open_signal.publication.localization import (
    LOCALIZATION_VERSION,
    LocalizationBatch,
)
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


class Localizer:
    def __init__(self) -> None:
        self.calls = 0
        self.translation_memories: list[dict[str, str]] = []

    def localize_many(self, payloads, *, locale, translation_memory=None):
        self.calls += 1
        memory = dict(translation_memory or {})
        self.translation_memories.append(memory)
        localized = deepcopy(payloads)
        localized[0]["localized"] = locale
        for payload in localized[1:]:
            payload["localized"] = locale
        source = "Repeated public headline"
        translation = "重複的公開標題"
        cache_hit = int(memory.get(source) == translation)
        return LocalizationBatch(
            payloads=localized,
            provenance="test/localizer:v1",
            prompt_tokens=10,
            completion_tokens=5,
            estimated_cost_usd=0.001,
            translated_string_count=3,
            cache_hit_count=cache_hit,
            cache_miss_count=1 - cache_hit,
            new_translations={} if cache_hit else {source: translation},
        )


class Explore:
    def __init__(self, *, fail=False, version="v1") -> None:
        self.fail = fail
        self.version = version
        self.calls = 0

    def build(self, **kwargs):
        del kwargs
        self.calls += 1
        if self.fail:
            raise RuntimeError("explore presenter failed")
        return {"surface": "explore", "version": self.version}


class EditionArchive:
    def __init__(self, version="v1") -> None:
        self.version = version
        self.calls = 0

    def build(self, **kwargs):
        del kwargs
        self.calls += 1
        return {"surface": "editions", "version": self.version}


class SeoIndex:
    def __init__(self, version="v1") -> None:
        self.version = version
        self.calls = 0

    def build(self, **kwargs):
        del kwargs
        self.calls += 1
        return {"claims": [], "topics": [], "editions": [], "version": self.version}


class TopicPage:
    def __init__(self, missing=None) -> None:
        self.missing = missing
        self.built: list[str] = []

    def build(self, topic_id):
        self.built.append(topic_id)
        if topic_id == self.missing:
            return None
        return {"topic": {"id": topic_id}, "title": f"Topic {topic_id}"}


class FrontPageWithTopics(FrontPage):
    def build(self, *, locale):
        page = super().build(locale=locale)
        page["slots"][0]["items"][0]["topic"] = {"id": "topic-1", "title": "Lead"}
        page["slots"][0]["items"][1]["topic"] = {"id": "topic-1", "title": "Lead"}
        page["slots"].append(
            {"items": [{"claim_ids": [], "topic": {"id": "topic-2", "title": "Watch"}}]}
        )
        return page


def delivery(
    store,
    client,
    *,
    claim_page=None,
    front_page=None,
    localizer=None,
    explore=None,
    edition_archive=None,
    seo_index=None,
    topic_page=None,
):
    return PublicationDelivery(
        object(),
        store,
        revalidate_url="https://open-signal.test/api/revalidate",
        revalidate_token="secret",
        client=client,
        front_page=front_page or FrontPage(),
        claim_page=claim_page or ClaimPage(),
        localizer=localizer,
        explore=explore,
        edition_archive=edition_archive,
        seo_index=seo_index,
        topic_page=topic_page,
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


def test_traditional_chinese_delivery_seals_localization_before_pointer() -> None:
    store = MemoryStore()
    client = Client()
    localizer = Localizer()

    result = delivery(store, client, localizer=localizer).deliver(locale="zh-Hant")

    assert result["status"] == "delivered"
    assert localizer.calls == 1
    localization_key = (
        "public/publications/editions/edition-1/localization."
        f"zh-Hant.{LOCALIZATION_VERSION}.json"
    )
    memory_key = (
        "public/publications/localization-memory/zh-Hant/"
        f"{LOCALIZATION_VERSION}.json"
    )
    pointer_key = "public/publications/channels/front-page/zh-Hant.json"
    manifest_key = (
        "public/publications/editions/edition-1/manifest."
        f"zh-Hant.{LOCALIZATION_VERSION}.json"
    )
    assert store.put_order.index(localization_key) < store.put_order.index(pointer_key)
    assert store.put_order.index(memory_key) < store.put_order.index(pointer_key)
    assert json.loads(store.get(pointer_key))["locale"] == "zh-Hant"
    assert (
        json.loads(store.get(pointer_key))["localization_version"]
        == LOCALIZATION_VERSION
    )
    manifest = json.loads(store.get(manifest_key))
    assert manifest["localization"]["key"] == localization_key
    assert manifest["localization"]["provenance"] == "test/localizer:v1"
    page = json.loads(
        store.get(
            "public/publications/editions/edition-1/front-page."
            f"zh-Hant.{LOCALIZATION_VERSION}.json"
        )
    )
    assert page["localized"] == "zh-Hant"
    assert client.calls[0]["json"]["locale"] == "zh-Hant"


def test_localized_notification_retry_reuses_sealed_translation() -> None:
    store = MemoryStore()
    localizer = Localizer()

    with pytest.raises(httpx.HTTPStatusError):
        delivery(store, Client(error=True), localizer=localizer).deliver(
            locale="zh-Hant"
        )

    result = delivery(store, Client(), localizer=localizer).deliver(
        locale="zh-Hant"
    )

    assert result["status"] == "delivered"
    assert localizer.calls == 1


def test_localized_delivery_reuses_translation_memory_across_editions() -> None:
    store = MemoryStore()
    localizer = Localizer()

    delivery(store, Client(), localizer=localizer).deliver(locale="zh-Hant")
    delivery(
        store,
        Client(),
        localizer=localizer,
        front_page=FrontPage("edition-2"),
    ).deliver(locale="zh-Hant")

    assert localizer.calls == 2
    assert localizer.translation_memories[0] == {}
    assert localizer.translation_memories[1] == {
        "Repeated public headline": "重複的公開標題"
    }
    second_bundle = json.loads(
        store.get(
            "public/publications/editions/edition-2/localization."
            f"zh-Hant.{LOCALIZATION_VERSION}.json"
        )
    )
    assert second_bundle["usage"]["cache_hit_count"] == 1
    assert second_bundle["usage"]["cache_miss_count"] == 0


def test_localization_policy_version_republishes_same_edition() -> None:
    store = MemoryStore()
    pointer_key = "public/publications/channels/front-page/zh-Hant.json"
    old_receipt = "public/publications/deliveries/edition-1/vercel.zh-Hant.json"
    store.put(
        pointer_key,
        json.dumps(
            {
                "edition_id": "edition-1",
                "locale": "zh-Hant",
                "localization_version": "os-l10n-001",
            }
        ).encode(),
        content_type="application/json",
    )
    store.put(old_receipt, b"{}", content_type="application/json")
    localizer = Localizer()

    result = delivery(store, Client(), localizer=localizer).deliver(
        locale="zh-Hant"
    )

    assert result["status"] == "delivered"
    assert localizer.calls == 1
    assert (
        json.loads(store.get(pointer_key))["localization_version"]
        == LOCALIZATION_VERSION
    )


def test_non_english_delivery_requires_localizer() -> None:
    with pytest.raises(RuntimeError, match="localizer is not configured"):
        delivery(MemoryStore(), Client()).deliver(locale="zh-Hant")


def test_delivery_rejects_unknown_locale() -> None:
    with pytest.raises(ValueError, match="unsupported publication locale"):
        delivery(MemoryStore(), Client()).deliver(locale="ja")


def test_delivery_writes_channel_snapshots_before_pointer() -> None:
    store = MemoryStore()
    client = Client()
    explore = Explore()
    editions = EditionArchive()
    seo = SeoIndex()

    result = delivery(
        store,
        client,
        explore=explore,
        edition_archive=editions,
        seo_index=seo,
    ).deliver()

    assert result["status"] == "delivered"
    explore_key = "public/publications/channels/explore/en.json"
    editions_key = "public/publications/channels/editions/en.json"
    seo_key = "public/publications/channels/seo-index.json"
    pointer_key = "public/publications/channels/front-page/en.json"
    assert store.put_order.index(explore_key) < store.put_order.index(pointer_key)
    assert store.put_order.index(editions_key) < store.put_order.index(pointer_key)
    assert store.put_order.index(seo_key) < store.put_order.index(pointer_key)
    assert json.loads(store.get(explore_key)) == {"surface": "explore", "version": "v1"}
    assert json.loads(store.get(editions_key)) == {"surface": "editions", "version": "v1"}
    assert json.loads(store.get(seo_key))["version"] == "v1"
    assert explore.calls == 1
    assert editions.calls == 1
    assert seo.calls == 1


def test_channel_snapshots_are_not_rewritten_when_unchanged() -> None:
    store = MemoryStore()
    service = delivery(
        store,
        Client(),
        explore=Explore(),
        edition_archive=EditionArchive(),
        seo_index=SeoIndex(),
    )
    service.deliver()
    puts_after_first = list(store.put_order)

    result = service.deliver()

    assert result["status"] == "unchanged"
    assert store.put_order == puts_after_first


def test_explore_presenter_failure_does_not_block_front_page() -> None:
    store = MemoryStore()
    client = Client()

    result = delivery(
        store,
        client,
        explore=Explore(fail=True),
        edition_archive=EditionArchive(),
        seo_index=SeoIndex(),
    ).deliver()

    assert result["status"] == "delivered"
    assert "public/publications/channels/front-page/en.json" in store.objects
    assert "public/publications/channels/explore/en.json" not in store.objects
    assert "public/publications/channels/editions/en.json" in store.objects
    assert "public/publications/channels/seo-index.json" in store.objects


def test_delivery_writes_referenced_topic_projections() -> None:
    store = MemoryStore()
    client = Client()
    topics = TopicPage()

    result = delivery(
        store,
        client,
        front_page=FrontPageWithTopics(),
        topic_page=topics,
    ).deliver()

    assert result["status"] == "delivered"
    topic_one = "public/publications/topics/topic-1/en.json"
    topic_two = "public/publications/topics/topic-2/en.json"
    pointer_key = "public/publications/channels/front-page/en.json"
    assert store.put_order.index(topic_one) < store.put_order.index(pointer_key)
    assert store.put_order.index(topic_two) < store.put_order.index(pointer_key)
    assert "public/publications/topics/topic-3/en.json" not in store.objects
    assert topics.built == ["topic-1", "topic-2"]
    assert client.calls[0]["json"]["topic_ids"] == ["topic-1", "topic-2"]


def test_missing_topic_projection_does_not_block_front_page() -> None:
    store = MemoryStore()

    result = delivery(
        store,
        Client(),
        front_page=FrontPageWithTopics(),
        topic_page=TopicPage(missing="topic-2"),
    ).deliver()

    assert result["status"] == "delivered"
    assert "public/publications/topics/topic-1/en.json" in store.objects
    assert "public/publications/topics/topic-2/en.json" not in store.objects
    assert "public/publications/channels/front-page/en.json" in store.objects
