from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.database import create_database_engine, utc_now
from app.models import (
    CollectionRun,
    CollectionStatus,
    Product,
    RankObservation,
    ScopeType,
    Snapshot,
)


def make_product(external_id: str = "1") -> Product:
    now = utc_now()
    return Product(
        external_id=external_id,
        identity_source="upstream_id",
        title="کالا",
        first_seen_at=now,
        last_seen_at=now,
    )


def make_run() -> CollectionRun:
    return CollectionRun(
        status=CollectionStatus.RUNNING,
        scope_type=ScopeType.GLOBAL,
        scope_key="global",
        sort_type="best_selling",
        requested_limit=10,
    )


def test_clean_schema_contains_required_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {
        "products",
        "categories",
        "snapshots",
        "rank_observations",
        "collection_runs",
        "collection_scopes",
    } <= tables


def test_duplicate_external_product_id_is_prevented(session_factory):
    with pytest.raises(IntegrityError), session_factory.begin() as db:
        db.add_all([make_product("same"), make_product("same")])
    with session_factory() as db:
        assert db.scalar(select(text("count(*)")).select_from(Product)) == 0


def test_snapshot_and_rank_persistence_and_duplicate_prevention(session_factory):
    now = utc_now().replace(microsecond=0)
    with session_factory.begin() as db:
        product = make_product("42")
        run = make_run()
        db.add_all([product, run])
        db.flush()
        db.add(
            Snapshot(
                product_id=product.id,
                observed_at=now,
                price_toman=1000,
                source="test",
                collection_run_id=run.id,
                currency_unit="TOMAN",
                variant_key="default",
            )
        )
        db.add(
            RankObservation(
                product_id=product.id,
                observed_at=now,
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                rank_position=1,
                collection_run_id=run.id,
            )
        )
    with session_factory() as db:
        assert db.scalar(select(Snapshot.price_toman)) == 1000
        assert db.scalar(select(RankObservation.rank_position)) == 1
    with pytest.raises(IntegrityError), session_factory.begin() as db:
        product = db.scalar(select(Product).where(Product.external_id == "42"))
        run = db.scalar(select(CollectionRun))
        db.add(
            RankObservation(
                product_id=product.id,
                observed_at=now,
                scope_type=ScopeType.GLOBAL,
                scope_key="global",
                sort_type="best_selling",
                rank_position=2,
                collection_run_id=run.id,
            )
        )


def test_transaction_rolls_back_all_writes(session_factory):
    with pytest.raises(RuntimeError), session_factory.begin() as db:
        db.add(make_product("rollback"))
        db.flush()
        raise RuntimeError("force rollback")
    with session_factory() as db:
        assert db.scalar(select(Product).where(Product.external_id == "rollback")) is None


def test_sqlite_foreign_keys_are_enforced(session_factory):
    with pytest.raises(IntegrityError), session_factory.begin() as db:
        db.add(
            Snapshot(product_id=9999, observed_at=utc_now(), source="test", variant_key="default")
        )


def test_check_constraints_reject_invalid_observed_values(session_factory):
    with session_factory.begin() as db:
        product = make_product("bad-price")
        db.add(product)
        db.flush()
        product_id = product.id
    with pytest.raises(IntegrityError), session_factory.begin() as db:
        db.add(
            Snapshot(
                product_id=product_id,
                observed_at=utc_now(),
                price_toman=-1,
                source="test",
                variant_key="default",
            )
        )


def test_alembic_upgrade_creates_missing_database_directory(tmp_path: Path, monkeypatch):
    database = tmp_path / "nested" / "runtime" / "migrated.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    assert database.exists()
    engine = create_database_engine(f"sqlite:///{database}")
    assert "rank_observations" in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_upgrade_from_clean_database(tmp_path: Path, monkeypatch):
    database = tmp_path / "migrated.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database}")
    assert "rank_observations" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "17025a71ce1e"
        )
    command.downgrade(config, "base")
    assert "products" not in inspect(engine).get_table_names()
    engine.dispose()
