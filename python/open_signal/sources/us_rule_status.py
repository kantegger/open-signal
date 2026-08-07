"""US Federal Rule status mapping (spec §33.10, OS-013).

Maps Federal Register documents to a rule-lifecycle status, and validates
transitions. Partial effectiveness is detected from the document text
signals defined in ``infra/ontologies/us-rule-status.yaml``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY_PATH = REPO_ROOT / "infra" / "ontologies" / "us-rule-status.yaml"

PARTIAL_DATE_RE = re.compile(r"effective\s+(?:dates|on)\s+(?:are|is)?")


class RuleStatusError(Exception):
    pass


def load_ontology(path: Path | str | None = None) -> dict[str, Any]:
    with (Path(path) if path else ONTOLOGY_PATH).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_effective_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).date()
        except ValueError:
            continue
    return None


def _detect_partial_effectiveness(doc: dict[str, Any]) -> bool:
    """Heuristics: multiple effective dates or text signals."""
    if doc.get("partial_effective"):
        return True
    dates = doc.get("dates")
    if isinstance(dates, list) and len(dates) > 1:
        return True
    text_blob = " ".join(
        str(doc.get(k) or "") for k in ("abstract", "dates", "body", "full_text")
    ).lower()
    signals = load_ontology().get("partial_effectiveness_signals", [])
    return any(s in text_blob for s in signals)


def map_document_status(doc: dict[str, Any], now: date | datetime | None = None) -> str:
    """Map one Federal Register document to a rule status id."""
    now = now.date() if isinstance(now, datetime) else (now or datetime.now(timezone.utc).date())
    ontology = load_ontology()
    mapping = ontology["document_type_mapping"]

    doc_type = doc.get("type") or doc.get("document_type") or ""
    mapped = mapping.get(doc_type)
    if mapped == "proposed":
        return "proposed"
    if mapped == "withdrawn":
        return "withdrawn"
    if mapped == "amended":
        return "amended"

    effective_date = _parse_effective_date(doc.get("effective_date"))
    if effective_date is None:
        # no explicit date -> inspect body/dates field
        effective_date = _parse_effective_date(doc.get("dates"))

    if _detect_partial_effectiveness(doc):
        return "partially_effective"

    if effective_date is None:
        # published final rule with no parsed date -> treat as final
        return "final"
    return "effective" if effective_date <= now else "final"


def transition_allowed(current: str, target: str, path: Path | str | None = None) -> bool:
    ontology = load_ontology(path)
    transitions = ontology.get("transitions", [])
    return any(t["from"] == current and t["to"] == target for t in transitions)


def validate_status_id(status: str, path: Path | str | None = None) -> bool:
    ontology = load_ontology(path)
    return any(s["id"] == status for s in ontology.get("statuses", []))


def apply_transition(current: str, target: str, path: Path | str | None = None) -> str:
    if not validate_status_id(target, path):
        raise RuleStatusError(f"unknown status {target!r}")
    if current != target and not transition_allowed(current, target, path):
        raise RuleStatusError(f"transition {current} -> {target} not allowed by ontology")
    return target
