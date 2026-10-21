from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.common import resolve_scope_key
from app.database import get_db
from app.schemas.api import RankingListResponse, TrendResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api", tags=["rankings"])

SortField = Literal[
    "rank",
    "-rank",
    "rank_improvement",
    "-rank_improvement",
    "price",
    "-price",
    "rating",
    "-rating",
    "observations",
    "-observations",
    "last_observed",
    "-last_observed",
    "trend",
    "-trend",
]


@router.get("/rankings", response_model=RankingListResponse)
def rankings(
    request: Request,
    period: Literal["current", "7d", "30d"] = "current",
    scope: Literal["global", "category"] = "global",
    category_id: int | None = Query(default=None, ge=1),
    ranking_method: Literal["best_selling"] = "best_selling",
    q: str | None = Query(default=None, max_length=200),
    sort: SortField = "rank",
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10_000),
    session: Session = Depends(get_db),
) -> dict:
    scope_key = resolve_scope_key(session, scope, category_id)
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    return service.filtered_rankings(
        period=period,
        scope_key=scope_key,
        sort_type=ranking_method,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/market/trends", response_model=TrendResponse)
def trends(
    request: Request,
    period: Literal["7d", "30d"] = "7d",
    scope: Literal["global", "category"] = "global",
    category_id: int | None = Query(default=None, ge=1),
    ranking_method: Literal["best_selling"] = "best_selling",
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_db),
) -> dict:
    scope_key = resolve_scope_key(session, scope, category_id)
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    return service.trends(
        days=7 if period == "7d" else 30,
        scope_key=scope_key,
        sort_type=ranking_method,
        limit=limit,
    )
