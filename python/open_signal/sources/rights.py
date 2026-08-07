"""Rights capability checks (spec §85, OS-005).

Evaluates a RightsManifest's allowedOperations against the spec §85 default
policy: explicitly allowed -> use per manifest; explicitly denied -> no;
unknown (null) -> internal testing only, never public full-text or mass
redistribution.
"""

from __future__ import annotations

from typing import Any, Literal

# spec §85 allowedOperations keys
ALLOWED_OPERATIONS = (
    "internalAnalysis",
    "rawCaching",
    "metadataDisplay",
    "headlineDisplay",
    "excerptDisplay",
    "fullTextStorage",
    "historicalDisplay",
    "derivedMetrics",
    "commercialUse",
    "publicApiRedistribution",
)

Verdict = Literal["allowed", "denied", "internal_only"]


def check_operation(
    allowed_operations: dict[str, bool | None] | None,
    operation: str,
) -> Verdict:
    """Evaluate one operation against a manifest's allowedOperations.

    - ``allowed``: explicitly permitted
    - ``denied``: explicitly forbidden
    - ``internal_only``: unknown (null) — internal testing allowed, public
      full-text / mass redistribution forbidden (spec §85 default policy)
    """
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"unknown operation {operation!r}; valid: {ALLOWED_OPERATIONS}")

    value = (allowed_operations or {}).get(operation)
    if value is True:
        return "allowed"
    if value is False:
        return "denied"
    return "internal_only"


def can_publicly_display(
    allowed_operations: dict[str, bool | None] | None,
    *,
    full_text: bool = False,
) -> bool:
    """Whether content may be publicly displayed.

    Headline/excerpt display requires explicit allowance (spec §85: unknown
    rights never allow public copying or mass redistribution). Full-text
    display additionally requires ``fullTextStorage`` and ``excerptDisplay``
    (full-text implies displaying it).
    """
    if full_text:
        return (
            check_operation(allowed_operations, "fullTextStorage") == "allowed"
            and check_operation(allowed_operations, "headlineDisplay") != "denied"
        )
    return check_operation(allowed_operations, "headlineDisplay") == "allowed" or (
        check_operation(allowed_operations, "excerptDisplay") == "allowed"
    )


def can_store_raw(allowed_operations: dict[str, bool | None] | None) -> bool:
    """Raw caching for internal operation is allowed unless explicitly denied."""
    return check_operation(allowed_operations, "rawCaching") != "denied"


def summarize(manifest: Any) -> dict[str, Verdict]:
    """Summarize all operations for the operations console read view."""
    ops = getattr(manifest, "allowedOperations", None)
    return {op: check_operation(ops, op) for op in ALLOWED_OPERATIONS}
