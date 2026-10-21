"""Persistent data model for observed marketplace facts."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utc_now


class ScopeType(str, enum.Enum):
    GLOBAL = "global"
    CATEGORY = "category"


class CollectionStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


scope_type_enum = Enum(
    ScopeType, native_enum=False, length=16, values_callable=lambda x: [e.value for e in x]
)
status_enum = Enum(
    CollectionStatus,
    native_enum=False,
    length=16,
    values_callable=lambda x: [e.value for e in x],
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    parent: Mapped[Category | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False, default="upstream_id")
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    category: Mapped[Category | None] = relationship()
    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    rank_observations: Mapped[list[RankObservation]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        CheckConstraint("items_fetched >= 0", name="ck_collection_runs_items_fetched"),
        CheckConstraint("items_saved >= 0", name="ck_collection_runs_items_saved"),
        CheckConstraint(
            "(scope_type = 'global' AND category_id IS NULL) OR "
            "(scope_type = 'category' AND category_id IS NOT NULL)",
            name="ck_collection_runs_scope_category",
        ),
        Index("ix_collection_runs_scope_started", "scope_key", "sort_type", "started_at"),
        Index("ix_collection_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CollectionStatus] = mapped_column(
        status_enum, default=CollectionStatus.RUNNING, nullable=False
    )
    items_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_saved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scope_type: Mapped[ScopeType] = mapped_column(scope_type_enum, nullable=False)
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        # A category that owns recorded observations cannot be deleted: the
        # check constraint above requires a category scope to keep its
        # category, so nulling the reference would break the row. Deleting the
        # observations first is the explicit, auditable path.
        ForeignKey(
            "categories.id",
            name="fk_collection_runs_category_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    sort_type: Mapped[str] = mapped_column(String(80), nullable=False, default="best_selling")
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped[Category | None] = relationship()
    snapshots: Mapped[list[Snapshot]] = relationship(back_populates="collection_run")
    rank_observations: Mapped[list[RankObservation]] = relationship(back_populates="collection_run")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "observed_at",
            "source",
            "variant_key",
            name="uq_snapshots_fact",
        ),
        CheckConstraint("price_toman IS NULL OR price_toman >= 0", name="ck_snapshots_price"),
        CheckConstraint(
            "discount_percent IS NULL OR (discount_percent >= 0 AND discount_percent <= 100)",
            name="ck_snapshots_discount",
        ),
        CheckConstraint(
            "rating_stars IS NULL OR (rating_stars >= 0 AND rating_stars <= 5)",
            name="ck_snapshots_rating",
        ),
        CheckConstraint(
            "rating_count IS NULL OR rating_count >= 0", name="ck_snapshots_rating_count"
        ),
        Index("ix_snapshots_product_observed", "product_id", "observed_at"),
        Index("ix_snapshots_observed", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_toman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_stars: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    collection_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="SET NULL"), nullable=True
    )
    currency_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_price_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variant_key: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    seller: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warranty: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_historical_import: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped[Product] = relationship(back_populates="snapshots")
    collection_run: Mapped[CollectionRun | None] = relationship(back_populates="snapshots")


class RankObservation(Base):
    __tablename__ = "rank_observations"
    __table_args__ = (
        UniqueConstraint(
            "collection_run_id",
            "scope_key",
            "sort_type",
            "product_id",
            name="uq_rank_run_product",
        ),
        UniqueConstraint(
            "collection_run_id",
            "scope_key",
            "sort_type",
            "rank_position",
            name="uq_rank_run_position",
        ),
        CheckConstraint("rank_position > 0", name="ck_rank_position_positive"),
        CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type = 'category' AND scope_id IS NOT NULL)",
            name="ck_rank_scope_category",
        ),
        Index(
            "ix_rank_scope_observed",
            "scope_key",
            "sort_type",
            "observed_at",
            "rank_position",
        ),
        Index("ix_rank_product_observed", "product_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope_type: Mapped[ScopeType] = mapped_column(scope_type_enum, nullable=False)
    scope_id: Mapped[int | None] = mapped_column(
        # Same rule as collection_runs.category_id: a category scope keeps its
        # category, so the category cannot disappear under the observation.
        ForeignKey(
            "categories.id",
            name="fk_rank_observations_scope_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    sort_type: Mapped[str] = mapped_column(String(80), nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    collection_run_id: Mapped[int] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="rank_observations")
    collection_run: Mapped[CollectionRun] = relationship(back_populates="rank_observations")
    scope_category: Mapped[Category | None] = relationship()


class CollectionScope(Base):
    __tablename__ = "collection_scopes"
    __table_args__ = (
        UniqueConstraint("scope_key", "sort_type", name="uq_collection_scope_key_sort"),
        CheckConstraint("interval_minutes >= 5", name="ck_collection_scope_interval"),
        CheckConstraint(
            "(scope_type = 'global' AND category_id IS NULL) OR "
            "(scope_type = 'category' AND category_id IS NOT NULL)",
            name="ck_collection_scopes_scope_category",
        ),
        Index("ix_collection_scopes_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_type: Mapped[ScopeType] = mapped_column(scope_type_enum, nullable=False)
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    sort_type: Mapped[str] = mapped_column(String(80), nullable=False, default="best_selling")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    category: Mapped[Category | None] = relationship()
