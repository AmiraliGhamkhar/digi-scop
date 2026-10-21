"""restrict category references that the scope checks protect

The scope checks require a category scope to keep its category row
(``ck_collection_runs_scope_category`` and ``ck_rank_scope_category``), but
the foreign keys used to promise ``ON DELETE SET NULL``. The two rules could
not both hold: deleting a category nulled the reference and the row then
violated its own check constraint. The foreign keys now refuse the delete
instead, so recorded observations are never silently orphaned.

Revision ID: b7c8d9e0f1a2
Revises: 17025a71ce1e
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "17025a71ce1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite cannot alter a foreign key in place, so Alembic recreates the table.
# The table definitions below are spelled out in full: the recreate copies
# columns, check constraints, unique constraints, foreign keys and indexes
# from this definition, so nothing is lost on the way.
_STATUS = sa.Enum(
    "running",
    "success",
    "partial",
    "failed",
    name="collectionstatus",
    native_enum=False,
    length=16,
)
_SCOPE_TYPE = sa.Enum(
    "global",
    "category",
    name="scopetype",
    native_enum=False,
    length=16,
)


def _collection_runs_table(ondelete: str) -> sa.Table:
    return sa.Table(
        "collection_runs",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", _STATUS, nullable=False),
        sa.Column("items_fetched", sa.Integer(), nullable=False),
        sa.Column("items_saved", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("scope_type", _SCOPE_TYPE, nullable=False),
        sa.Column("scope_key", sa.String(length=160), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("sort_type", sa.String(length=80), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("items_fetched >= 0", name="ck_collection_runs_items_fetched"),
        sa.CheckConstraint("items_saved >= 0", name="ck_collection_runs_items_saved"),
        sa.CheckConstraint(
            "(scope_type = 'global' AND category_id IS NULL) OR "
            "(scope_type = 'category' AND category_id IS NOT NULL)",
            name="ck_collection_runs_scope_category",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_collection_runs_category_id",
            ondelete=ondelete,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_collection_runs_scope_started", "scope_key", "sort_type", "started_at"),
        sa.Index("ix_collection_runs_status_started", "status", "started_at"),
    )


def _rank_observations_table(ondelete: str) -> sa.Table:
    return sa.Table(
        "rank_observations",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_type", _SCOPE_TYPE, nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("scope_key", sa.String(length=160), nullable=False),
        sa.Column("sort_type", sa.String(length=80), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("collection_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("rank_position > 0", name="ck_rank_position_positive"),
        sa.CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type = 'category' AND scope_id IS NOT NULL)",
            name="ck_rank_scope_category",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_rank_observations_collection_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_rank_observations_product_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["categories.id"],
            name="fk_rank_observations_scope_id",
            ondelete=ondelete,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_run_id", "scope_key", "sort_type", "product_id", name="uq_rank_run_product"
        ),
        sa.UniqueConstraint(
            "collection_run_id",
            "scope_key",
            "sort_type",
            "rank_position",
            name="uq_rank_run_position",
        ),
        sa.Index("ix_rank_product_observed", "product_id", "observed_at"),
        sa.Index(
            "ix_rank_scope_observed",
            "scope_key",
            "sort_type",
            "observed_at",
            "rank_position",
        ),
    )


def _set_category_ondelete(
    table: sa.Table,
    *,
    constraint_name: str,
    column: str,
    ondelete: str,
) -> None:
    with op.batch_alter_table(
        table.name,
        copy_from=table,
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(constraint_name)
        batch_op.create_foreign_key(
            constraint_name,
            "categories",
            [column],
            ["id"],
            ondelete=ondelete,
        )


def _rebuild(ondelete: str) -> None:
    """Rebuild both tables with the requested category foreign key action.

    SQLite applies ``ON DELETE CASCADE`` when a parent table is dropped, so
    rebuilding ``collection_runs`` would delete every rank observation that
    points at it. Foreign key enforcement is therefore switched off for the
    rebuild and switched on again afterwards; the migration refuses to run if
    SQLite ignores the switch, because that would silently lose rows.
    """

    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
            raise RuntimeError(
                "SQLite refused to disable foreign key enforcement; the table "
                "rebuild would delete the dependent rows"
            )
    try:
        _set_category_ondelete(
            _collection_runs_table("SET NULL" if ondelete == "RESTRICT" else "RESTRICT"),
            constraint_name="fk_collection_runs_category_id",
            column="category_id",
            ondelete=ondelete,
        )
        _set_category_ondelete(
            _rank_observations_table("SET NULL" if ondelete == "RESTRICT" else "RESTRICT"),
            constraint_name="fk_rank_observations_scope_id",
            column="scope_id",
            ondelete=ondelete,
        )
    finally:
        if sqlite:
            # Best effort: SQLite ignores the pragma while a transaction is
            # open, and migrations/env.py re-asserts it after the run.
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _rebuild("RESTRICT")


def downgrade() -> None:
    _rebuild("SET NULL")
