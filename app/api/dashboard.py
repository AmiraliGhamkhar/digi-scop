from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import DashboardResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(request: Request, session: Session = Depends(get_db)) -> dict:
    service = AnalyticsService(
        session, default_interval_minutes=request.app.state.settings.collection_interval_minutes
    )
    return service.dashboard()
