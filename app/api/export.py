from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.common import resolve_scope_key
from app.api.rankings import SortField
from app.database import get_db
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api", tags=["export"])


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get("/export.csv")
def export_csv(
    request: Request,
    period: Literal["current", "7d", "30d"] = "current",
    scope: Literal["global", "category"] = "global",
    category_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=200),
    sort: SortField = "rank",
    limit: int = Query(default=50, ge=1, le=50),
    session: Session = Depends(get_db),
) -> Response:
    scope_key = resolve_scope_key(session, scope, category_id)
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    result = service.filtered_rankings(
        period=period,
        scope_key=scope_key,
        sort_type="best_selling",
        q=q,
        sort=sort,
        limit=limit,
        offset=0,
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "رتبه مشاهده‌شده",
            "عنوان محصول",
            "قیمت (تومان)",
            "تخفیف (درصد)",
            "امتیاز",
            "تعداد امتیاز",
            "تغییر رتبه",
            "تعداد مشاهده",
            "نرخ حضور (درصد)",
            "آخرین مشاهده",
            "پیوند محصول",
            "شناسه دیجی‌کالا",
            "مبنای داده",
        ]
    )
    for item in result["items"]:
        writer.writerow(
            [
                item.get("current_rank"),
                _excel_safe(item.get("title") or ""),
                item.get("price_toman"),
                item.get("discount_percent"),
                item.get("rating_stars"),
                item.get("rating_count"),
                item.get("rank_change"),
                item.get("observation_count"),
                item.get("presence_rate"),
                item.get("last_observed").isoformat() if item.get("last_observed") else "",
                _excel_safe(item.get("url") or ""),
                _excel_safe(item.get("external_id") or ""),
                result["data_basis"],
            ]
        )
    content = "\ufeff" + output.getvalue()
    headers = {
        "Content-Disposition": f'attachment; filename="digiscope-{period}-{scope}.csv"',
        "X-DigiScope-Data-Basis": result["data_basis"],
    }
    coverage = result.get("coverage")
    if coverage:
        headers["X-DigiScope-Coverage-Percent"] = str(coverage["coverage_percent"])
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)
