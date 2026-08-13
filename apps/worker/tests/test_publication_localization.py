"""Publication localization safety tests (database-free)."""

from __future__ import annotations

import json

import pytest
from open_signal.agents.runtime import LlmUsage
from open_signal.publication.localization import (
    LOCALIZATION_VERSION,
    LocalizationError,
    PublicationLocalizer,
)


class FakeClient:
    def __init__(
        self,
        *,
        tamper_with_token: bool = False,
        compact_chinese: bool = False,
    ) -> None:
        self.tamper_with_token = tamper_with_token
        self.compact_chinese = compact_chinese
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        request = json.loads(messages[1]["content"])
        self.calls.append({"request": request, "kwargs": kwargs})
        translations = {}
        for item in request["items"]:
            if self.compact_chinese:
                tokens = [
                    part
                    for part in item["text"].split()
                    if part.startswith("__OS_TOKEN_")
                ]
                text = "繁中" + "".join(tokens)
            else:
                text = f"繁中：{item['text']}"
            if self.tamper_with_token:
                text = text.replace("__OS_TOKEN_0000__", "999")
            translations[item["id"]] = text
        return (
            json.dumps({"translations": translations}, ensure_ascii=False),
            LlmUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )


def sample_payloads() -> list[dict]:
    return [
        {
            "locale": {
                "requested": "zh-Hant",
                "published": "en",
                "fallback_used": True,
                "translation_provenance": None,
            },
            "snapshot": {"id": "edition-1"},
            "slots": [
                {
                    "items": [
                        {
                            "headline": "Rate-cut probability rose to 72%",
                            "summary": "The market moved 4.2pp over 24 hours.",
                            "claim_ids": ["claim-1"],
                            "display_fields": {
                                "old_text": "Coverage applies only to existing facilities.",
                                "new_text": "Coverage now includes newly licensed facilities.",
                                "change_title": "Material rule coverage expanded after licensing change",
                                "window": "next 24 hours",
                                "work_title": "Phase 2 trial design for solid tumors",
                            },
                            "evidence": {
                                "headline": "Original source headline 72%",
                                "url": "https://example.test/evidence/72",
                            },
                        }
                    ]
                }
            ],
            "publication_context": {
                "research": [
                    {
                        "topic_label": "Oncology immunotherapy",
                        "entity": "Anhui Provincial Hospital + 2 other sponsors",
                        "source_label": "ClinicalTrials.gov",
                    }
                ]
            },
        },
        {
            "locale": {
                "requested": "zh-Hant",
                "published": "en",
                "fallback_used": True,
                "translation_provenance": None,
            },
            "claim": {
                "id": "claim-1",
                "public_statement": "YES probability increased from 68% to 72%.",
                "structured_proposition": {
                    "statement": "YES probability increased from 68% to 72%.",
                    "value": 0.72,
                },
            },
            "observation": "The observed probability increased by 4.2pp.",
        },
    ]


def test_localization_translates_presentation_but_preserves_truth_fields() -> None:
    client = FakeClient()
    result = PublicationLocalizer(client).localize_many(
        sample_payloads(),
        locale="zh-Hant",
    )

    page, claim = result.payloads
    item = page["slots"][0]["items"][0]
    fields = item["display_fields"]
    assert item["headline"].startswith("繁中：")
    assert "72%" in item["headline"]
    assert item["source_headline"] == "Rate-cut probability rose to 72%"
    assert item["evidence"]["headline"] == "Original source headline 72%"
    assert item["evidence"]["url"] == "https://example.test/evidence/72"
    assert fields["old_text"].startswith("繁中：")
    assert fields["new_text"].startswith("繁中：")
    assert fields["change_title"].startswith("繁中：")
    assert fields["window"].startswith("繁中：")
    assert fields["work_title"].startswith("繁中：")
    research = page["publication_context"]["research"][0]
    assert research["topic_label"].startswith("繁中：")
    assert research["entity"].startswith("繁中：")
    assert research["source_label"] == "ClinicalTrials.gov"
    assert claim["claim"]["public_statement"].startswith("繁中：")
    assert (
        claim["claim"]["source_public_statement"]
        == "YES probability increased from 68% to 72%."
    )
    assert claim["claim"]["structured_proposition"] == {
        "statement": "YES probability increased from 68% to 72%.",
        "value": 0.72,
    }
    assert page["locale"] == {
        "requested": "zh-Hant",
        "published": "zh-Hant",
        "fallback_used": False,
        "translation_provenance": f"deepseek/deepseek-chat:{LOCALIZATION_VERSION}",
    }
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 8
    assert result.translated_string_count > 0


def test_localization_rejects_changed_protected_tokens() -> None:
    localizer = PublicationLocalizer(FakeClient(tamper_with_token=True))

    with pytest.raises(LocalizationError, match="protected number"):
        localizer.localize_many(sample_payloads(), locale="zh-Hant")


def test_localization_allows_chinese_text_adjacent_to_protected_numbers() -> None:
    result = PublicationLocalizer(FakeClient(compact_chinese=True)).localize_many(
        sample_payloads(),
        locale="zh-Hant",
    )

    assert "72%" in result.payloads[0]["slots"][0]["items"][0]["headline"]


def test_localization_rejects_unsupported_target() -> None:
    with pytest.raises(LocalizationError, match="unsupported localization target"):
        PublicationLocalizer(FakeClient()).localize_many(
            sample_payloads(),
            locale="ja",
        )


def test_localization_reuses_valid_translation_memory_without_llm_calls() -> None:
    first_client = FakeClient()
    first = PublicationLocalizer(first_client).localize_many(
        sample_payloads(),
        locale="zh-Hant",
    )
    second_client = FakeClient()

    second = PublicationLocalizer(second_client).localize_many(
        sample_payloads(),
        locale="zh-Hant",
        translation_memory=first.new_translations,
    )

    assert second_client.calls == []
    assert second.cache_hit_count == first.translated_string_count
    assert second.cache_miss_count == 0
    assert second.prompt_tokens == 0
    assert second.completion_tokens == 0
    assert second.new_translations == {}
    assert second.payloads == first.payloads


def test_invalid_cached_english_prose_is_retranslated() -> None:
    client = FakeClient()
    source = "Rate-cut probability rose to 72%"

    result = PublicationLocalizer(client).localize_many(
        sample_payloads(),
        locale="zh-Hant",
        translation_memory={source: source},
    )

    assert client.calls
    assert result.cache_hit_count < result.translated_string_count
    assert result.cache_miss_count > 0
    assert result.payloads[0]["slots"][0]["items"][0]["headline"].startswith(
        "繁中："
    )
