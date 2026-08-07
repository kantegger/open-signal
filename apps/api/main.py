"""Open Signal read-only public API (OS-030).

FastAPI app exposing claim pages and editions. Read-only by design: no
mutation endpoints. Run with: uvicorn apps.api.main:app
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from open_signal.api.ops import OpsPresenter
from open_signal.api.presenters import ClaimPagePresenter
from open_signal.composer.edition_writer import EditionWriter
from open_signal.security import hardening

app = FastAPI(title="Open Signal Public API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # public read-only
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _engine():
    from sqlalchemy import create_engine

    return create_engine(os.environ["OPEN_SIGNAL_DATABASE_URL"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str) -> dict:
    presenter = ClaimPagePresenter(_engine())
    page = presenter.build(claim_id)
    if page is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return page


@app.get("/api/editions/latest")
def get_latest_edition() -> dict:
    """Return the latest published edition with claim card summaries."""
    from sqlalchemy import text

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, edition_date, edition_payload, included_section_ids, "
                "included_claim_ids, generated_at FROM daily_editions "
                "WHERE status = 'published' ORDER BY generated_at DESC LIMIT 1"
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no editions yet")

    claim_ids = [str(c) for c in (row[4] if isinstance(row[4], list) else [])]
    cards = _claim_cards(claim_ids)

    return {
        "id": str(row[0]),
        "edition_date": str(row[1]),
        "edition_payload": row[2] if isinstance(row[2], dict) else {},
        "sections": row[3] if isinstance(row[3], list) else [],
        "claim_ids": claim_ids,
        "generated_at": row[5].isoformat(),
        "cards": cards,
    }


def _claim_cards(claim_ids: list[str]) -> list[dict]:
    """Build card summaries for a list of claim IDs in a single query."""
    from sqlalchemy import text

    if not claim_ids:
        return []
    with _engine().connect() as conn:
        import uuid as _uuid

        rows = conn.execute(
            text(
                "SELECT c.id, c.public_statement, c.structured_proposition, c.confidence, "
                "c.confidence_label, c.status, c.desk_id, c.issued_at, "
                "c.section_id, c.capability_id, c.claim_type "
                "FROM claims c WHERE c.id = ANY(:ids) AND c.status = 'published'"
            ),
            {"ids": [_uuid.UUID(cid) for cid in claim_ids]},
        ).fetchall()
    cards = []
    for r in rows:
        prop = r[2] or {}
        en = prop.get("en", {}) if isinstance(prop, dict) else {}
        headline = en.get("headline", r[1]) or r[1]
        observation = en.get("observation", "")
        analysis = en.get("analysis", "")
        assessment = en.get("assessment", "")

        # derive trend from structured keys or analysis text
        trend = en.get("trend") or _derive_trend(analysis, en)
        # derive category tags from section + claim_type
        tags = [r[8].replace("-", " ").title(), r[10].replace("_", " ").title()]

        cards.append({
            "id": str(r[0]),
            "headline": headline[:120],
            "summary": (observation or analysis)[:140],
            "trend": trend,
            "probability": en.get("probability"),
            "confidence": float(r[3]) if r[3] is not None else None,
            "confidence_label": r[4],
            "source_label": r[6],
            "section": r[8],
            "tags": tags,
            "issued_at": r[7].isoformat() if r[7] else None,
        })
    return cards


def _derive_trend(analysis: str, en: dict) -> str | None:
    """Heuristic trend detection."""
    text = (analysis + " " + str(en)).lower()
    if any(w in text for w in ("increas", "up ", "ris", "surge", "higher", "bull")):
        return "up"
    if any(w in text for w in ("decreas", "down", "drop", "fall", "lower", "bear")):
        return "down"
    return "neutral"


@app.get("/api/editions/{edition_id}")
def get_edition(edition_id: str) -> dict:
    writer = EditionWriter(_engine())
    payload = writer.edition_json(edition_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="edition not found")
    return payload


# --------------------------------------------------------- operations console
def require_ops(x_ops_token: str | None = Header(default=None)) -> None:
    if not hardening.require_ops_token(x_ops_token):
        raise HTTPException(status_code=401, detail="ops authentication required")


@app.get("/api/ops/current-edition", dependencies=[Depends(require_ops)])
def ops_current_edition() -> dict:
    data = OpsPresenter(_engine()).current_edition()
    if data is None:
        raise HTTPException(status_code=404, detail="no editions yet")
    return data


@app.get("/api/ops/source-health", dependencies=[Depends(require_ops)])
def ops_source_health() -> list[dict]:
    return OpsPresenter(_engine()).source_health()


@app.get("/api/ops/job-queue", dependencies=[Depends(require_ops)])
def ops_job_queue() -> dict:
    return OpsPresenter(_engine()).job_queue()


@app.get("/api/ops/agent-runs", dependencies=[Depends(require_ops)])
def ops_agent_runs(limit: int = 20) -> list[dict]:
    return OpsPresenter(_engine()).agent_runs(limit=min(limit, 100))


@app.get("/api/ops/verification-failures", dependencies=[Depends(require_ops)])
def ops_verification_failures() -> list[dict]:
    return OpsPresenter(_engine()).verification_failures()


@app.get("/api/ops/daily-cost", dependencies=[Depends(require_ops)])
def ops_daily_cost(days: int = 14) -> list[dict]:
    return OpsPresenter(_engine()).daily_cost(days=min(days, 90))


@app.get("/api/ops/feature-flags", dependencies=[Depends(require_ops)])
def ops_feature_flags() -> list[dict]:
    return OpsPresenter(_engine()).feature_flags()


@app.get("/api/ops/claims-corrected", dependencies=[Depends(require_ops)])
def ops_claims_corrected() -> list[dict]:
    return OpsPresenter(_engine()).claims_corrected()
