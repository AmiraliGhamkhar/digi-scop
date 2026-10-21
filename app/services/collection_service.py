"""Idempotent, scope-locked market data collection workflow."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import as_utc, utc_now
from app.mcp.adapter import MarketDataAdapter, PriceHistoryBatch
from app.mcp.normalizer import NormalizedRankingBatch
from app.models import (
    Category,
    CollectionRun,
    CollectionScope,
    CollectionStatus,
    Product,
    RankObservation,
    ScopeType,
    Snapshot,
)
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)


class CollectionAlreadyRunning(RuntimeError):
    pass


class CollectionConfigurationError(ValueError):
    pass


@dataclass(slots=True)
class ScopeSpec:
    scope_type: ScopeType
    scope_key: str
    sort_type: str = "best_selling"
    category_id: int | None = None
    category_external_id: str | None = None
    interval_minutes: int = 1440
    config_id: int | None = None


@dataclass(slots=True)
class CollectionOutcome:
    run_id: int
    scope_key: str
    status: str
    items_fetched: int
    items_saved: int
    warnings: list[str]
    error: str | None = None


class CollectionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        adapter: MarketDataAdapter,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.adapter = adapter
        self.settings = settings
        self.lock_dir = Path(settings.collection_lock_dir)

    def ensure_default_scope(self) -> CollectionScope:
        with self.session_factory.begin() as session:
            scope = session.scalar(
                select(CollectionScope).where(
                    CollectionScope.scope_key == "global",
                    CollectionScope.sort_type == "best_selling",
                )
            )
            if scope:
                return scope
            scope = CollectionScope(
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                category_id=None,
                sort_type="best_selling",
                enabled=True,
                interval_minutes=self.settings.collection_interval_minutes,
            )
            session.add(scope)
            session.flush()
            return scope

    def configured_scopes(self, *, enabled_only: bool = True) -> list[ScopeSpec]:
        with self.session_factory() as session:
            query = select(CollectionScope).order_by(CollectionScope.id)
            if enabled_only:
                query = query.where(CollectionScope.enabled.is_(True))
            records = session.scalars(query).all()
            result: list[ScopeSpec] = []
            for record in records:
                category = session.get(Category, record.category_id) if record.category_id else None
                result.append(
                    ScopeSpec(
                        scope_type=record.scope_type,
                        scope_key=record.scope_key,
                        sort_type=record.sort_type,
                        category_id=record.category_id,
                        category_external_id=category.external_id if category else None,
                        interval_minutes=record.interval_minutes,
                        config_id=record.id,
                    )
                )
            return result

    def scope_for_category(self, category_id: int) -> ScopeSpec:
        with self.session_factory() as session:
            category = session.get(Category, category_id)
            if not category:
                raise CollectionConfigurationError("unknown category")
            config = session.scalar(
                select(CollectionScope).where(
                    CollectionScope.category_id == category_id,
                    CollectionScope.sort_type == "best_selling",
                )
            )
            return ScopeSpec(
                scope_type=ScopeType.CATEGORY,
                scope_key=f"category:{category_id}",
                category_id=category.id,
                category_external_id=category.external_id,
                interval_minutes=(
                    config.interval_minutes if config else self.settings.collection_interval_minutes
                ),
                config_id=config.id if config else None,
            )

    async def run_configured(
        self,
        *,
        limit: int | None = None,
        include_price_history: bool = False,
    ) -> list[CollectionOutcome]:
        self.ensure_default_scope()
        outcomes: list[CollectionOutcome] = []
        for scope in self.configured_scopes():
            try:
                outcomes.append(
                    await self.run_scope(
                        scope,
                        limit=limit or self.settings.default_ranking_limit,
                        include_price_history=include_price_history,
                    )
                )
            except CollectionAlreadyRunning as exc:
                outcomes.append(
                    CollectionOutcome(
                        run_id=0,
                        scope_key=scope.scope_key,
                        status="skipped",
                        items_fetched=0,
                        items_saved=0,
                        warnings=[],
                        error=str(exc),
                    )
                )
        return outcomes

    async def run_scope(
        self,
        scope: ScopeSpec,
        *,
        limit: int,
        include_price_history: bool = False,
    ) -> CollectionOutcome:
        if not 1 <= limit <= self.settings.max_ranking_limit:
            raise CollectionConfigurationError(
                f"limit must be between 1 and {self.settings.max_ranking_limit}"
            )
        with self._scope_lock(scope.scope_key, scope.sort_type):
            run = self._create_run(scope, limit)
            started_monotonic = time.monotonic()
            logger.info(
                "Collection started",
                extra={
                    "event": "collection_start",
                    "run_id": run.id,
                    "scope": scope.scope_key,
                    "sort": scope.sort_type,
                    "limit": limit,
                },
            )
            try:
                batch = await self.adapter.fetch_ranking(
                    scope_type=scope.scope_type,
                    category_external_id=scope.category_external_id,
                    limit=limit,
                    sort_type=scope.sort_type,
                )
                saved, product_ids = self.persist_batch(run.id, scope, batch)
                warnings = list(batch.warnings)
                imported_points = 0
                if include_price_history:
                    history_limit = self.settings.price_history_products_per_run
                    if history_limit <= 0:
                        warnings.append(
                            "price history was requested but PRICE_HISTORY_PRODUCTS_PER_RUN is zero"
                        )
                    else:
                        for product_id in product_ids[:history_limit]:
                            try:
                                imported, history_warnings = await self.import_price_history(
                                    product_id, collection_run_id=run.id
                                )
                                imported_points += imported
                                for history_warning in history_warnings[:10]:
                                    warnings.append(
                                        f"price history product {product_id}: {history_warning}"
                                    )
                            except Exception as exc:  # noqa: BLE001 - isolate optional enrichment
                                safe = self._safe_error(exc)
                                warnings.append(f"price history product {product_id}: {safe}")
                                logger.warning(
                                    "Historical import failed",
                                    extra={
                                        "event": "historical_import_failure",
                                        "run_id": run.id,
                                        "product_id": product_id,
                                        "error_type": type(exc).__name__,
                                    },
                                )
                if not batch.products:
                    warnings.append("the ranking call returned no valid product observations")
                status = CollectionStatus.PARTIAL if warnings else CollectionStatus.SUCCESS
                duration_ms = round((time.monotonic() - started_monotonic) * 1000)
                # Upstream tools report their own card count as ``returned``
                # (with ``fetched`` as a tolerated alias). Warnings describe
                # skipped rows; they are not fetched items and never inflate
                # the count. When upstream reports nothing, the normalized
                # product count is the honest fallback.
                reported_fetched = next(
                    (
                        value
                        for key in ("returned", "fetched")
                        if isinstance(value := batch.metadata.get(key), (int, float))
                        and not isinstance(value, bool)
                        and value >= 0
                    ),
                    None,
                )
                fetched_count = (
                    int(reported_fetched) if reported_fetched is not None else len(batch.products)
                )
                metadata = {
                    **batch.metadata,
                    "warnings": warnings[:50],
                    "price_points_imported": imported_points,
                }
                self._finish_run(
                    run.id,
                    scope,
                    status=status,
                    items_fetched=fetched_count,
                    items_saved=saved,
                    duration_ms=duration_ms,
                    source_metadata=metadata,
                )
                logger.info(
                    "Collection finished",
                    extra={
                        "event": "collection_finish",
                        "run_id": run.id,
                        "scope": scope.scope_key,
                        "status": status.value,
                        "items_fetched": fetched_count,
                        "items_saved": saved,
                        "duration_ms": duration_ms,
                    },
                )
                return CollectionOutcome(
                    run_id=run.id,
                    scope_key=scope.scope_key,
                    status=status.value,
                    items_fetched=fetched_count,
                    items_saved=saved,
                    warnings=warnings,
                )
            except Exception as exc:
                duration_ms = round((time.monotonic() - started_monotonic) * 1000)
                safe_error = self._safe_error(exc)
                self._finish_run(
                    run.id,
                    scope,
                    status=CollectionStatus.FAILED,
                    items_fetched=0,
                    items_saved=0,
                    duration_ms=duration_ms,
                    error_message=safe_error,
                    source_metadata={"error_type": type(exc).__name__},
                )
                logger.exception(
                    "Collection failed",
                    extra={
                        "event": "collection_failure",
                        "run_id": run.id,
                        "scope": scope.scope_key,
                        "error_type": type(exc).__name__,
                    },
                )
                return CollectionOutcome(
                    run_id=run.id,
                    scope_key=scope.scope_key,
                    status=CollectionStatus.FAILED.value,
                    items_fetched=0,
                    items_saved=0,
                    warnings=[],
                    error=safe_error,
                )

    def persist_batch(
        self,
        run_id: int,
        scope: ScopeSpec,
        batch: NormalizedRankingBatch,
    ) -> tuple[int, list[int]]:
        """Persist one normalized ranking atomically; safe to repeat for a run."""

        with self.session_factory.begin() as session:
            run = session.get(CollectionRun, run_id)
            if not run:
                raise CollectionConfigurationError("collection run does not exist")
            observed_at = as_utc(run.started_at) or utc_now()
            # Two passes allow a child that precedes its parent in the payload to
            # acquire the parent relationship on the second pass.
            for category in batch.categories:
                ProductService.upsert_category(session, category, observed_at)
            for category in batch.categories:
                ProductService.upsert_category(session, category, observed_at)

            saved = 0
            product_ids: list[int] = []
            source_tool = str(batch.metadata.get("tool") or "ranking")
            snapshot_source = f"mcp:{source_tool}:{scope.scope_key}"[:120]
            for item in batch.products:
                product = ProductService.upsert_product(
                    session,
                    item,
                    observed_at,
                    category_id=scope.category_id,
                )
                product_ids.append(product.id)
                existing_snapshot = session.scalar(
                    select(Snapshot.id).where(
                        Snapshot.product_id == product.id,
                        Snapshot.observed_at == observed_at,
                        Snapshot.source == snapshot_source,
                        Snapshot.variant_key == "default",
                    )
                )
                if existing_snapshot is None:
                    session.add(
                        Snapshot(
                            product_id=product.id,
                            observed_at=observed_at,
                            price_toman=item.price_toman,
                            discount_percent=item.discount_percent,
                            rating_stars=item.rating_stars,
                            rating_count=item.rating_count,
                            availability_status=item.availability_status,
                            source=snapshot_source,
                            collection_run_id=run.id,
                            currency_unit="TOMAN" if item.price_toman is not None else None,
                            original_price_value=(
                                str(item.price_toman) if item.price_toman is not None else None
                            ),
                            variant_key="default",
                            seller=item.seller,
                            is_historical_import=False,
                        )
                    )
                existing_rank = session.scalar(
                    select(RankObservation.id).where(
                        RankObservation.collection_run_id == run.id,
                        RankObservation.scope_key == scope.scope_key,
                        RankObservation.sort_type == scope.sort_type,
                        RankObservation.product_id == product.id,
                    )
                )
                if existing_rank is None:
                    session.add(
                        RankObservation(
                            product_id=product.id,
                            observed_at=observed_at,
                            scope_type=scope.scope_type,
                            scope_id=scope.category_id,
                            scope_key=scope.scope_key,
                            sort_type=scope.sort_type,
                            rank_position=item.rank_position,
                            collection_run_id=run.id,
                        )
                    )
                    saved += 1
            session.flush()
            return saved, product_ids

    async def import_price_history(
        self,
        product_id: int,
        *,
        collection_run_id: int | None = None,
    ) -> tuple[int, list[str]]:
        """Import one product's price chart; returns saved points and warnings.

        Upstream advisories (for example an explicitly unavailable history
        window) surface as warnings so the run records why no points arrived.
        """

        with self.session_factory() as session:
            product = session.get(Product, product_id)
            if not product:
                raise CollectionConfigurationError("unknown product")
            external_id = product.external_id
        batch: PriceHistoryBatch = await self.adapter.fetch_price_history(external_id)
        inserted = 0
        with self.session_factory.begin() as session:
            for point in batch.points:
                exists = session.scalar(
                    select(Snapshot.id).where(
                        Snapshot.product_id == product_id,
                        Snapshot.observed_at == point.observed_at,
                        Snapshot.source == "mcp:product_price_chart",
                        Snapshot.variant_key == point.variant_key,
                    )
                )
                if exists is not None:
                    continue
                session.add(
                    Snapshot(
                        product_id=product_id,
                        observed_at=point.observed_at,
                        price_toman=point.price_toman,
                        source="mcp:product_price_chart",
                        collection_run_id=collection_run_id,
                        currency_unit="TOMAN",
                        original_price_value=str(point.price_toman),
                        variant_key=point.variant_key,
                        seller=point.seller,
                        warranty=point.warranty,
                        is_historical_import=True,
                    )
                )
                inserted += 1
        return inserted, list(batch.warnings)

    def _create_run(self, scope: ScopeSpec, limit: int) -> CollectionRun:
        with self.session_factory.begin() as session:
            run = CollectionRun(
                started_at=utc_now(),
                status=CollectionStatus.RUNNING,
                items_fetched=0,
                items_saved=0,
                scope_type=scope.scope_type,
                scope_key=scope.scope_key,
                category_id=scope.category_id,
                sort_type=scope.sort_type,
                requested_limit=limit,
            )
            session.add(run)
            session.flush()
            return run

    def _finish_run(
        self,
        run_id: int,
        scope: ScopeSpec,
        *,
        status: CollectionStatus,
        items_fetched: int,
        items_saved: int,
        duration_ms: int,
        source_metadata: dict[str, Any],
        error_message: str | None = None,
    ) -> None:
        finished_at = utc_now()
        try:
            with self.session_factory.begin() as session:
                run = session.get(CollectionRun, run_id)
                if not run:
                    return
                run.finished_at = finished_at
                run.status = status
                run.items_fetched = items_fetched
                run.items_saved = items_saved
                run.duration_ms = duration_ms
                run.error_message = error_message
                run.source_metadata = source_metadata
                if scope.config_id:
                    config = session.get(CollectionScope, scope.config_id)
                    if config:
                        if (
                            status in {CollectionStatus.SUCCESS, CollectionStatus.PARTIAL}
                            and items_saved
                        ):
                            config.last_success_at = finished_at
                        if status == CollectionStatus.FAILED:
                            config.last_error_at = finished_at
        except SQLAlchemyError:
            logger.exception(
                "Could not finalize collection run",
                extra={"event": "database_error", "run_id": run_id},
            )
            raise

    @contextmanager
    def _scope_lock(self, scope_key: str, sort_type: str) -> Iterator[None]:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{scope_key}:{sort_type}".encode()).hexdigest()[:20]
        path = self.lock_dir / f"collection-{digest}.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CollectionAlreadyRunning(
                    f"a collection is already running for {scope_key}/{sort_type}"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = " ".join(str(exc).split())[:400]
        return f"{type(exc).__name__}: {message or 'operation failed'}"
