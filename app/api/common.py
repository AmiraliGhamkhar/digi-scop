from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Category
from app.services.analytics_service import AnalyticsService


def resolve_scope_key(session: Session, scope: str, category_id: int | None) -> str:
    if scope == "global":
        if category_id is not None:
            raise HTTPException(
                status_code=422, detail="category_id is only valid for category scope"
            )
        return "global"
    if category_id is None:
        raise HTTPException(status_code=422, detail="category_id is required for category scope")
    if session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="category not found")
    return AnalyticsService.scope_key("category", category_id)
