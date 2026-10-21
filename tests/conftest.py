from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base, create_database_engine, create_session_factory, utc_now
from app.main import create_app
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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        collection_lock_dir=tmp_path / "locks",
        admin_token="test-admin-secret",
        collection_interval_minutes=1440,
        price_history_products_per_run=2,
    )


@pytest.fixture
def engine(settings: Settings):
    value = create_database_engine(settings.database_url)
    Base.metadata.create_all(value)
    yield value
    value.dispose()


@pytest.fixture
def session_factory(engine):
    return create_session_factory(engine)


@pytest.fixture
def session(session_factory) -> Session:
    value = session_factory()
    yield value
    value.rollback()
    value.close()


@pytest.fixture
def ranking_payload() -> dict:
    return {
        "returned": 3,
        "fetched": 3,
        "total_items_estimate": 50,
        "categories": [
            {"id": 11, "title": "گوشی موبایل", "url": "https://www.digikala.com/main/mobile/"}
        ],
        "items": [
            {
                "id": 101,
                "title": "گوشی نمونه یک",
                "price_toman": 12_000_000,
                "discount_percent": 8,
                "rating_stars": 4.4,
                "rating_count": 120,
                "in_stock": True,
                "seller": "فروشنده یک",
                "url": "https://www.digikala.com/product/dkp-101/",
            },
            {
                "id": 102,
                "title": "گوشی نمونه دو",
                "price_toman": None,
                "discount_percent": 0,
                "rating_stars": None,
                "rating_count": 0,
                "in_stock": False,
                "url": "https://www.digikala.com/product/dkp-102/",
            },
            {
                "id": 103,
                "title": "گوشی نمونه سه",
                "price_toman": 8_500_000,
                "url": "https://www.digikala.com/product/dkp-103/",
            },
        ],
    }


@pytest.fixture
def mock_adapter(ranking_payload: dict) -> MockMCPAdapter:
    return MockMCPAdapter(
        ranking_payloads={"global": ranking_payload, "category:11": ranking_payload},
        price_payloads={
            "101": {
                "window_days": 30,
                "current_price_toman": 12_000_000,
                "series": [
                    {
                        "variant_id": 1,
                        "color": "مشکی",
                        "points": [
                            {"day": "2026-10-01", "price_toman": 12_500_000, "seller": "الف"},
                            {"day": "2026-10-02", "price_toman": 12_000_000, "seller": "ب"},
                        ],
                    }
                ],
            }
        },
    )


