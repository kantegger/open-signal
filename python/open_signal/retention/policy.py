"""Machine-readable raw payload retention policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "registries"
    / "retention-policy-registry.yaml"
)


@dataclass(frozen=True)
class RawRetentionPolicy:
    """Policy for reporting and bounded purge of superseded payloads."""

    version: str
    mode: str = "report_only"
    default_hot_days: int = 30
    source_hot_days: dict[str, int] = field(default_factory=dict)
    maximum_rows_per_run: int = 1000

    @classmethod
    def load(cls, path: Path | str | None = None) -> RawRetentionPolicy:
        policy_path = Path(path) if path else DEFAULT_POLICY_PATH
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("retention policy must be a mapping")
        purge = raw.get("purge")
        if not isinstance(purge, dict):
            raise TypeError("retention policy purge must be a mapping")
        source_hot_days = raw.get("source_hot_days") or {}
        if not isinstance(source_hot_days, dict):
            raise TypeError("source_hot_days must be a mapping")
        policy = cls(
            version=_required_text(raw, "version"),
            mode=_required_text(raw, "mode"),
            default_hot_days=_positive_int(raw, "default_hot_days"),
            source_hot_days={
                str(slug): _positive_value(days, f"source_hot_days.{slug}")
                for slug, days in source_hot_days.items()
            },
            maximum_rows_per_run=_positive_int(purge, "maximum_rows_per_run"),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.mode not in {"report_only", "active"}:
            raise ValueError("retention policy mode must be report_only or active")
        _positive_value(self.default_hot_days, "default_hot_days")
        _positive_value(self.maximum_rows_per_run, "maximum_rows_per_run")
        for slug, days in self.source_hot_days.items():
            if not slug:
                raise ValueError("source policy slug must not be empty")
            _positive_value(days, f"source_hot_days.{slug}")

    def hot_days_for(self, source_slug: str) -> int:
        return self.source_hot_days.get(source_slug, self.default_hot_days)

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "mode": self.mode,
            "default_hot_days": self.default_hot_days,
            "source_hot_days": dict(sorted(self.source_hot_days.items())),
            "purge": {
                "maximum_rows_per_run": self.maximum_rows_per_run,
            },
        }


def _required_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _positive_int(mapping: dict[str, Any], key: str) -> int:
    return _positive_value(mapping.get(key), key)


def _positive_value(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value
