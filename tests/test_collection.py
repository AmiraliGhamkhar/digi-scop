from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.database import utc_now
from app.mcp.adapter import MockMCPAdapter
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
from app.services.collection_service import (
    CollectionAlreadyRunning,
    CollectionService,
)


@pytest.mark.asyncio
async def test_collection_normalizes_and_persists_observed_facts(
    session_factory, mock_adapter, settings
):
    service = CollectionService(session_factory, mock_adapter, settings)
    scope_model = service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    outcome = await service.run_scope(scope, limit=3)
    assert outcome.status == "success"
    assert outcome.items_saved == 3
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 3
        assert db.scalar(select(func.count(Snapshot.id))) == 3
        assert db.scalar(select(func.count(RankObservation.id))) == 3
        run = db.get(CollectionRun, outcome.run_id)
        assert run.status == CollectionStatus.SUCCESS
        assert run.finished_at is not None
        assert run.source_metadata["tool"] == "mock"
        assert db.get(CollectionScope, scope_model.id).last_success_at is not None
        missing = db.scalar(select(Snapshot).where(Snapshot.price_toman.is_(None)))
        assert missing.currency_unit is None


@pytest.mark.asyncio
async def test_repeated_collections_keep_history_but_deduplicate_products(
    session_factory, mock_adapter, settings
):
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    first = await service.run_scope(scope, limit=3)
    second = await service.run_scope(scope, limit=3)
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 3
        assert db.scalar(select(func.count(CollectionRun.id))) == 2
        assert db.scalar(select(func.count(RankObservation.id))) == 6
        assert first.run_id != second.run_id


@pytest.mark.asyncio
async def test_duplicate_persist_for_same_run_is_idempotent(
    session_factory, mock_adapter, settings
):
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    outcome = await service.run_scope(scope, limit=3)
    batch = await mock_adapter.fetch_ranking(
        scope_type=ScopeType.GLOBAL, category_external_id=None, limit=3
    )
    saved, _ = service.persist_batch(outcome.run_id, scope, batch)
    assert saved == 0
    with session_factory() as db:
        assert db.scalar(select(func.count(RankObservation.id))) == 3
        assert db.scalar(select(func.count(Snapshot.id))) == 3


