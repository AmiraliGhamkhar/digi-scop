from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.common import resolve_scope_key
from app.api.rankings import SortField
from app.database import get_db
from app.schemas.api import ProductDetailResponse, RankingListResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products", response_model=RankingListResponse)
def products(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    category_id: int | None = Query(default=None, ge=1),
    period: Literal["current", "7d", "30d"] = "current",
    sort: SortField = "rank",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10_000),
    session: Session = Depends(get_db),
) -> dict:
    scope = "category" if category_id is not None else "global"
    scope_key = resolve_scope_key(session, scope, category_id)
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    return service.filtered_rankings(
        period=period,
        scope_key=scope_key,
        sort_type="best_selling",
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductDetailResponse)
def product_detail(
    product_id: int,
    request: Request,
    session: Session = Depends(get_db),
) -> dict:
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    result = service.product_detail(product_id)
    if result is None:
        raise HTTPException(status_code=404, detail="product not found")
    return result
