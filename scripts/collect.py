"""Run one scheduled/manual collection process (cron entry point)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.mcp.factory import build_adapter
from app.services.collection_service import (
    CollectionAlreadyRunning,
    CollectionConfigurationError,
    CollectionOutcome,
    CollectionService,
    ScopeSpec,
    skipped_outcome,
)


async def collect_scopes(
    service: CollectionService,
    scopes: list[ScopeSpec],
    *,
    limit: int,
    include_price_history: bool,
) -> list[CollectionOutcome]:
    """Collect each scope; a locked scope is reported as skipped, not as a crash."""

    outcomes: list[CollectionOutcome] = []
    for scope in scopes:
        try:
            outcomes.append(
                await service.run_scope(
                    scope,
                    limit=limit,
                    include_price_history=include_price_history,
                )
            )
        except CollectionAlreadyRunning as exc:
            outcomes.append(skipped_outcome(scope.scope_key, str(exc)))
    return outcomes


async def run(args: argparse.Namespace) -> int:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    adapter = build_adapter(settings)
    service = CollectionService(create_session_factory(engine), adapter, settings)
    try:
        service.ensure_default_scope()
        limit = args.limit or settings.default_ranking_limit
        if args.category_id:
            try:
                scopes = [
                    service.scope_for_category(category_id) for category_id in args.category_id
                ]
            except CollectionConfigurationError as exc:
                print(f"collection skipped: {exc}", file=sys.stderr)
                return 2
            if not args.no_global:
                scopes = [
                    scope
                    for scope in service.configured_scopes(enabled_only=False)
                    if scope.scope_key == "global"
                ] + scopes
            outcomes = await collect_scopes(
                service,
                scopes,
                limit=limit,
                include_price_history=args.with_price_history,
            )
        else:
            outcomes = await service.run_configured(
                limit=args.limit,
                include_price_history=args.with_price_history,
                include_global=not args.no_global,
            )
        print(json.dumps([asdict(outcome) for outcome in outcomes], ensure_ascii=False, indent=2))
        return 1 if any(outcome.status == "failed" for outcome in outcomes) else 0
    finally:
        await adapter.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect observed Digikala rankings")
    parser.add_argument("--limit", type=int, help="requested top N (maximum configured value)")
    parser.add_argument(
        "--category-id",
        type=int,
        action="append",
        default=[],
        help="internal DigiScope category id; repeat to collect multiple categories",
    )
    parser.add_argument("--no-global", action="store_true", help="skip global scope")
    parser.add_argument(
        "--with-price-history",
        action="store_true",
        help="import the verified ~30-day price chart for a bounded number of products",
    )
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
