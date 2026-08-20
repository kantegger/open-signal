"""Deliver an atomically composed Edition to immutable public object storage.

Database publication and external delivery intentionally have separate failure
boundaries. The composer moves the PostgreSQL channel pointer transactionally;
this service then copies that complete snapshot to R2, advances the R2 current
pointer last, and asks Vercel to invalidate only the affected cache tags.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from open_signal.api.editions import EditionArchivePresenter, FrontPagePresenter
from open_signal.api.explore import ExplorePresenter
from open_signal.api.presenters import ClaimPagePresenter
from open_signal.api.topics import SeoIndexPresenter, TopicPagePresenter
from open_signal.publication.localization import (
    LOCALIZATION_VERSION,
    PublicationLocalizer,
)
from open_signal.sources.artifact_store import ArtifactStore, S3ArtifactStore

logger = logging.getLogger(__name__)

DELIVERY_VERSION = "1.0.0"
CONTENT_TYPE = "application/json; charset=utf-8"
SUPPORTED_DELIVERY_LOCALES = frozenset({"en", "zh-Hant"})


@dataclass(frozen=True)
class PublicationKeys:
    edition: str
    manifest: str
    localization: str
    translation_memory: str
    current: str
    explore: str
    editions: str
    seo_index: str
    receipt: str
    claim_snapshots: tuple[str, ...]
    claim_current: tuple[str, ...]
    topic_current: tuple[str, ...]


class PublicationDelivery:
    """Copy the current database snapshot to R2 and notify Vercel once."""

    def __init__(
        self,
        engine: Any,
        store: ArtifactStore,
        *,
        revalidate_url: str,
        revalidate_token: str,
        client: Any | None = None,
        front_page: Any | None = None,
        claim_page: Any | None = None,
        localizer: PublicationLocalizer | None = None,
        explore: Any | None = None,
        edition_archive: Any | None = None,
        seo_index: Any | None = None,
        topic_page: Any | None = None,
    ) -> None:
        self.store = store
        self.revalidate_url = revalidate_url
        self.revalidate_token = revalidate_token
        self.client = client or httpx.Client(timeout=20.0)
        self.front_page = front_page or FrontPagePresenter(engine)
        self.claim_page = claim_page or ClaimPagePresenter(engine)
        self.localizer = localizer
        self.explore = explore
        self.edition_archive = edition_archive
        self.seo_index = seo_index
        self.topic_page = topic_page

    def deliver(self, *, locale: str = "en") -> dict[str, Any]:
        if locale not in SUPPORTED_DELIVERY_LOCALES:
            raise ValueError(f"unsupported publication locale: {locale}")
        page = self.front_page.build(locale=locale)
        if page is None:
            return {"status": "empty", "locale": locale}

        edition_id = str(page["snapshot"]["id"])
        claim_ids = _claim_ids(page)
        topic_ids = _topic_ids(page)
        keys = _keys(edition_id, claim_ids, topic_ids, locale)

        current = self._json_or_none(keys.current)
        expected_localization_version = (
            LOCALIZATION_VERSION if locale != "en" else None
        )
        already_current = (
            current is not None
            and current.get("edition_id") == edition_id
            and current.get("locale") == locale
            and current.get("localization_version")
            == expected_localization_version
        )
        if already_current and self.store.exists(keys.receipt):
            self._write_read_models(keys, locale=locale, topic_ids=topic_ids)
            return {
                "status": "unchanged",
                "edition_id": edition_id,
                "locale": locale,
                "claim_count": len(claim_ids),
            }

        claim_payloads: dict[str, dict[str, Any]] = {}
        for claim_id in claim_ids:
            payload = self.claim_page.build(claim_id, locale=locale)
            if payload is None:
                raise RuntimeError(
                    f"edition {edition_id} references missing claim {claim_id}"
                )
            claim_payloads[claim_id] = payload

        localization_metadata: dict[str, Any] | None = None
        if locale != "en":
            page, claim_payloads, localization_metadata = self._localize(
                page,
                claim_payloads,
                edition_id=edition_id,
                claim_ids=claim_ids,
                locale=locale,
                key=keys.localization,
                translation_memory_key=keys.translation_memory,
            )

        edition_bytes = _json_bytes(page)
        claim_bytes = {
            claim_id: _json_bytes(payload)
            for claim_id, payload in claim_payloads.items()
        }
        manifest = {
            "delivery_version": DELIVERY_VERSION,
            "edition_id": edition_id,
            "locale": locale,
            "published_at": page["snapshot"].get("published_at"),
            "front_page": {
                "key": keys.edition,
                "sha256": _sha256(edition_bytes),
            },
            "claims": [
                {
                    "id": claim_id,
                    "key": snapshot_key,
                    "current_key": current_key,
                    "sha256": _sha256(claim_bytes[claim_id]),
                }
                for claim_id, snapshot_key, current_key in zip(
                    claim_ids,
                    keys.claim_snapshots,
                    keys.claim_current,
                    strict=True,
                )
            ],
        }
        if localization_metadata is not None:
            manifest["localization"] = localization_metadata
        manifest_bytes = _json_bytes(manifest)
        pointer = {
            "delivery_version": DELIVERY_VERSION,
            "edition_id": edition_id,
            "locale": locale,
            "published_at": page["snapshot"].get("published_at"),
            "manifest_key": keys.manifest,
            "manifest_sha256": _sha256(manifest_bytes),
            "front_page_key": keys.edition,
            "front_page_sha256": _sha256(edition_bytes),
        }
        if expected_localization_version is not None:
            pointer["localization_version"] = expected_localization_version

        self._put_immutable(keys.edition, edition_bytes)
        for claim_id, key in zip(claim_ids, keys.claim_snapshots, strict=True):
            self._put_immutable(key, claim_bytes[claim_id])
        self._put_immutable(keys.manifest, manifest_bytes)

        # Claim pages are current projections over an append-only Ledger. Keep
        # an immutable copy inside each Edition for replay, then refresh the
        # public projection before exposing an Edition that links to it.
        for claim_id, key in zip(claim_ids, keys.claim_current, strict=True):
            self._put_mutable_if_changed(key, claim_bytes[claim_id])

        self._write_read_models(keys, locale=locale, topic_ids=topic_ids)

        # The page pointer moves only after every referenced object exists.
        if not already_current:
            self.store.put(keys.current, _json_bytes(pointer), content_type=CONTENT_TYPE)

        response = self.client.post(
            self.revalidate_url,
            headers={"Authorization": f"Bearer {self.revalidate_token}"},
            json={
                "edition_id": edition_id,
                "locale": locale,
                "claim_ids": claim_ids,
                "topic_ids": topic_ids,
            },
        )
        response.raise_for_status()
        receipt = {
            "delivery_version": DELIVERY_VERSION,
            "edition_id": edition_id,
            "locale": locale,
            "notified": True,
        }
        self._put_immutable(keys.receipt, _json_bytes(receipt))
        return {
            "status": "delivered",
            "edition_id": edition_id,
            "locale": locale,
            "claim_count": len(claim_ids),
            "manifest_sha256": pointer["manifest_sha256"],
        }

    def _localize(
        self,
        page: dict[str, Any],
        claim_payloads: dict[str, dict[str, Any]],
        *,
        edition_id: str,
        claim_ids: list[str],
        locale: str,
        key: str,
        translation_memory_key: str,
    ) -> tuple[
        dict[str, Any],
        dict[str, dict[str, Any]],
        dict[str, Any],
    ]:
        existing = self._json_or_none(key)
        if existing is None:
            if self.localizer is None:
                raise RuntimeError(
                    f"publication localizer is not configured for {locale}"
                )
            source_payloads = [page, *(claim_payloads[claim_id] for claim_id in claim_ids)]
            translation_memory = self._load_translation_memory(
                translation_memory_key,
                locale=locale,
            )
            batch = self.localizer.localize_many(
                source_payloads,
                locale=locale,
                translation_memory=translation_memory,
            )
            if len(batch.payloads) != len(source_payloads):
                raise RuntimeError("publication localizer returned the wrong payload count")
            bundle = {
                "localization_version": LOCALIZATION_VERSION,
                "edition_id": edition_id,
                "locale": locale,
                "provenance": batch.provenance,
                "usage": {
                    "prompt_tokens": batch.prompt_tokens,
                    "completion_tokens": batch.completion_tokens,
                    "estimated_cost_usd": batch.estimated_cost_usd,
                    "translated_string_count": batch.translated_string_count,
                    "cache_hit_count": batch.cache_hit_count,
                    "cache_miss_count": batch.cache_miss_count,
                },
                "translation_memory_key": translation_memory_key,
                "page": batch.payloads[0],
                "claims": {
                    claim_id: payload
                    for claim_id, payload in zip(
                        claim_ids,
                        batch.payloads[1:],
                        strict=True,
                    )
                },
            }
            bundle_bytes = _json_bytes(bundle)
            self._put_immutable(key, bundle_bytes)
            if batch.new_translations:
                translation_memory.update(batch.new_translations)
                self._put_mutable_if_changed(
                    translation_memory_key,
                    _translation_memory_bytes(
                        translation_memory,
                        locale=locale,
                    ),
                )
        else:
            bundle = existing

        if (
            bundle.get("edition_id") != edition_id
            or bundle.get("locale") != locale
            or not isinstance(bundle.get("page"), dict)
            or not isinstance(bundle.get("claims"), dict)
        ):
            raise RuntimeError(f"invalid publication localization bundle: {key}")
        localized_claims = bundle["claims"]
        if set(localized_claims) != set(claim_ids) or not all(
            isinstance(localized_claims[claim_id], dict) for claim_id in claim_ids
        ):
            raise RuntimeError(f"incomplete publication localization bundle: {key}")
        metadata = {
            "key": key,
            "sha256": _sha256(_json_bytes(bundle)),
            "version": bundle.get("localization_version"),
            "provenance": bundle.get("provenance"),
            "usage": bundle.get("usage"),
        }
        return (
            bundle["page"],
            {claim_id: localized_claims[claim_id] for claim_id in claim_ids},
            metadata,
        )

    def _load_translation_memory(
        self,
        key: str,
        *,
        locale: str,
    ) -> dict[str, str]:
        if not self.store.exists(key):
            return {}
        try:
            payload = json.loads(self.store.get(key))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or payload.get("localization_version") != LOCALIZATION_VERSION
            or payload.get("locale") != locale
            or not isinstance(payload.get("entries"), dict)
        ):
            return {}

        memory: dict[str, str] = {}
        for digest, raw_entry in payload["entries"].items():
            if not isinstance(digest, str) or not isinstance(raw_entry, dict):
                continue
            source = raw_entry.get("source")
            translation = raw_entry.get("translation")
            if not isinstance(source, str) or not isinstance(translation, str):
                continue
            if _sha256(source.encode("utf-8")) != digest:
                continue
            memory[source] = translation
        return memory

    def _write_read_models(
        self,
        keys: PublicationKeys,
        *,
        locale: str,
        topic_ids: list[str],
    ) -> None:
        self._write_optional_snapshot(keys.explore, self.explore, "explore")
        self._write_optional_snapshot(
            keys.editions,
            self.edition_archive,
            "edition archive",
        )
        self._write_optional_snapshot(keys.seo_index, self.seo_index, "seo index")
        if self.topic_page is None:
            return
        for topic_id, key in zip(topic_ids, keys.topic_current, strict=True):
            try:
                payload = self.topic_page.build(topic_id)
            except Exception:
                logger.warning(
                    "publication topic snapshot failed",
                    extra={"topic_id": topic_id, "locale": locale},
                    exc_info=True,
                )
                continue
            if not isinstance(payload, dict):
                continue
            self._put_mutable_if_changed(key, _json_bytes(payload))

    def _write_optional_snapshot(
        self,
        key: str,
        presenter: Any,
        label: str,
    ) -> None:
        if presenter is None:
            return
        try:
            payload = presenter.build()
        except Exception:
            logger.warning(
                "publication %s snapshot failed",
                label,
                exc_info=True,
            )
            return
        if not isinstance(payload, dict):
            return
        self._put_mutable_if_changed(key, _json_bytes(payload))

    def _put_immutable(self, key: str, data: bytes) -> None:
        if self.store.exists(key):
            if self.store.get(key) != data:
                raise RuntimeError(f"immutable publication object changed: {key}")
            return
        self.store.put(key, data, content_type=CONTENT_TYPE)

    def _put_mutable_if_changed(self, key: str, data: bytes) -> None:
        if self.store.exists(key) and self.store.get(key) == data:
            return
        self.store.put(key, data, content_type=CONTENT_TYPE)

    def _json_or_none(self, key: str) -> dict[str, Any] | None:
        if not self.store.exists(key):
            return None
        try:
            value = json.loads(self.store.get(key))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"invalid publication pointer: {key}") from exc
        return value if isinstance(value, dict) else None


def from_environment(engine: Any) -> PublicationDelivery | None:
    """Build the R2 delivery adapter, or disable it when wholly unconfigured."""
    values = {
        "endpoint_url": os.environ.get("OPEN_SIGNAL_R2_ENDPOINT_URL"),
        "access_key": os.environ.get("OPEN_SIGNAL_R2_ACCESS_KEY_ID"),
        "secret_key": os.environ.get("OPEN_SIGNAL_R2_SECRET_ACCESS_KEY"),
        "bucket": os.environ.get("OPEN_SIGNAL_R2_PUBLIC_BUCKET"),
        "revalidate_url": os.environ.get("OPEN_SIGNAL_REVALIDATE_URL"),
        "revalidate_token": os.environ.get("OPEN_SIGNAL_REVALIDATE_TOKEN"),
    }
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "incomplete publication delivery configuration: " + ", ".join(missing)
        )
    store = S3ArtifactStore(
        str(values["bucket"]),
        endpoint_url=str(values["endpoint_url"]),
        aws_access_key_id=str(values["access_key"]),
        aws_secret_access_key=str(values["secret_key"]),
        region_name="auto",
    )
    return PublicationDelivery(
        engine,
        store,
        revalidate_url=str(values["revalidate_url"]),
        revalidate_token=str(values["revalidate_token"]),
        # Public delivery is English-only. Keep the optional localizer injection
        # for isolated tests, but never construct a paid translation client here.
        localizer=None,
        explore=ExplorePresenter(engine),
        edition_archive=EditionArchivePresenter(engine),
        seo_index=SeoIndexPresenter(engine),
        topic_page=TopicPagePresenter(engine),
    )


def _claim_ids(page: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for slot in page.get("slots", []):
        for item in slot.get("items", []):
            for value in item.get("claim_ids", []):
                claim_id = str(value)
                if claim_id and claim_id not in seen:
                    seen.add(claim_id)
                    result.append(claim_id)
    return result


def _topic_ids(page: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for slot in page.get("slots", []):
        for item in slot.get("items", []):
            topic = item.get("topic")
            topic_id = topic.get("id") if isinstance(topic, dict) else None
            if topic_id and str(topic_id) not in seen:
                seen.add(str(topic_id))
                result.append(str(topic_id))
    return result


def _keys(
    edition_id: str,
    claim_ids: list[str],
    topic_ids: list[str],
    locale: str,
) -> PublicationKeys:
    prefix = "public/publications"
    presentation_locale = (
        locale if locale == "en" else f"{locale}.{LOCALIZATION_VERSION}"
    )
    return PublicationKeys(
        edition=(
            f"{prefix}/editions/{edition_id}/front-page."
            f"{presentation_locale}.json"
        ),
        manifest=(
            f"{prefix}/editions/{edition_id}/manifest."
            f"{presentation_locale}.json"
        ),
        localization=(
            f"{prefix}/editions/{edition_id}/localization."
            f"{presentation_locale}.json"
        ),
        translation_memory=(
            f"{prefix}/localization-memory/{locale}/"
            f"{LOCALIZATION_VERSION}.json"
        ),
        current=f"{prefix}/channels/front-page/{locale}.json",
        explore=f"{prefix}/channels/explore/{locale}.json",
        editions=f"{prefix}/channels/editions/{locale}.json",
        seo_index=f"{prefix}/channels/seo-index.json",
        receipt=(
            f"{prefix}/deliveries/{edition_id}/vercel."
            f"{presentation_locale}.json"
        ),
        claim_snapshots=tuple(
            f"{prefix}/editions/{edition_id}/claims/"
            f"{claim_id}.{presentation_locale}.json"
            for claim_id in claim_ids
        ),
        claim_current=tuple(
            f"{prefix}/claims/{claim_id}/{locale}.json"
            for claim_id in claim_ids
        ),
        topic_current=tuple(
            f"{prefix}/topics/{topic_id}/{locale}.json"
            for topic_id in topic_ids
        ),
    )


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _translation_memory_bytes(
    translations: dict[str, str],
    *,
    locale: str,
) -> bytes:
    entries = {
        _sha256(source.encode("utf-8")): {
            "source": source,
            "translation": translation,
        }
        for source, translation in translations.items()
    }
    return _json_bytes(
        {
            "schema_version": 1,
            "localization_version": LOCALIZATION_VERSION,
            "locale": locale,
            "entries": entries,
        }
    )
