"""DigiScope FastAPI application and Persian RTL dashboard."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.api import categories, collection, dashboard, export, products, rankings
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory, database_is_ready
from app.logging_config import configure_logging
from app.mcp.adapter import MarketDataAdapter
from app.mcp.factory import build_adapter
from app.schemas.api import HealthResponse
from app.services.collection_service import CollectionService

VERSION = "0.1.0"
BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    adapter: MarketDataAdapter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    database_engine = engine or create_database_engine(settings.database_url)
    session_factory = create_session_factory(database_engine)
    market_adapter = adapter or build_adapter(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _schema_ready(database_engine):
            app.state.collection_service.ensure_default_scope()
        else:
            logger.warning(
                "Database schema is not initialized; run alembic upgrade head",
                extra={"event": "database_schema_missing"},
            )
        yield
        await market_adapter.close()
        database_engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=VERSION,
        description=(
            "Coverage-aware Digikala ranking observations. Rankings are observed positions, "
            "not sales quantities."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings
    app.state.engine = database_engine
    app.state.session_factory = session_factory
    app.state.adapter = market_adapter
    app.state.collection_service = CollectionService(session_factory, market_adapter, settings)
    app.state.manual_collection_last_at = 0.0

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error",
                extra={
                    "event": "request_error",
                    "path": request.url.path,
                    "request_id": request_id,
                },
            )
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "font-src 'self'; img-src 'self' https: data:; connect-src 'self'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
        logger.info(
            "HTTP request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "request_id": request_id,
            },
        )
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database operation failed", extra={"event": "database_error"})
        return JSONResponse(status_code=503, content={"detail": "database operation failed"})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"app_name": settings.app_name, "version": VERSION},
        )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> dict:
        ready = database_is_ready(database_engine) and _schema_ready(database_engine)
        return {
            "status": "ok" if ready else "degraded",
            "database": "ready" if ready else "unavailable",
            "version": VERSION,
            "timestamp": datetime.now(UTC),
        }

    @app.get("/ready", response_model=HealthResponse, tags=["system"])
    def readiness() -> JSONResponse | dict:
        ready = database_is_ready(database_engine) and _schema_ready(database_engine)
        payload = {
            "status": "ok" if ready else "degraded",
            "database": "ready" if ready else "unavailable",
            "version": VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    app.include_router(dashboard.router)
    app.include_router(categories.router)
    app.include_router(products.router)
    app.include_router(rankings.router)
    app.include_router(collection.router)
    app.include_router(export.router)
    return app


def _schema_ready(engine: Engine) -> bool:
    try:
        return inspect(engine).has_table("products") and inspect(engine).has_table(
            "collection_runs"
        )
    except SQLAlchemyError:
        return False


app = create_app()
