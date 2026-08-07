"""Claims ledger (spec §171, OS-023).

Uniform append-only ledger over claims / claim_versions / claim_events:
- create_claim writes claim + first version + claim.created event
- update_claim writes a new version (previous_version_id) + claim.updated
- transition_status writes claim.status_changed
- every event carries previous_event_hash / current_event_hash (SHA-256
  chain); verify_hash_chain recomputes the chain
- get_claim_page is the read API (claim + versions + events)
- append-only is enforced at the DB layer by the prevent_mutation trigger
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text


class ClaimsLedger:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ---------------------------------------------------------------- create
    def create_claim(
        self,
        *,
        desk_id: str,
        section_id: str,
        capability_id: str,
        claim_type: str,
        public_statement: str,
        structured_proposition: dict[str, Any],
        confidence: float,
        evidence_bundle_id: str,
        agent_lineage_id: str,
        model_version: str,
        charter_version: str,
        run_id: str | None,
        actor_type: str = "system",
        actor_id: str = "ledger",
        institution_id: str = "open-signal",
        epistemic_status: str = "derived",
        status: str = "draft",
    ) -> dict[str, Any]:
        """Create claim + version 1 + claim.created event (chain root)."""
        with self.engine.begin() as conn:
            claim_row = conn.execute(
                text(
                    """
                    INSERT INTO claims
                      (institution_id, desk_id, agent_lineage_id, model_version,
                       charter_version, run_id, section_id, capability_id,
                       claim_type, public_statement, structured_proposition,
                       confidence, confidence_label, epistemic_status,
                       evidence_bundle_id, evidence_snapshot_hash,
                       issued_at, status)
                    VALUES
                      (:inst, :desk, :lineage, :model, :charter, :run,
                       :section, :capability, :type, :statement, CAST(:prop AS jsonb),
                       :confidence, :label, :epistemic, :eb, :hash, now(), :status)
                    RETURNING id
                    """
                ),
                {
                    "inst": institution_id,
                    "desk": desk_id,
                    "lineage": agent_lineage_id,
                    "model": model_version,
                    "charter": charter_version,
                    "run": run_id,
                    "section": section_id,
                    "capability": capability_id,
                    "type": claim_type,
                    "statement": public_statement,
                    "prop": json.dumps(structured_proposition),
                    "confidence": confidence,
                    "label": _confidence_label(confidence),
                    "epistemic": epistemic_status,
                    "eb": evidence_bundle_id,
                    "hash": _sha256(public_statement + json.dumps(structured_proposition, sort_keys=True)),
                    "status": status,
                },
            ).fetchone()
            claim_id = str(claim_row[0])

            version_id = self._append_version(
                conn, claim_id, version_number=1, public_statement=public_statement,
                structured_proposition=structured_proposition, confidence=confidence,
                evidence_bundle_id=evidence_bundle_id, change_type="initial",
                change_reason="claim created", previous_version_id=None, run_id=run_id,
            )
            event_hash = self._append_event(
                conn, claim_id, event_type="claim.created",
                payload={"status": status, "version_number": 1}, actor_type=actor_type,
                actor_id=actor_id, previous_hash=None,
            )
            conn.execute(
                text("UPDATE claims SET current_version_id = :v WHERE id = :id"),
                {"v": version_id, "id": claim_id},
            )

        return {"claim_id": claim_id, "version_id": version_id, "event_hash": event_hash}

    # ---------------------------------------------------------------- update
    def update_claim(
        self,
        *,
        claim_id: str,
        public_statement: str,
        structured_proposition: dict[str, Any],
        confidence: float,
        evidence_bundle_id: str,
        change_reason: str,
        actor_type: str,
        actor_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a new version + claim.updated event. Claim row is NOT
        mutated (versions are authoritative); current_version_id advances."""
        with self.engine.begin() as conn:
            claim = conn.execute(
                text("SELECT status, current_version_id FROM claims WHERE id = :id"),
                {"id": claim_id},
            ).fetchone()
            if claim is None:
                raise KeyError(f"claim {claim_id} not found")

            prev_version = conn.execute(
                text("SELECT version_number FROM claim_versions WHERE id = :id"),
                {"id": claim[1]},
            ).fetchone()
            next_number = (prev_version[0] + 1) if prev_version else 2

            version_id = self._append_version(
                conn, claim_id, version_number=next_number, public_statement=public_statement,
                structured_proposition=structured_proposition, confidence=confidence,
                evidence_bundle_id=evidence_bundle_id, change_type="update",
                change_reason=change_reason, previous_version_id=claim[1], run_id=run_id,
            )
            event_hash = self._append_event(
                conn, claim_id, event_type="claim.updated",
                payload={"version_number": next_number, "reason": change_reason},
                actor_type=actor_type, actor_id=actor_id, previous_hash=None,
            )
            conn.execute(
                text("UPDATE claims SET current_version_id = :v WHERE id = :id"),
                {"v": version_id, "id": claim_id},
            )
        return {"version_id": version_id, "version_number": next_number, "event_hash": event_hash}

    # --------------------------------------------------------------- transition
    def transition_status(
        self, *, claim_id: str, new_status: str, reason: str, actor_type: str, actor_id: str
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            current = conn.execute(
                text("SELECT status FROM claims WHERE id = :id"), {"id": claim_id}
            ).fetchone()
            if current is None:
                raise KeyError(f"claim {claim_id} not found")
            conn.execute(
                text("UPDATE claims SET status = :status WHERE id = :id"),
                {"status": new_status, "id": claim_id},
            )
            event_hash = self._append_event(
                conn, claim_id, event_type="claim.status_changed",
                payload={"from": current[0], "to": new_status, "reason": reason},
                actor_type=actor_type, actor_id=actor_id, previous_hash=None,
            )
        return {"event_hash": event_hash, "from": current[0], "to": new_status}

    # ------------------------------------------------------------------ events
    def _append_event(
        self,
        conn: Any,
        claim_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        actor_type: str,
        actor_id: str,
        previous_hash: str | None,
    ) -> str:
        if previous_hash is None:
            prev = conn.execute(
                text(
                    "SELECT current_event_hash FROM claim_events "
                    "WHERE claim_id = :id ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"id": claim_id},
            ).fetchone()
            previous_hash = prev[0] if prev else None

        body = json.dumps(
            {"claim_id": claim_id, "event_type": event_type, "payload": payload},
            ensure_ascii=False, sort_keys=True, default=str,
        )
        current_hash = hashlib.sha256(
            f"{previous_hash or ''}|{body}".encode()
        ).hexdigest()

        row = conn.execute(
            text(
                """
                INSERT INTO claim_events
                  (claim_id, event_type, payload, actor_type, actor_id,
                   previous_event_hash, current_event_hash)
                VALUES (:id, :type, CAST(:payload AS jsonb), :actor_type, :actor_id,
                        :prev, :hash)
                RETURNING current_event_hash
                """
            ),
            {
                "id": claim_id,
                "type": event_type,
                "payload": json.dumps(payload),
                "actor_type": actor_type,
                "actor_id": actor_id,
                "prev": previous_hash,
                "hash": current_hash,
            },
        ).fetchone()
        return str(row[0])

    def _append_version(
        self,
        conn: Any,
        claim_id: str,
        *,
        version_number: int,
        public_statement: str,
        structured_proposition: dict[str, Any],
        confidence: float,
        evidence_bundle_id: str,
        change_type: str,
        change_reason: str,
        previous_version_id: str | None,
        run_id: str | None,
    ) -> str:
        row = conn.execute(
            text(
                """
                INSERT INTO claim_versions
                  (claim_id, version_number, public_statement, structured_proposition,
                   confidence, evidence_bundle_id, change_type, change_reason,
                   previous_version_id, created_by_run_id)
                VALUES (:id, :num, :statement, CAST(:prop AS jsonb), :confidence,
                        :eb, :change_type, :reason, :prev, :run)
                RETURNING id
                """
            ),
            {
                "id": claim_id,
                "num": version_number,
                "statement": public_statement,
                "prop": json.dumps(structured_proposition),
                "confidence": confidence,
                "eb": evidence_bundle_id,
                "change_type": change_type,
                "reason": change_reason,
                "prev": previous_version_id,
                "run": run_id,
            },
        ).fetchone()
        return str(row[0])

    # ------------------------------------------------------------- hash chain
    def verify_hash_chain(self, claim_id: str) -> bool:
        """Recompute the event hash chain; False if any link is broken."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT previous_event_hash, current_event_hash, event_type, payload "
                    "FROM claim_events WHERE claim_id = :id ORDER BY occurred_at ASC"
                ),
                {"id": claim_id},
            ).fetchall()

        previous = None
        for prev_hash, cur_hash, event_type, payload in rows:
            body = json.dumps(
                {"claim_id": claim_id, "event_type": event_type, "payload": payload},
                ensure_ascii=False, sort_keys=True, default=str,
            )
            expected = hashlib.sha256(f"{previous or ''}|{body}".encode()).hexdigest()
            if prev_hash != previous:
                return False
            if cur_hash != expected:
                return False
            previous = cur_hash
        return True

    # ------------------------------------------------------------ read API
    def get_claim_page(self, claim_id: str) -> dict[str, Any] | None:
        """Claim page read API: claim + versions + events."""
        with self.engine.connect() as conn:
            claim = conn.execute(
                text(
                    "SELECT id, claim_type, public_statement, structured_proposition, "
                    "confidence, status, desk_id, capability_id, issued_at, current_version_id "
                    "FROM claims WHERE id = :id"
                ),
                {"id": claim_id},
            ).fetchone()
            if claim is None:
                return None
            versions = conn.execute(
                text(
                    "SELECT version_number, public_statement, change_type, change_reason, "
                    "confidence, created_at FROM claim_versions WHERE claim_id = :id "
                    "ORDER BY version_number ASC"
                ),
                {"id": claim_id},
            ).fetchall()
            events = conn.execute(
                text(
                    "SELECT event_type, payload, actor_type, actor_id, occurred_at, "
                    "current_event_hash FROM claim_events WHERE claim_id = :id "
                    "ORDER BY occurred_at ASC"
                ),
                {"id": claim_id},
            ).fetchall()

        return {
            "claim": {
                "id": str(claim[0]),
                "claim_type": claim[1],
                "public_statement": claim[2],
                "structured_proposition": claim[3],
                "confidence": float(claim[4]) if claim[4] is not None else None,
                "status": claim[5],
                "desk_id": claim[6],
                "capability_id": claim[7],
                "issued_at": claim[8].isoformat(),
                "current_version_id": str(claim[9]) if claim[9] else None,
            },
            "versions": [
                {
                    "version_number": v[0],
                    "public_statement": v[1],
                    "change_type": v[2],
                    "change_reason": v[3],
                    "confidence": float(v[4]) if v[4] is not None else None,
                    "created_at": v[5].isoformat(),
                }
                for v in versions
            ],
            "events": [
                {
                    "event_type": e[0],
                    "payload": e[1],
                    "actor_type": e[2],
                    "actor_id": e[3],
                    "occurred_at": e[4].isoformat(),
                    "current_event_hash": e[5],
                }
                for e in events
            ],
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"
