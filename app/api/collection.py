from __future__ import annotations

import hmac
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import (
    CollectionStatusResponse,
    ManualCollectionRequest,
    ManualCollectionResponse,
)
from app.services.analytics_service import AnalyticsService
from app.services.collection_service import CollectionAlreadyRunning, CollectionConfigurationError

router = APIRouter(prefix="/api/collection", tags=["collection"])


@router.get("/status", response_model=CollectionStatusResponse)
def collection_status(
    request: Request,
    session: Session = Depends(get_db),
) -> dict:
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    return service.collection_status()


@router.post("/run", response_model=ManualCollectionResponse)
async def run_collection(
    body: ManualCollectionRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    settings = request.app.state.settings
    configured_token = settings.admin_token_value
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="manual collection is disabled until ADMIN_TOKEN is configured",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, configured_token):
        raise HTTPException(status_code=401, detail="invalid administrative token")

    limit = body.limit or settings.default_ranking_limit
    if limit > settings.max_ranking_limit:
        raise HTTPException(
            status_code=422,
            detail=f"limit exceeds configured maximum {settings.max_ranking_limit}",
        )
    if not body.include_global and not body.category_ids:
        raise HTTPException(status_code=422, detail="select global or at least one category scope")

    collection_service = request.app.state.collection_service
    scopes = []
    if body.include_global:
        collection_service.ensure_default_scope()
        scopes.extend(
            scope
            for scope in collection_service.configured_scopes(enabled_only=False)
            if scope.scope_key == "global"
        )
    try:
        scopes.extend(
            collection_service.scope_for_category(category_id) for category_id in body.category_ids
        )
    except CollectionConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Authenticated and validated endpoint, plus a small process-local burst guard.
    # Cross-process overlap is prevented by the service's per-scope file lock.
    now = time.monotonic()
    last = getattr(request.app.state, "manual_collection_last_at", 0.0)
    if now - last < 2.0:
        raise HTTPException(
            status_code=429,
            detail="manual collection was triggered too recently",
            headers={"Retry-After": "2"},
        )
    request.app.state.manual_collection_last_at = now

    outcomes = []
    for scope in scopes:
        try:
            outcome = await collection_service.run_scope(
                scope,
                limit=limit,
                include_price_history=body.include_price_history,
            )
        except CollectionAlreadyRunning as exc:
            outcomes.append(
                {
                    "run_id": 0,
                    "scope_key": scope.scope_key,
                    "status": "skipped",
                    "items_fetched": 0,
                    "items_saved": 0,
                    "warnings": [],
                    "error": str(exc),
                }
            )
            continue
        outcomes.append(asdict(outcome))
    return {"outcomes": outcomes}