@pytest.mark.asyncio
async def test_adapter_failure_is_recorded_without_deleting_history(
    session_factory, ranking_payload, settings
):
    adapter = MockMCPAdapter(ranking_payloads={"global": ranking_payload})
    service = CollectionService(session_factory, adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    successful = await service.run_scope(scope, limit=3)
    adapter.errors["global"] = TimeoutError("upstream unavailable")
    failed = await service.run_scope(scope, limit=3)
    assert successful.status == "success"
    assert failed.status == "failed"
    with session_factory() as db:
        assert db.scalar(select(func.count(RankObservation.id))) == 3
        run = db.get(CollectionRun, failed.run_id)
        assert run.status == CollectionStatus.FAILED
        assert "TimeoutError" in run.error_message


@pytest.mark.asyncio
async def test_schema_warning_creates_partial_run(session_factory, settings):
    adapter = MockMCPAdapter(
        ranking_payloads={
            "global": {
                "items": [
                    {"id": 1, "title": "valid"},
                    {"title": "no stable identity"},
                ]
            }
        }
    )
    service = CollectionService(session_factory, adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    outcome = await service.run_scope(scope, limit=10)
    assert outcome.status == "partial"
    assert outcome.items_saved == 1
    assert outcome.warnings


@pytest.mark.asyncio
async def test_category_scope_retains_separate_ranking(session_factory, ranking_payload, settings):
    adapter = MockMCPAdapter(
        ranking_payloads={"global": ranking_payload, "category:11": ranking_payload}
    )
    service = CollectionService(session_factory, adapter, settings)
    service.ensure_default_scope()
    with session_factory.begin() as db:
        category = Category(external_id="11", title="موبایل", last_seen_at=utc_now())
        db.add(category)
        db.flush()
        category_id = category.id
        db.add(
            CollectionScope(
                scope_type=ScopeType.CATEGORY,
                scope_key=f"category:{category_id}",
                category_id=category_id,
                sort_type="best_selling",
                enabled=True,
                interval_minutes=1440,
            )
        )
    global_scope = next(
        scope for scope in service.configured_scopes() if scope.scope_type == ScopeType.GLOBAL
    )
    category_scope = next(
        scope for scope in service.configured_scopes() if scope.scope_type == ScopeType.CATEGORY
    )
    await service.run_scope(global_scope, limit=3)
    await service.run_scope(category_scope, limit=3)
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 3
        assert set(db.scalars(select(RankObservation.scope_key))) == {
            "global",
            f"category:{category_id}",
        }


@pytest.mark.asyncio
async def test_price_history_import_deduplicates_and_never_creates_rank(
    session_factory, mock_adapter, settings
):
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    await service.run_scope(scope, limit=3)
    with session_factory() as db:
        product_id = db.scalar(select(Product.id).where(Product.external_id == "101"))
        rank_count = db.scalar(select(func.count(RankObservation.id)))
    imported, warnings = await service.import_price_history(product_id)
    assert imported == 2
    assert warnings == []
    reimported, _ = await service.import_price_history(product_id)
    assert reimported == 0
    with session_factory() as db:
        assert db.scalar(select(func.count(RankObservation.id))) == rank_count
        imported = list(db.scalars(select(Snapshot).where(Snapshot.is_historical_import.is_(True))))
        assert len(imported) == 2
        assert all(point.source == "mcp:product_price_chart" for point in imported)


@pytest.mark.asyncio
async def test_unavailable_price_history_is_reported_without_failing_the_run(
    session_factory, mock_adapter, settings
):
    mock_adapter.price_payloads["101"] = {
        "history_available": False,
        "items": [],
        "returned": 0,
        "message": "Digikala is not serving price history for product 101 right now.",
        "suggestion": "The history endpoint is refusing requests right now.",
    }
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    outcome = await service.run_scope(scope, limit=3, include_price_history=True)
    assert outcome.status == "partial"
    assert outcome.items_saved == 3
    assert any(
        "price history product" in warning and "not serving price history" in warning
        for warning in outcome.warnings
    )


@pytest.mark.asyncio
async def test_items_fetched_prefers_the_upstream_returned_count(session_factory, settings):
    payload = {
        "returned": 3,
        "items": [
            {"id": 1, "title": "a"},
            {"title": "missing stable identity"},
            {"id": 2, "title": "b"},
            {"id": 3, "title": "c"},
        ],
    }
    adapter = MockMCPAdapter(ranking_payloads={"global": payload})
    service = CollectionService(session_factory, adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    outcome = await service.run_scope(scope, limit=10)
    # The upstream count wins; warnings about skipped rows never inflate it.
    assert outcome.items_fetched == 3
    assert outcome.items_saved == 3
    assert outcome.status == "partial"


@pytest.mark.asyncio
async def test_run_configured_can_skip_the_global_scope(session_factory, mock_adapter, settings):
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    with session_factory.begin() as db:
        category = Category(external_id="11", title="موبایل", last_seen_at=utc_now())
        db.add(category)
        db.flush()
        category_id = category.id
        db.add(
            CollectionScope(
                scope_type=ScopeType.CATEGORY,
                scope_key=f"category:{category_id}",
                category_id=category_id,
                sort_type="best_selling",
                enabled=True,
                interval_minutes=1440,
            )
        )
    outcomes = await service.run_configured(limit=3, include_global=False)
    assert [outcome.scope_key for outcome in outcomes] == [f"category:{category_id}"]
    with session_factory() as db:
        runs = list(db.scalars(select(CollectionRun)))
    assert all(run.scope_key != "global" for run in runs)


@pytest.mark.asyncio
async def test_scope_lock_prevents_overlapping_job(session_factory, mock_adapter, settings):
    service = CollectionService(session_factory, mock_adapter, settings)
    service.ensure_default_scope()
    scope = service.configured_scopes()[0]
    with (
        service._scope_lock(scope.scope_key, scope.sort_type),
        pytest.raises(CollectionAlreadyRunning),
    ):
        await service.run_scope(scope, limit=3)
