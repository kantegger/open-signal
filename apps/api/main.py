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
    """Return the latest published edition for the frontend."""
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
    return {
        "id": str(row[0]),
        "edition_date": str(row[1]),
        "edition_payload": row[2] if isinstance(row[2], dict) else {},
        "sections": row[3] if isinstance(row[3], list) else [],
        "claim_ids": [str(c) for c in (row[4] if isinstance(row[4], list) else [])],
        "generated_at": row[5].isoformat(),
    }


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
