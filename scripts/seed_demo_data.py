"""Create deterministic, clearly labelled development-only observations."""

from __future__ import annotations

import argparse
from datetime import timedelta

from sqlalchemy import delete, inspect, select

from app.config import Settings
from app.database import create_database_engine, create_session_factory, utc_now
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

PRODUCT_TITLES = [
    "گوشی موبایل مدل آفتاب پرو",
    "هدفون بی‌سیم مدل موج",
    "ساعت هوشمند مدل سپهر",
    "تبلت مدل دیدار ۱۱",
    "شارژر سریع مدل نیرو",
    "پاوربانک مدل راه",
    "لپ‌تاپ مدل کارا ۱۴",
    "ماوس بی‌سیم مدل آرام",
    "کیبورد مکانیکی مدل نویسا",
    "مانیتور مدل روشن ۲۴",
    "هارد اکسترنال مدل نگهدار",
    "اسپیکر قابل حمل مدل نوا",
]


def seed(reset: bool) -> None:
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("demo data is permitted only in development or test environments")
    engine = create_database_engine(settings.database_url)
    if not inspect(engine).has_table("products"):
        raise SystemExit("database is not migrated; run: alembic upgrade head")
    factory = create_session_factory(engine)

    with factory.begin() as session:
        existing = session.scalar(select(Product.id).where(Product.external_id.like("demo-%")))
        if existing and not reset:
            print("Demo observations already exist; use --reset to replace them.")
            return
        if reset:
            demo_runs = list(
                session.scalars(select(CollectionRun).where(CollectionRun.scope_key.like("demo:%")))
            )
            # Earlier seed versions use the real global scope; source metadata is
            # the authoritative development label.
            demo_runs.extend(
                run
                for run in session.scalars(select(CollectionRun)).all()
                if isinstance(run.source_metadata, dict) and run.source_metadata.get("demo")
            )
            run_ids = {run.id for run in demo_runs}
            if run_ids:
                session.execute(
                    delete(RankObservation).where(RankObservation.collection_run_id.in_(run_ids))
                )
                session.execute(delete(Snapshot).where(Snapshot.collection_run_id.in_(run_ids)))
                session.execute(delete(CollectionRun).where(CollectionRun.id.in_(run_ids)))
            session.execute(delete(Snapshot).where(Snapshot.source.like("demo:%")))
            demo_category_ids = list(
                session.scalars(select(Category.id).where(Category.external_id.like("demo-%")))
            )
            if demo_category_ids:
                session.execute(
                    delete(CollectionScope).where(
                        CollectionScope.category_id.in_(demo_category_ids)
                    )
                )
            session.execute(delete(Product).where(Product.external_id.like("demo-%")))
            session.execute(delete(Category).where(Category.external_id.like("demo-%")))

    now = utc_now().replace(minute=0, second=0, microsecond=0)
    with factory.begin() as session:
        phones = Category(
            external_id="demo-phones",
            title="موبایل و لوازم دیجیتال (نمایشی)",
            last_seen_at=now,
        )
        computers = Category(
            external_id="demo-computers",
            title="رایانه و تجهیزات (نمایشی)",
            last_seen_at=now,
        )
        session.add_all([phones, computers])
        session.flush()
        products = []
        for index, title in enumerate(PRODUCT_TITLES):
            product = Product(
                external_id=f"demo-{1001 + index}",
                identity_source="demo_fixture",
                title=title,
                category_id=phones.id if index < 6 else computers.id,
                first_seen_at=now - timedelta(days=9),
                last_seen_at=now,
            )
            session.add(product)
            products.append(product)
        session.flush()
        global_scope = session.scalar(
            select(CollectionScope).where(
                CollectionScope.scope_key == "global",
                CollectionScope.sort_type == "best_selling",
            )
        )
        if global_scope:
            global_scope.enabled = True
            global_scope.interval_minutes = 1440
            global_scope.last_success_at = now
        else:
            global_scope = CollectionScope(
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                enabled=True,
                interval_minutes=1440,
                last_success_at=now,
            )
            session.add(global_scope)
        phone_scope = CollectionScope(
            scope_type=ScopeType.CATEGORY,
            scope_key=f"category:{phones.id}",
            category_id=phones.id,
            sort_type="best_selling",
            enabled=True,
            interval_minutes=1440,
            last_success_at=now,
        )
        session.add(phone_scope)

        for day_index in range(10):
            observed_at = now - timedelta(days=9 - day_index)
            global_run = CollectionRun(
                started_at=observed_at,
                finished_at=observed_at + timedelta(seconds=2),
                status=CollectionStatus.SUCCESS,
                items_fetched=len(products),
                items_saved=len(products),
                source_metadata={"demo": True, "note": "deterministic development fixture"},
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                requested_limit=20,
                duration_ms=2000,
            )
            session.add(global_run)
            session.flush()
            rank_a = 10 - day_index
            rank_b = 1 + day_index
            free_positions = [
                position for position in range(1, 13) if position not in {rank_a, rank_b}
            ]
            positions = [rank_a, rank_b, *free_positions]
            for product_index, product in enumerate(products):
                price = (
                    8_000_000
                    + product_index * 2_750_000
                    - day_index * (25_000 + product_index * 500)
                )
                session.add(
                    RankObservation(
                        product_id=product.id,
                        observed_at=observed_at,
                        scope_type=ScopeType.GLOBAL,
                        scope_key="global",
                        sort_type="best_selling",
                        rank_position=positions[product_index],
                        collection_run_id=global_run.id,
                    )
                )
                session.add(
                    Snapshot(
                        product_id=product.id,
                        observed_at=observed_at,
                        price_toman=price,
                        discount_percent=float((product_index + day_index) % 18),
                        rating_stars=round(3.7 + (product_index % 6) * 0.2, 1),
                        rating_count=30 + product_index * 17 + day_index,
                        availability_status="in_stock",
                        source="demo:observed-ranking",
                        collection_run_id=global_run.id,
                        currency_unit="TOMAN",
                        original_price_value=str(price),
                        variant_key="default",
                    )
                )

            category_run = CollectionRun(
                started_at=observed_at + timedelta(minutes=1),
                finished_at=observed_at + timedelta(minutes=1, seconds=1),
                status=CollectionStatus.SUCCESS,
                items_fetched=6,
                items_saved=6,
                source_metadata={"demo": True, "note": "category development fixture"},
                scope_type=ScopeType.CATEGORY,
                scope_key=f"category:{phones.id}",
                category_id=phones.id,
                sort_type="best_selling",
                requested_limit=10,
                duration_ms=1000,
            )
            session.add(category_run)
            session.flush()
            category_order = list(range(6))
            category_order.insert(0, category_order.pop((9 - day_index) % 6))
            for rank, product_index in enumerate(category_order, start=1):
                session.add(
                    RankObservation(
                        product_id=products[product_index].id,
                        observed_at=category_run.started_at,
                        scope_type=ScopeType.CATEGORY,
                        scope_id=phones.id,
                        scope_key=f"category:{phones.id}",
                        sort_type="best_selling",
                        rank_position=rank,
                        collection_run_id=category_run.id,
                    )
                )

        # A failed opportunity proves that failed runs are disclosed but never
        # counted as a product absence.
        failed_at = now - timedelta(days=3, hours=12)
        session.add(
            CollectionRun(
                started_at=failed_at,
                finished_at=failed_at + timedelta(seconds=1),
                status=CollectionStatus.FAILED,
                items_fetched=0,
                items_saved=0,
                error_message="DemoNetworkError: خطای نمایشی دریافت داده",
                source_metadata={"demo": True, "error_type": "DemoNetworkError"},
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                requested_limit=20,
                duration_ms=1000,
            )
        )
    engine.dispose()
    print("Seeded 10 days of clearly labelled demo observations. No sales quantities were created.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic development-only data")
    parser.add_argument("--reset", action="store_true", help="replace existing demo fixture rows")
    args = parser.parse_args()
    seed(args.reset)


if __name__ == "__main__":
    main()
