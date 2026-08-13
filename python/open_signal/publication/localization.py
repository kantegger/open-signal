"""Versioned localization of immutable public presentation payloads.

Localization is deliberately downstream of Claim verification.  It translates
only presentation fields, never typed propositions, identifiers, source
evidence, numbers, dates, confidence, or status.  The localized result is
sealed by PublicationDelivery alongside the source Edition.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from open_signal.agents.runtime import DeepSeekClient, LlmUsage

LOCALIZATION_VERSION = "os-l10n-002"
SUPPORTED_TARGETS = frozenset({"zh-Hant"})

_TRANSLATABLE_FIELDS = frozenset(
    {
        "analysis",
        "assessment",
        "baseline_label",
        "change_reason",
        "change_summary",
        "change_title",
        "current_text",
        "dek",
        "description",
        "detail",
        "diff_summary",
        "entity",
        "event_title",
        "expectation_title",
        "headline",
        "interpretation",
        "item_title",
        "known_limitations",
        "limitation",
        "method_summary",
        "metric",
        "new_text",
        "observation",
        "old_text",
        "option_label",
        "original_claim",
        "outcome",
        "previous_text",
        "primary_observation",
        "primary_signal",
        "public_statement",
        "question",
        "reason",
        "rationale",
        "resolution_rule_summary",
        "rule_title",
        "statement",
        "summary",
        "title",
        "topic_label",
        "unresolved_questions",
        "window",
        "window_label",
        "work_title",
    }
)
_SOURCE_EVIDENCE_FIELDS = frozenset(
    {
        "counter",
        "counterevidence",
        "counter_evidence",
        "evidence",
        "evidence_preview",
        "evidence_record",
        "primary",
        "primary_evidence",
        "source_coverage",
        "supporting",
        "supporting_evidence",
        "structured_proposition",
    }
)
_PROTECTED_PATTERN = re.compile(
    r"https?://[^\s]+"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    r"|\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|(?:[+$€£¥-]?\d[\d,.]*(?:\s?(?:%|pp|bps|h|d|hours?|days?|weeks?|months?|years?))?)",
    re.IGNORECASE,
)
_PLACEHOLDER_PATTERN = re.compile(r"__OS_TOKEN_\d{4}__")
_HAS_ENGLISH = re.compile(r"[A-Za-z]")
_HAS_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_ENGLISH_WORD = re.compile(r"[A-Za-z]{2,}")
_ENUM_LIKE = re.compile(r"^[A-Za-z0-9_.:/-]+$")


class LocalizationError(RuntimeError):
    """Raised when a localized presentation cannot be safely produced."""


@dataclass(frozen=True)
class LocalizationBatch:
    payloads: list[dict[str, Any]]
    provenance: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    translated_string_count: int
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    new_translations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _TextRef:
    payload_index: int
    path: tuple[str | int, ...]
    source: str


class PublicationLocalizer:
    """Translate presentation strings while preserving all truth-bearing data."""

    def __init__(
        self,
        client: DeepSeekClient,
        *,
        model: str = "deepseek-chat",
        batch_size: int = 45,
    ) -> None:
        self.client = client
        self.model = model
        self.batch_size = batch_size

    @property
    def provenance(self) -> str:
        return f"deepseek/{self.model}:{LOCALIZATION_VERSION}"

    def localize_many(
        self,
        payloads: list[dict[str, Any]],
        *,
        locale: str,
        translation_memory: Mapping[str, str] | None = None,
    ) -> LocalizationBatch:
        if locale not in SUPPORTED_TARGETS:
            raise LocalizationError(f"unsupported localization target: {locale}")
        localized = copy.deepcopy(payloads)
        for payload in localized:
            _preserve_source_presentation(payload)
        refs = _collect_text_refs(localized)
        unique_sources = list(dict.fromkeys(ref.source for ref in refs))
        translated: dict[str, str] = {}
        cache_hits = 0
        misses: list[str] = []
        memory = translation_memory or {}
        for source in unique_sources:
            cached = memory.get(source)
            if isinstance(cached, str):
                try:
                    _validate_restored_translation(source, cached)
                except LocalizationError:
                    misses.append(source)
                else:
                    translated[source] = cached.strip()
                    cache_hits += 1
            else:
                misses.append(source)

        usage = LlmUsage()
        new_translations: dict[str, str] = {}

        for offset in range(0, len(misses), self.batch_size):
            batch = misses[offset : offset + self.batch_size]
            batch_result, batch_usage = self._translate_batch(batch, locale=locale)
            translated.update(batch_result)
            new_translations.update(batch_result)
            usage.prompt_tokens += batch_usage.prompt_tokens
            usage.completion_tokens += batch_usage.completion_tokens
            usage.total_tokens += batch_usage.total_tokens

        for ref in refs:
            value = translated.get(ref.source)
            if value is None:
                raise LocalizationError("translation response omitted a presentation string")
            _set_path(localized[ref.payload_index], ref.path, value)

        for payload in localized:
            _mark_locale(payload, locale=locale, provenance=self.provenance)

        return LocalizationBatch(
            payloads=localized,
            provenance=self.provenance,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            estimated_cost_usd=usage.cost_usd(self.model),
            translated_string_count=len(unique_sources),
            cache_hit_count=cache_hits,
            cache_miss_count=len(misses),
            new_translations=new_translations,
        )

    def _translate_batch(
        self,
        values: list[str],
        *,
        locale: str,
    ) -> tuple[dict[str, str], LlmUsage]:
        protected: list[tuple[str, dict[str, str]]] = [
            _protect_tokens(value) for value in values
        ]
        items = [
            {"id": str(index), "text": value}
            for index, (value, _) in enumerate(protected)
        ]
        system = (
            "You localize a public evidence product from English into Traditional Chinese "
            "(BCP 47 zh-Hant). Translate faithfully and concisely. Preserve uncertainty, "
            "modality, and epistemic strength exactly; never add causality, advice, or facts. "
            "Translate every sentence and descriptive phrase; keep official proper names "
            "recognizable and use established Traditional Chinese names when they exist. "
            "Use natural newsroom Traditional Chinese, not word-for-word English syntax. "
            "Every __OS_TOKEN_0000__ placeholder must appear exactly once and unchanged. "
            "Return only JSON in the form "
            '{"translations":{"0":"..."}} with one entry for every input id.'
        )
        content, usage = self.client.chat(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"target_locale": locale, "items": items},
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.model,
            temperature=0.0,
            max_tokens=4096,
            json_mode=True,
        )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LocalizationError("localizer returned invalid JSON") from exc
        raw = parsed.get("translations") if isinstance(parsed, dict) else None
        if not isinstance(raw, dict) or set(raw) != {str(i) for i in range(len(values))}:
            raise LocalizationError("localizer returned an incomplete translation map")

        result: dict[str, str] = {}
        for index, source in enumerate(values):
            candidate = raw.get(str(index))
            if not isinstance(candidate, str) or not candidate.strip():
                raise LocalizationError("localizer returned an empty translation")
            protected_source, tokens = protected[index]
            expected = set(tokens)
            actual = set(_PLACEHOLDER_PATTERN.findall(candidate))
            if actual != expected or any(candidate.count(token) != 1 for token in expected):
                raise LocalizationError("localizer changed a protected number, date, or URL")
            restored = candidate.strip()
            for placeholder, original in tokens.items():
                restored = restored.replace(placeholder, original)
            _validate_restored_translation(source, restored)
            result[source] = restored
            if protected_source == source and not tokens and restored == source:
                # Exact preservation is allowed for proper names, but a whole batch of
                # untouched English prose is almost certainly a failed localization.
                continue
        if values and all(result[value] == value for value in values):
            raise LocalizationError("localizer returned the English source unchanged")
        return result, usage


def _collect_text_refs(payloads: list[dict[str, Any]]) -> list[_TextRef]:
    refs: list[_TextRef] = []

    def visit(
        value: Any,
        *,
        payload_index: int,
        path: tuple[str | int, ...],
        parent_field: str | None,
        blocked: bool,
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_blocked = blocked or key in _SOURCE_EVIDENCE_FIELDS
                visit(
                    child,
                    payload_index=payload_index,
                    path=(*path, key),
                    parent_field=key,
                    blocked=child_blocked,
                )
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(
                    child,
                    payload_index=payload_index,
                    path=(*path, index),
                    parent_field=parent_field,
                    blocked=blocked,
                )
            return
        if (
            not blocked
            and isinstance(value, str)
            and parent_field in _TRANSLATABLE_FIELDS
            and _should_translate(value)
        ):
            refs.append(_TextRef(payload_index, path, value))

    for index, payload in enumerate(payloads):
        visit(
            payload,
            payload_index=index,
            path=(),
            parent_field=None,
            blocked=False,
        )
    return refs


def _should_translate(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or not _HAS_ENGLISH.search(text):
        return False
    if _ENUM_LIKE.fullmatch(text) and " " not in text:
        return False
    return not text.startswith(("http://", "https://"))


def _protect_tokens(value: str) -> tuple[str, dict[str, str]]:
    tokens: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        placeholder = f"__OS_TOKEN_{len(tokens):04d}__"
        tokens[placeholder] = match.group(0)
        return placeholder

    return _PROTECTED_PATTERN.sub(replace, value), tokens


def _numeric_tokens(value: str) -> list[str]:
    return [
        match.group(0)
        for match in _PROTECTED_PATTERN.finditer(value)
        if any(ch.isdigit() for ch in match.group(0))
    ]


def _validate_restored_translation(source: str, candidate: str) -> None:
    value = candidate.strip()
    if not value:
        raise LocalizationError("localizer returned an empty translation")
    source_tokens = Counter(match.group(0) for match in _PROTECTED_PATTERN.finditer(source))
    candidate_tokens = Counter(match.group(0) for match in _PROTECTED_PATTERN.finditer(value))
    if source_tokens != candidate_tokens:
        raise LocalizationError("localized presentation changed a protected number, date, or URL")
    if _numeric_tokens(source) != _numeric_tokens(value):
        raise LocalizationError("localized presentation changed numeric tokens")
    if len(_ENGLISH_WORD.findall(source)) >= 2 and not _HAS_CJK.search(value):
        raise LocalizationError("localized presentation contains no Traditional Chinese text")


def _set_path(payload: dict[str, Any], path: tuple[str | int, ...], value: str) -> None:
    cursor: Any = payload
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value


def _preserve_source_presentation(payload: dict[str, Any]) -> None:
    claim = payload.get("claim")
    if isinstance(claim, dict) and isinstance(claim.get("public_statement"), str):
        claim.setdefault("source_public_statement", claim["public_statement"])
    for slot in payload.get("slots", []):
        if not isinstance(slot, dict):
            continue
        for item in slot.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("headline"), str):
                item.setdefault("source_headline", item["headline"])


def _mark_locale(value: Any, *, locale: str, provenance: str) -> None:
    if isinstance(value, dict):
        locale_state = value.get("locale")
        if isinstance(locale_state, dict) and (
            "requested" in locale_state or "published" in locale_state
        ):
            locale_state.update(
                {
                    "requested": locale,
                    "published": locale,
                    "fallback_used": False,
                    "translation_provenance": provenance,
                }
            )
        for child in value.values():
            _mark_locale(child, locale=locale, provenance=provenance)
    elif isinstance(value, list):
        for child in value:
            _mark_locale(child, locale=locale, provenance=provenance)