@pytest.fixture
def seeded_market(session_factory):
    now = utc_now().replace(microsecond=0) - timedelta(minutes=5)
    with session_factory.begin() as db:
        category_a = Category(external_id="11", title="موبایل", last_seen_at=now)
        category_b = Category(external_id="22", title="رایانه", last_seen_at=now)
        db.add_all([category_a, category_b])
        db.flush()
        products = [
            Product(
                external_id="201",
                identity_source="upstream_id",
                title="محصول رو به رشد",
                url="https://www.digikala.com/product/dkp-201/",
                category_id=category_a.id,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now,
            ),
            Product(
                external_id="202",
                identity_source="upstream_id",
                title="محصول نزولی",
                url="https://www.digikala.com/product/dkp-202/",
                category_id=category_a.id,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now,
            ),
            Product(
                external_id="203",
                identity_source="upstream_id",
                title="محصول ثابت",
                category_id=category_b.id,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now,
            ),
            Product(
                external_id="204",
                identity_source="upstream_id",
                title="=فرمول آزمایشی",
                category_id=category_b.id,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now,
            ),
            Product(
                external_id="205",
                identity_source="upstream_id",
                title="فقط تاریخچه قیمت",
                category_id=category_b.id,
                first_seen_at=now - timedelta(days=3),
                last_seen_at=now,
            ),
        ]
        db.add_all(products)
        db.flush()
        global_scope = CollectionScope(
            scope_type=ScopeType.GLOBAL,
            scope_key="global",
            sort_type="best_selling",
            enabled=True,
            interval_minutes=1440,
            last_success_at=now,
        )
        category_scope = CollectionScope(
            scope_type=ScopeType.CATEGORY,
            scope_key=f"category:{category_a.id}",
            category_id=category_a.id,
            sort_type="best_selling",
            enabled=True,
            interval_minutes=1440,
            last_success_at=now,
        )
        db.add_all([global_scope, category_scope])
        trajectories = {
            products[0].id: [20, 15, 10, 5],
            products[1].id: [2, 4, 7, 9],
            products[2].id: [6, 6, 6, 6],
            products[3].id: [12, 11, None, 8],
        }
        runs = []
        for index in range(4):
            observed = now - timedelta(days=3 - index)
            run = CollectionRun(
                started_at=observed,
                finished_at=observed + timedelta(seconds=1),
                status=CollectionStatus.SUCCESS,
                items_fetched=4,
                items_saved=4 if index != 2 else 3,
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                requested_limit=20,
                source_metadata={"fixture": True},
            )
            db.add(run)
            db.flush()
            runs.append(run)
            for product_index, product in enumerate(products[:4]):
                rank = trajectories[product.id][index]
                if rank is not None:
                    db.add(
                        RankObservation(
                            product_id=product.id,
                            observed_at=observed,
                            scope_type=ScopeType.GLOBAL,
                            scope_key="global",
                            sort_type="best_selling",
                            rank_position=rank,
                            collection_run_id=run.id,
                        )
                    )
                db.add(
                    Snapshot(
                        product_id=product.id,
                        observed_at=observed,
                        price_toman=1_000_000 * (product_index + 1) + index * 10_000,
                        discount_percent=float(index),
                        rating_stars=4.0,
                        rating_count=10 + index,
                        availability_status="in_stock",
                        source="test:ranking",
                        collection_run_id=run.id,
                        currency_unit="TOMAN",
                        original_price_value="verified",
                        variant_key="default",
                    )
                )
        failed = CollectionRun(
            started_at=now - timedelta(days=1, hours=12),
            finished_at=now - timedelta(days=1, hours=12) + timedelta(seconds=1),
            status=CollectionStatus.FAILED,
            items_fetched=0,
            items_saved=0,
            error_message="Timeout: fixture failure",
            scope_type=ScopeType.GLOBAL,
            scope_key="global",
            sort_type="best_selling",
            requested_limit=20,
        )
        db.add(failed)
        db.flush()
        # One product is observed in more than one category scope while remaining
        # a single product row.
        category_run = CollectionRun(
            started_at=now,
            finished_at=now + timedelta(seconds=1),
            status=CollectionStatus.SUCCESS,
            items_fetched=2,
            items_saved=2,
            scope_type=ScopeType.CATEGORY,
            scope_key=f"category:{category_a.id}",
            category_id=category_a.id,
            sort_type="best_selling",
            requested_limit=10,
        )
        db.add(category_run)
        db.flush()
        db.add_all(
            [
                RankObservation(
                    product_id=products[0].id,
                    observed_at=now,
                    scope_type=ScopeType.CATEGORY,
                    scope_id=category_a.id,
                    scope_key=f"category:{category_a.id}",
                    sort_type="best_selling",
                    rank_position=1,
                    collection_run_id=category_run.id,
                ),
                RankObservation(
                    product_id=products[1].id,
                    observed_at=now,
                    scope_type=ScopeType.CATEGORY,
                    scope_id=category_a.id,
                    scope_key=f"category:{category_a.id}",
                    sort_type="best_selling",
                    rank_position=2,
                    collection_run_id=category_run.id,
                ),
                Snapshot(
                    product_id=products[4].id,
                    observed_at=now - timedelta(days=2),
                    price_toman=9_000_000,
                    source="test:price-only",
                    currency_unit="TOMAN",
                    original_price_value="9000000",
                    variant_key="blue",
                    is_historical_import=True,
                ),
            ]
        )
        ids = {
            "category_a": category_a.id,
            "category_b": category_b.id,
            "products": [product.id for product in products],
            "now": now,
        }
    return ids


@pytest.fixture
def client(settings, engine, mock_adapter, seeded_market):
    application = create_app(settings, engine=engine, adapter=mock_adapter)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def empty_client(settings, engine, mock_adapter):
    application = create_app(settings, engine=engine, adapter=mock_adapter)
    with TestClient(application) as test_client:
        yield test_client
