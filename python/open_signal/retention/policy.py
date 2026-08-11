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
    """Policy used only to classify records until execution is activated."""

    version: str
    mode: str = "report_only"
    default_hot_days: int = 30
    source_hot_days: dict[str, int] = field(default_factory=dict)
    compression: str = "gzip"
    object_prefix: str = "raw-payload/v1"
    recovery_grace_days: int = 7
    maximum_rows_per_run: int = 1000

    @classmethod
    def load(cls, path: Path | str | None = None) -> RawRetentionPolicy:
        policy_path = Path(path) if path else DEFAULT_POLICY_PATH
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("retention policy must be a mapping")
        storage = raw.get("cold_storage")
        if not isinstance(storage, dict):
            raise TypeError("retention policy cold_storage must be a mapping")
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
            compression=_required_text(storage, "compression"),
            object_prefix=_required_text(storage, "object_prefix").strip("/"),
            recovery_grace_days=_positive_int(storage, "recovery_grace_days"),
            maximum_rows_per_run=_positive_int(storage, "maximum_rows_per_run"),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.mode != "report_only":
            raise ValueError("retention policy mode must remain report_only")
        if self.compression != "gzip":
            raise ValueError("only deterministic gzip archives are supported")
        if not self.object_prefix:
            raise ValueError("object_prefix must not be empty")
        _positive_value(self.default_hot_days, "default_hot_days")
        _positive_value(self.recovery_grace_days, "recovery_grace_days")
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
            "cold_storage": {
                "compression": self.compression,
                "object_prefix": self.object_prefix,
                "recovery_grace_days": self.recovery_grace_days,
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
