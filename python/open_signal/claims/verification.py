"""Claim verification checks (spec §175, OS-024).

Eight gates a claim must pass before it may enter the Composer:
source, citation, number, date, rights, claim type, component fields,
prohibited language. Any failure blocks the claim (status rejected).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

ALLOWED_CLAIM_TYPES = {
    "derived_observation",
    "agent_observation",
    "rule_change_observation",
    "research_observation",
}

PROHIBITED_PATTERNS = [
    re.compile(r"建议.{0,6}(买入|卖出|持有|加仓|减仓|做多|做空)"),
    re.compile(r"(买入|卖出|做多|做空).{0,6}(建议|推荐)"),
    re.compile(r"(收益率|年化).{0,10}(预测|预期|将达到)"),
    re.compile(r"(恐慌|贪婪|信心不足|情绪低落|情绪高涨|恐慌性抛售|追涨)"),
    re.compile(r"(交易者|投资者|市场参与者).{0,10}(认为|预期|害怕|期待|担忧)"),
]

PROHIBITED_HIT_RATE = 0.8  # claims with >= this ratio of sentences flagged fail


class VerificationResult:
    def __init__(self, claim_id: str, checks: dict[str, dict[str, Any]]) -> None:
        self.claim_id = claim_id
        self.checks = checks

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks.values())

    def to_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "passed": self.passed, "checks": self.checks}


class ClaimVerifier:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ verify
    def verify(self, claim_id: str, render_candidate: dict[str, Any] | None = None) -> VerificationResult:
        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT claim_type, public_statement, structured_proposition, "
                    "confidence, evidence_bundle_id, issued_at, status "
                    "FROM claims WHERE id = :id"
                ),
                {"id": claim_id},
            ).fetchone()
        if claim is None:
            raise KeyError(f"claim {claim_id} not found")

        checks = {
            "source": self.check_source(claim_id, claim[4]),
            "citation": self.check_citation(claim[3], claim[2]),
            "number": self.check_number(claim[2], claim[3]),
            "date": self.check_date(claim[5]),
            "rights": self.check_rights(claim_id, claim[4]),
            "claim_type": self.check_claim_type(claim[0]),
            "component_fields": self.check_component_fields(render_candidate),
            "prohibited_language": self.check_prohibited_language(claim[1]),
        }
        return VerificationResult(claim_id, checks)

    # ------------------------------------------------------------------ gates
    def check_source(self, claim_id: str, evidence_bundle_id: str | None) -> dict[str, Any]:
        if evidence_bundle_id is None:
            return {"passed": False, "detail": "no evidence bundle"}
        with self.engine.connect() as conn:
            coverage = conn.execute(
                text("SELECT source_coverage FROM evidence_bundles WHERE id = :id"),
                {"id": evidence_bundle_id},
            ).fetchone()
        if coverage is None:
            return {"passed": False, "detail": "evidence bundle missing"}
        return {"passed": True, "detail": "evidence bundle present"}

    def check_citation(self, confidence: Any, proposition: dict[str, Any] | None) -> dict[str, Any]:
        prop = proposition or {}
        if prop.get("subject_ids"):
            return {"passed": True, "detail": f"{len(prop['subject_ids'])} subject(s) cited"}
        return {"passed": False, "detail": "no subject_ids in proposition"}

    def check_number(self, proposition: dict[str, Any] | None, confidence: Any) -> dict[str, Any]:
        issues = []
        if confidence is not None:
            c = float(confidence)
            if not (0.0 <= c <= 1.0):
                issues.append(f"confidence {c} out of [0,1]")
        prop = proposition or {}
        if "value" in prop and prop["value"] is not None:
            v = prop["value"]
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                issues.append("non-finite value")
            elif not isinstance(v, (int, float, bool)):
                issues.append(f"value is not numeric ({type(v).__name__})")
        return {"passed": not issues, "detail": "; ".join(issues) or "numbers valid"}

    def check_date(self, issued_at: Any) -> dict[str, Any]:
        if issued_at is None:
            return {"passed": False, "detail": "missing issued_at"}
        now = datetime.now(timezone.utc)
        if issued_at > now + __import__("datetime").timedelta(minutes=5):
            return {"passed": False, "detail": "issued_at in the future"}
        return {"passed": True, "detail": "date valid"}

    def check_rights(self, claim_id: str, evidence_bundle_id: str | None) -> dict[str, Any]:
        # Evidence whose source explicitly denies display must not pass.
        # First version: check the evidence bundle coverage for a deny flag;
        # unknown rights default to internal-only (allowed for the ledger).
        if evidence_bundle_id is None:
            return {"passed": False, "detail": "no evidence for rights check"}
        with self.engine.connect() as conn:
            coverage = conn.execute(
                text("SELECT source_coverage FROM evidence_bundles WHERE id = :id"),
                {"id": evidence_bundle_id},
            ).fetchone()
        if coverage is None:
            return {"passed": False, "detail": "evidence bundle missing"}
        if isinstance(coverage[0], dict) and coverage[0].get("rights_deny_display") is True:
            return {"passed": False, "detail": "source rights deny display"}
        return {"passed": True, "detail": "rights ok (internal display)"}

    def check_claim_type(self, claim_type: str) -> dict[str, Any]:
        if claim_type in ALLOWED_CLAIM_TYPES:
            return {"passed": True, "detail": claim_type}
        return {"passed": False, "detail": f"disallowed claim type {claim_type!r}"}

    def check_component_fields(self, render_candidate: dict[str, Any] | None) -> dict[str, Any]:
        if render_candidate is None:
            return {"passed": True, "detail": "no render candidate (not composer-bound)"}
        required = ("component_id", "headline", "display_fields")
        missing = [k for k in required if k not in render_candidate]
        if missing:
            return {"passed": False, "detail": f"missing {missing}"}
        return {"passed": True, "detail": "component fields complete"}

    def check_prohibited_language(self, statement: str) -> dict[str, Any]:
        hits = [p.pattern for p in PROHIBITED_PATTERNS if p.search(statement or "")]
        if hits:
            return {"passed": False, "detail": f"prohibited language: {hits}"}
        return {"passed": True, "detail": "clean"}

    # ------------------------------------------------------------------ gate
    def gate_for_composer(self, claim_id: str, render_candidate: dict[str, Any] | None = None) -> bool:
        """Composer gate: only verified claims may proceed."""
        result = self.verify(claim_id, render_candidate)
        new_status = "verified" if result.passed else "rejected"
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE claims SET status = :status WHERE id = :id"),
                {"status": new_status, "id": claim_id},
            )
        return result.passed
