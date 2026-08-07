"""Open Signal read-only public API (OS-030).

FastAPI app exposing claim pages and editions. Read-only by design: no
mutation endpoints. Run with: uvicorn apps.api.main:app
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from open_signal.api.presenters import ClaimPagePresenter
from open_signal.composer.edition_writer import EditionWriter

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


@app.get("/api/editions/{edition_id}")
def get_edition(edition_id: str) -> dict:
    writer = EditionWriter(_engine())
    payload = writer.edition_json(edition_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="edition not found")
    return payload
