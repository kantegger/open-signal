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
                            "evidence": {
                                "headline": "Original source headline 72%",
                                "url": "https://example.test/evidence/72",
                            },
                        }
                    ]
                }
            ],
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
    assert item["headline"].startswith("繁中：")
    assert "72%" in item["headline"]
    assert item["source_headline"] == "Rate-cut probability rose to 72%"
    assert item["evidence"]["headline"] == "Original source headline 72%"
    assert item["evidence"]["url"] == "https://example.test/evidence/72"
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
