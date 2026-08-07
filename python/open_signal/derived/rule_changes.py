"""Rule change detection (spec §33.x, OS-014).

Paragraph alignment between an old rule text and a new one, classification
of add/delete/change hunks, filtering of technical changes (dates, numbering,
formatting), and Rule Change Type candidates. Materiality judgment is left
to the agent (next milestone).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

TECHNICAL_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
    re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s+\d{4}\b", re.I),
    re.compile(r"effective\s+(?:on|date)?\s*:?\s*\d{1,2}/\d{1,2}/\d{2,4}", re.I),
    re.compile(r"\b\d{1,2}\s+days?\b", re.I),  # day counts
    re.compile(r"FR\s+\d{1,6}", re.I),  # Federal Register citation
    re.compile(r"^\s*\(\s*[a-z0-9]+\s*\)\s*$"),  # bare numbering
    re.compile(r"\b(amended|redesignated|republished)\b", re.I),  # procedural verbs
    re.compile(r"^.*(federal register|document number|docket|comment period).*$", re.I),
]

TECHNICAL_VERBS = {"is amended", "is revised", "is added", "is removed", "is redesignated"}


@dataclass
class ParagraphChange:
    kind: str  # "add" | "delete" | "change"
    paragraph_id: str | None
    old_text: str = ""
    new_text: str = ""
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "paragraph_id": self.paragraph_id,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "confidence": self.confidence,
        }


@dataclass
class RuleDiff:
    old_version: str
    new_version: str
    changes: list[ParagraphChange] = field(default_factory=list)

    def substantive(self) -> list[ParagraphChange]:
        return [c for c in self.changes if not is_technical_change(c)]

    def change_types(self) -> list[dict[str, Any]]:
        """Rule Change Type candidates for the materiality agent."""
        candidates = []
        for c in self.substantive():
            candidates.append(
                {
                    "paragraph_id": c.paragraph_id,
                    "kind": c.kind,
                    "candidate_types": classify_change(c),
                    "text_snippet": (c.new_text or c.old_text)[:200],
                }
            )
        return candidates


def split_paragraphs(text: str) -> list[str]:
    """Split rule text into paragraphs on blank lines or rule numbering."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    return paras


def paragraph_id(para: str) -> str | None:
    """Extract a stable paragraph id like '(a)', '(1)', 'Sec. 123.4'."""
    m = re.match(r"^\(\s*([a-z0-9]+)\s*\)", para)
    if m:
        return f"({m.group(1)})"
    m = re.match(r"^(?:Sec\.|Section)\s+([\d.]+)", para, re.I)
    if m:
        return f"sec-{m.group(1)}"
    return None


def align_paragraphs(old_text: str, new_text: str) -> RuleDiff:
    old_paras = split_paragraphs(old_text)
    new_paras = split_paragraphs(new_text)

    sm = difflib.SequenceMatcher(a=old_paras, b=new_paras, autojunk=False)
    changes: list[ParagraphChange] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            for para in new_paras[j1:j2]:
                changes.append(ParagraphChange("add", paragraph_id(para), new_text=para))
        elif tag == "delete":
            for para in old_paras[i1:i2]:
                changes.append(ParagraphChange("delete", paragraph_id(para), old_text=para))
        else:  # replace
            for old_p, new_p in zip(old_paras[i1:i2], new_paras[j1:j2]):
                if _norm(old_p) == _norm(new_p):
                    continue  # formatting-only
                changes.append(
                    ParagraphChange("change", paragraph_id(new_p) or paragraph_id(old_p), old_text=old_p, new_text=new_p)
                )
            # leftover unmatched
            for para in old_paras[i1 + len(new_paras[j1:j2]):]:
                changes.append(ParagraphChange("delete", paragraph_id(para), old_text=para))
            for para in new_paras[j1 + len(old_paras[i1:i2]):]:
                changes.append(ParagraphChange("add", paragraph_id(para), new_text=para))

    # SequenceMatcher can misalign identical paragraphs as delete+add pairs
    # (e.g. when one paragraph in the middle changed); cancel such pairs.
    deletes = [c for c in changes if c.kind == "delete"]
    adds = [c for c in changes if c.kind == "add"]
    for d_chg in deletes:
        for a_chg in adds:
            if (
                a_chg in changes
                and d_chg in changes
                and _norm(d_chg.old_text) == _norm(a_chg.new_text)
                and paragraph_id(d_chg.old_text) == paragraph_id(a_chg.new_text)
            ):
                changes.remove(d_chg)
                changes.remove(a_chg)
                break

    return RuleDiff(old_text, new_text, changes)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower().strip(".,;:")


def is_technical_change(change: ParagraphChange) -> bool:
    """Filter technical changes: dates, numbering, citations, formatting."""
    text = f"{change.old_text} {change.new_text}"
    return any(p.search(text) for p in TECHNICAL_PATTERNS)


def classify_change(change: ParagraphChange) -> list[str]:
    """Rule Change Type candidates (agent picks materiality later)."""
    text = (change.new_text or change.old_text).lower()
    candidates: list[str] = []

    if any(k in text for k in ("percent", "threshold", "minimum", "maximum", "limit", "amount", "$")):
        candidates.append("threshold_change")
    if any(k in text for k in ("shall", "must", "prohibited", "required", "require", "shall not")):
        candidates.append("policy_change")
    if any(k in text for k in ("applic", "scope", "coverage", "applies to", "entity", "person")):
        candidates.append("scope_change")
    if any(k in text for k in ("report", "record", "disclos", "notice", "submit", "file")):
        candidates.append("procedure_change")
    if any(k in text for k in ("schedule", "appendix", "table")):
        candidates.append("schedule_change")
    if any(k in text for k in ("definition", "means")):
        candidates.append("definition_change")
    if not candidates:
        candidates.append("unclassified")

    return candidates
