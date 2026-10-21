"""Enable and disable conservative scheduled collection scopes."""

from __future__ import annotations

import argparse

from sqlalchemy import inspect, select

from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.models import Category, CollectionScope, ScopeType


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage DigiScope scheduled collection scopes")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list configured scopes and known categories")
    add = sub.add_parser("add-category", help="monitor one already-known category")
    add.add_argument("category_id", type=int, help="internal category id from /api/categories")
    add.add_argument("--interval", type=int, default=None, help="collection interval in minutes")
    toggle = sub.add_parser("set-enabled", help="enable or disable a scope")
    toggle.add_argument("scope_id", type=int)
    toggle.add_argument("value", choices=["true", "false"])
    args = parser.parse_args()

    settings = Settings()
    engine = create_database_engine(settings.database_url)
    if not inspect(engine).has_table("collection_scopes"):
        raise SystemExit("database is not migrated; run: alembic upgrade head")
    factory = create_session_factory(engine)
    with factory.begin() as session:
        global_scope = session.scalar(
            select(CollectionScope).where(
                CollectionScope.scope_key == "global",
                CollectionScope.sort_type == "best_selling",
            )
        )
        if not global_scope:
            session.add(
                CollectionScope(
                    scope_type=ScopeType.GLOBAL,
                    scope_key="global",
                    sort_type="best_selling",
                    enabled=True,
                    interval_minutes=settings.collection_interval_minutes,
                )
            )
    try:
        if args.command == "list":
            with factory() as session:
                print("Configured scopes:")
                for scope in session.scalars(select(CollectionScope).order_by(CollectionScope.id)):
                    print(
                        f"  {scope.id}: {scope.scope_key} sort={scope.sort_type} "
                        f"enabled={scope.enabled} interval={scope.interval_minutes}m"
                    )
                print("Known categories:")
                for category in session.scalars(select(Category).order_by(Category.title)):
                    print(
                        f"  {category.id}: external={category.external_id} title={category.title}"
                    )
        elif args.command == "add-category":
            interval = args.interval or settings.collection_interval_minutes
            if interval < 5:
                raise SystemExit("interval must be at least 5 minutes")
            with factory.begin() as session:
                category = session.get(Category, args.category_id)
                if not category:
                    raise SystemExit(
                        "unknown category; collect global data first and list categories"
                    )
                key = f"category:{category.id}"
                scope = session.scalar(
                    select(CollectionScope).where(
                        CollectionScope.scope_key == key,
                        CollectionScope.sort_type == "best_selling",
                    )
                )
                if scope:
                    scope.enabled = True
                    scope.interval_minutes = interval
                    print(f"Updated scope {scope.id}: {key}")
                else:
                    scope = CollectionScope(
                        scope_type=ScopeType.CATEGORY,
                        scope_key=key,
                        category_id=category.id,
                        sort_type="best_selling",
                        enabled=True,
                        interval_minutes=interval,
                    )
                    session.add(scope)
                    session.flush()
                    print(f"Added scope {scope.id}: {key}")
        else:
            with factory.begin() as session:
                scope = session.get(CollectionScope, args.scope_id)
                if not scope:
                    raise SystemExit("unknown scope id")
                scope.enabled = args.value == "true"
                print(f"Scope {scope.id} enabled={scope.enabled}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
