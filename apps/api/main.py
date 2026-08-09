"""Open Signal read-only public API (OS-030).

FastAPI app exposing claim pages and editions. Read-only by design: no
mutation endpoints. Run with: uvicorn apps.api.main:app
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from open_signal.api.database import get_engine
from open_signal.api.editions import FrontPagePresenter
from open_signal.api.ops import OpsPresenter
from open_signal.api.presenters import ClaimPagePresenter
from open_signal.api.topics import SeoIndexPresenter, TopicPagePresenter
from open_signal.composer.edition_writer import EditionWriter
from open_signal.security import hardening

app = FastAPI(title="Open Signal Public API", version="0.1.0")
ops_bearer = HTTPBearer(auto_error=False, scheme_name="OpsBearer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # public read-only
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _engine():
    return get_engine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str, locale: str = "en") -> dict:
    presenter = ClaimPagePresenter(_engine())
    page = presenter.build(claim_id, locale=locale)
    if page is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return page


@app.get("/api/editions/latest")
def get_latest_edition(locale: str = "en") -> dict:
    """Compatibility endpoint; new clients should consume Render Plans below."""
    page = FrontPagePresenter(_engine()).legacy_latest(locale=locale)
    if page is None:
        raise HTTPException(status_code=404, detail="no editions yet")
    return page


@app.get("/api/front-page/current", response_model=None)
def get_current_front_page(
    response: Response,
    locale: str = "en",
    if_none_match: str | None = Header(default=None),
) -> dict | Response:
    page = FrontPagePresenter(_engine()).build(locale=locale)
    if page is None:
        raise HTTPException(status_code=404, detail="no editions yet")
    etag = f'"{page["snapshot"]["id"]}:{locale}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=120"
    return page


@app.get("/api/editions/{edition_id}")
def get_edition(edition_id: str) -> dict:
    writer = EditionWriter(_engine())
    payload = writer.edition_json(edition_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="edition not found")
    return payload


@app.get("/api/editions/{edition_id}/front-page")
def get_edition_front_page(
    edition_id: UUID,
    response: Response,
    locale: str = "en",
) -> dict:
    page = FrontPagePresenter(_engine()).build(
        locale=locale,
        edition_id=str(edition_id),
    )
    if page is None:
        raise HTTPException(status_code=404, detail="edition not found")
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return page


@app.get("/api/topics/{expectation_id}")
def get_topic(expectation_id: UUID, response: Response) -> dict:
    page = TopicPagePresenter(_engine()).build(str(expectation_id))
    if page is None:
        raise HTTPException(status_code=404, detail="topic not found")
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return page


@app.get("/api/seo-index")
def get_seo_index(response: Response, limit: int = 1000) -> dict:
    response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=3600"
    return SeoIndexPresenter(_engine()).build(limit=limit)


# --------------------------------------------------------- operations console
def require_ops(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(ops_bearer),
    ] = None,
    x_ops_token: Annotated[str | None, Header()] = None,
) -> None:
    authorization = (
        f"{credentials.scheme} {credentials.credentials}" if credentials else None
    )
    if not hardening.require_ops_token(authorization, x_ops_token=x_ops_token):
        raise HTTPException(
            status_code=401,
            detail="ops authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
