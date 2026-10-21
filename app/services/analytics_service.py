"""Coverage-aware ranking analytics built only from stored observations."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import as_utc, utc_now
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

ELIGIBLE_STATUSES = (CollectionStatus.SUCCESS, CollectionStatus.PARTIAL)
PERIOD_DAYS = {"7d": 7, "30d": 30}


class AnalyticsService:
    """Read-side service; every formula is deterministic and exposed in output."""

    TREND_FORMULA = (
        "100 × (0.55 × normalized_rank_improvement + 0.25 × presence + "
        "0.10 × observation_confidence + 0.10 × recency); range -100..100"
    )

    def __init__(self, session: Session, *, default_interval_minutes: int = 1440) -> None:
        self.session = session
        self.default_interval_minutes = default_interval_minutes

    @staticmethod
    def scope_key(scope: ScopeType | str, category_id: int | None = None) -> str:
        value = scope.value if isinstance(scope, ScopeType) else scope
        if value == ScopeType.GLOBAL.value:
            return "global"
        if value == ScopeType.CATEGORY.value and category_id is not None:
            return f"category:{category_id}"
        raise ValueError("category_id is required for category scope")

    def coverage(
        self,
        *,
        days: int,
        scope_key: str = "global",
        sort_type: str = "best_selling",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        end = (now or utc_now()).astimezone(UTC)
        start = end - timedelta(days=days)
        interval = self._interval(scope_key, sort_type)
        expected = max(1, math.ceil(days * 24 * 60 / interval))
        successful_runs = list(
            self.session.scalars(
                select(CollectionRun)
                .where(
                    CollectionRun.scope_key == scope_key,
                    CollectionRun.sort_type == sort_type,
                    CollectionRun.status.in_(ELIGIBLE_STATUSES),
                    CollectionRun.items_saved > 0,
                    CollectionRun.started_at >= start,
                    CollectionRun.started_at <= end,
                )
                .order_by(CollectionRun.started_at)
            )
        )
        run_ids = [run.id for run in successful_runs]
        observations: list[RankObservation] = []
        if run_ids:
            observations = list(
                self.session.scalars(
                    select(RankObservation).where(RankObservation.collection_run_id.in_(run_ids))
                )
            )
        product_counts: dict[int, int] = defaultdict(int)
        for observation in observations:
            product_counts[observation.product_id] += 1
        earliest = min((as_utc(row.observed_at) for row in observations), default=None)
        latest = max((as_utc(row.observed_at) for row in observations), default=None)
        if earliest and latest:
            observed_seconds = max(
                interval * 60,
                (latest - earliest).total_seconds() + interval * 60,
            )
            temporal_percent = min(100.0, observed_seconds / (days * 86400) * 100)
        else:
            temporal_percent = 0.0
        schedule_percent = min(100.0, len(successful_runs) / expected * 100)
        coverage_percent = round(min(temporal_percent, schedule_percent), 1)
        complete = coverage_percent >= 95.0 and len(successful_runs) >= expected
        if not observations:
            label = "داده کافی برای مقایسه وجود ندارد"
        elif complete:
            label = "داده تاریخی ثبت‌شده"
        else:
            label = "تاریخچه کامل نیست"
        return {
            "window_start": start,
            "window_end": end,
            "window_days": days,
            "expected_runs": expected,
            "successful_runs": len(successful_runs),
            "failed_runs_excluded": self._failed_run_count(scope_key, sort_type, start, end),
            "unique_products": len(product_counts),
            "products_with_sufficient_history": sum(
                1 for count in product_counts.values() if count >= 2
            ),
            "coverage_percent": coverage_percent,
            "schedule_completion_percent": round(schedule_percent, 1),
            "temporal_coverage_percent": round(temporal_percent, 1),
            "earliest_observation": earliest,
            "latest_observation": latest,
            "complete": complete,
            "label": label,
            "interval_minutes": interval,
        }

    def current_rankings(
        self,
        *,
        scope_key: str = "global",
        sort_type: str = "best_selling",
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionRun | None]:
        latest_run = self.session.scalar(
            select(CollectionRun)
            .where(
                CollectionRun.scope_key == scope_key,
                CollectionRun.sort_type == sort_type,
                CollectionRun.status.in_(ELIGIBLE_STATUSES),
                CollectionRun.items_saved > 0,
            )
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(1)
        )
        if not latest_run:
            return [], None
        query = (
            select(RankObservation, Product)
            .join(Product, Product.id == RankObservation.product_id)
            .where(RankObservation.collection_run_id == latest_run.id)
            .order_by(RankObservation.rank_position, Product.id)
        )
        if q:
            query = query.where(Product.title.ilike(f"%{q.strip()}%"))
        rows = self.session.execute(query).all()
        stats = self._observation_stats(scope_key=scope_key, sort_type=sort_type)
        items: list[dict[str, Any]] = []
        for observation, product in rows:
            snapshot = self._latest_snapshot(product.id)
            previous = self.session.scalar(
                select(RankObservation)
                .join(CollectionRun, CollectionRun.id == RankObservation.collection_run_id)
                .where(
                    RankObservation.product_id == product.id,
                    RankObservation.scope_key == scope_key,
                    RankObservation.sort_type == sort_type,
                    RankObservation.observed_at < observation.observed_at,
                    CollectionRun.status.in_(ELIGIBLE_STATUSES),
                    CollectionRun.items_saved > 0,
                )
                .order_by(RankObservation.observed_at.desc(), RankObservation.id.desc())
                .limit(1)
            )
            rank_change = (
                previous.rank_position - observation.rank_position if previous is not None else None
            )
            observation_count, first_observed = stats.get(
                product.id, (1, as_utc(observation.observed_at))
            )
            items.append(
                self._product_item(
                    product,
                    snapshot,
                    current_rank=observation.rank_position,
                    rank_change=rank_change,
                    observation_count=observation_count,
                    first_observed=first_observed or as_utc(observation.observed_at),
                    last_observed=as_utc(observation.observed_at),
                    average_rank=float(observation.rank_position),
                    best_rank=observation.rank_position,
                    presence_rate=100.0,
                    sufficient_history=previous is not None,
                )
            )
        return items, latest_run

    def historical_rankings(
        self,
        *,
        days: int,
        scope_key: str = "global",
        sort_type: str = "best_selling",
        q: str | None = None,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        end = (now or utc_now()).astimezone(UTC)
        start = end - timedelta(days=days)
        run_ids = list(
            self.session.scalars(
                select(CollectionRun.id).where(
                    CollectionRun.scope_key == scope_key,
                    CollectionRun.sort_type == sort_type,
                    CollectionRun.status.in_(ELIGIBLE_STATUSES),
                    CollectionRun.items_saved > 0,
                    CollectionRun.started_at >= start,
                    CollectionRun.started_at <= end,
                )
            )
        )
        coverage = self.coverage(days=days, scope_key=scope_key, sort_type=sort_type, now=end)
        if not run_ids:
            return [], coverage
        query = (
            select(RankObservation, Product)
            .join(Product, Product.id == RankObservation.product_id)
            .where(RankObservation.collection_run_id.in_(run_ids))
            .order_by(
                RankObservation.product_id,
                RankObservation.observed_at,
                RankObservation.id,
            )
        )
        if q:
            query = query.where(Product.title.ilike(f"%{q.strip()}%"))
        grouped: dict[int, tuple[Product, list[RankObservation]]] = {}
        for observation, product in self.session.execute(query):
            if product.id not in grouped:
                grouped[product.id] = (product, [])
            grouped[product.id][1].append(observation)
        opportunities = max(1, len(run_ids))
        items: list[dict[str, Any]] = []
        for product, observations in grouped.values():
            first = observations[0]
            last = observations[-1]
            positions = [observation.rank_position for observation in observations]
            observed_runs = len({observation.collection_run_id for observation in observations})
            improvement = first.rank_position - last.rank_position
            presence = observed_runs / opportunities * 100
            last_at = as_utc(last.observed_at) or end
            normalized_improvement = max(
                -1.0,
                min(1.0, improvement / max(first.rank_position, last.rank_position, 1)),
            )
            presence_component = presence / 100
            observation_component = min(1.0, len(observations) / max(2, opportunities))
            recency_component = max(0.0, 1 - (end - last_at).total_seconds() / (days * 86400))
            trend_score = 100 * (
                0.55 * normalized_improvement
                + 0.25 * presence_component
                + 0.10 * observation_component
                + 0.10 * recency_component
            )
            trend_score = round(max(-100.0, min(100.0, trend_score)), 2)
            snapshot = self._latest_snapshot(product.id)
            item = self._product_item(
                product,
                snapshot,
                current_rank=last.rank_position,
                rank_change=improvement,
                observation_count=len(observations),
                first_observed=as_utc(first.observed_at),
                last_observed=last_at,
                average_rank=round(sum(positions) / len(positions), 2),
                best_rank=min(positions),
                presence_rate=round(presence, 2),
                sufficient_history=len(observations) >= 2,
            )
            item.update(
                {
                    "start_rank": first.rank_position,
                    "end_rank": last.rank_position,
                    "rank_improvement": improvement,
                    "trend_score": trend_score,
                    "trend_components": {
                        "normalized_rank_improvement": round(normalized_improvement, 4),
                        "presence": round(presence_component, 4),
                        "observation_confidence": round(observation_component, 4),
                        "recency": round(recency_component, 4),
                    },
                    "trend_formula": self.TREND_FORMULA,
                }
            )
            items.append(item)
        items.sort(
            key=lambda item: (
                -int(item["sufficient_history"]),
                -float(item["trend_score"]),
                -int(item["rank_improvement"]),
                int(item["current_rank"]),
                int(item["id"]),
            )
        )
        return items, coverage

    def filtered_rankings(
        self,
        *,
        period: str,
        scope_key: str,
        sort_type: str,
        q: str | None,
        sort: str,
        limit: int,
        offset: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if period == "current":
            items, run = self.current_rankings(scope_key=scope_key, sort_type=sort_type, q=q)
            coverage: dict[str, Any] | None = None
            observed_at = as_utc(run.started_at) if run else None
        else:
            days = PERIOD_DAYS[period]
            items, coverage = self.historical_rankings(
                days=days,
                scope_key=scope_key,
                sort_type=sort_type,
                q=q,
                now=now,
            )
            observed_at = coverage["latest_observation"]
        items = self._sort_items(items, sort)
        total = len(items)
        return {
            "items": items[offset : offset + limit],
            "pagination": {"limit": limit, "offset": offset, "total": total},
            "period": period,
            "scope_key": scope_key,
            "sort_type": sort_type,
            "observed_at": observed_at,
            "coverage": coverage,
            "data_basis": (
                "current_observed_ranking"
                if period == "current"
                else "stored_observed_ranking_history"
            ),
        }

    def trends(
        self,
        *,
        days: int,
        scope_key: str,
        sort_type: str,
        limit: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        items, coverage = self.historical_rankings(
            days=days, scope_key=scope_key, sort_type=sort_type, now=now
        )
        eligible = [
            item for item in items if item["sufficient_history"] and item["rank_improvement"] > 0
        ]
        eligible.sort(
            key=lambda item: (
                -item["rank_improvement"],
                -item["trend_score"],
                item["current_rank"],
                item["id"],
            )
        )
        return {
            "items": eligible[:limit],
            "coverage": coverage,
            "indicator_name": "ranking_based_trend_indicator",
            "not_sales_growth": True,
            "formula": self.TREND_FORMULA,
        }

    def product_detail(self, product_id: int) -> dict[str, Any] | None:
        product = self.session.get(Product, product_id)
        if not product:
            return None
        # The window keeps the newest rows, not the oldest: the detail view
        # answers "what is the latest known price and rank", so the newest
        # observations are the ones that matter.
        snapshots = list(
            self.session.scalars(
                select(Snapshot)
                .where(Snapshot.product_id == product_id, Snapshot.price_toman.is_not(None))
                .order_by(Snapshot.observed_at.desc(), Snapshot.id.desc())
                .limit(500)
            )
        )
        snapshots.reverse()
        rankings = list(
            self.session.scalars(
                select(RankObservation)
                .join(CollectionRun, CollectionRun.id == RankObservation.collection_run_id)
                .where(
                    RankObservation.product_id == product_id,
                    CollectionRun.status.in_(ELIGIBLE_STATUSES),
                    CollectionRun.items_saved > 0,
                )
                .order_by(RankObservation.observed_at.desc(), RankObservation.id.desc())
                .limit(500)
            )
        )
        rankings.reverse()
        scopes = sorted({(row.scope_key, row.sort_type) for row in rankings})
        coverage = {
            key: {
                period: self.coverage(days=days, scope_key=key, sort_type=method)
                for period, days in PERIOD_DAYS.items()
            }
            for key, method in scopes
        }
        latest_snapshot = self._latest_snapshot(product_id)
        return {
            "id": product.id,
            "external_id": product.external_id,
            "identity_source": product.identity_source,
            "title": product.title,
            "url": product.url,
            "image_url": product.image_url,
            "category_id": product.category_id,
            "first_seen_at": as_utc(product.first_seen_at),
            "last_seen_at": as_utc(product.last_seen_at),
            "latest_snapshot": self._snapshot_dict(latest_snapshot),
            "price_history": [self._snapshot_dict(row) for row in snapshots],
            "ranking_history": [
                {
                    "observed_at": as_utc(row.observed_at),
                    "scope_type": row.scope_type.value,
                    "scope_id": row.scope_id,
                    "scope_key": row.scope_key,
                    "sort_type": row.sort_type,
                    "rank_position": row.rank_position,
                    "collection_run_id": row.collection_run_id,
                }
                for row in rankings
            ],
            "coverage": coverage,
            "history_limits": {
                "price": "MCP imports cover about 30 days per variant when explicitly collected",
                "ranking": "starts with DigiScope collection; no upstream historical ranking exists",
            },
        }

    def dashboard(self, *, now: datetime | None = None) -> dict[str, Any]:
        current, latest_run = self.current_rankings()
        coverage_7 = self.coverage(days=7, now=now)
        coverage_30 = self.coverage(days=30, now=now)
        trends = self.trends(days=7, scope_key="global", sort_type="best_selling", limit=5, now=now)
        latest_any = self.session.scalar(
            select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(1)
        )
        interval = self._interval("global", "best_selling")
        latest_success_at = (
            as_utc(latest_run.finished_at or latest_run.started_at) if latest_run else None
        )
        reference = (now or utc_now()).astimezone(UTC)
        stale = bool(
            latest_success_at
            and reference - latest_success_at > timedelta(minutes=max(interval * 2, 60))
        )
        if latest_any and latest_any.status == CollectionStatus.FAILED:
            health = "error"
        elif not latest_run:
            health = "no_data"
        elif stale:
            health = "stale"
        elif latest_run.status == CollectionStatus.PARTIAL:
            health = "warning"
        else:
            health = "healthy"
        monitored_categories = (
            self.session.scalar(
                select(func.count(CollectionScope.id)).where(
                    CollectionScope.enabled.is_(True),
                    CollectionScope.scope_type == ScopeType.CATEGORY,
                )
            )
            or 0
        )
        return {
            "latest_successful_collection_at": latest_success_at,
            "latest_collection_status": latest_any.status.value if latest_any else None,
            "collection_health": health,
            "data_stale": stale,
            "monitored_products": self.session.scalar(select(func.count(Product.id))) or 0,
            "known_categories": self.session.scalar(select(func.count(Category.id))) or 0,
            "monitored_categories": monitored_categories,
            "ranking_observations": self.session.scalar(select(func.count(RankObservation.id)))
            or 0,
            "latest_current_best_sellers": current[:10],
            "top_ranking_improvements": trends["items"],
            "coverage": {"7d": coverage_7, "30d": coverage_30},
            "demo_data": bool(
                self.session.scalar(
                    select(Snapshot.id).where(Snapshot.source.like("demo:%")).limit(1)
                )
            ),
            "terminology": {
                "ranking": "current observed ranking",
                "trend": "ranking-based trend indicator, not sales growth",
            },
        }

    def collection_status(self, *, limit: int = 20) -> dict[str, Any]:
        runs = list(
            self.session.scalars(
                select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(limit)
            )
        )
        scopes = list(self.session.scalars(select(CollectionScope).order_by(CollectionScope.id)))
        return {
            "runs": [
                {
                    "id": run.id,
                    "started_at": as_utc(run.started_at),
                    "finished_at": as_utc(run.finished_at),
                    "status": run.status.value,
                    "scope_type": run.scope_type.value,
                    "scope_key": run.scope_key,
                    "category_id": run.category_id,
                    "sort_type": run.sort_type,
                    "items_fetched": run.items_fetched,
                    "items_saved": run.items_saved,
                    "duration_ms": run.duration_ms,
                    "error_message": run.error_message,
                    "source_metadata": run.source_metadata,
                }
                for run in runs
            ],
            "scopes": [
                {
                    "id": scope.id,
                    "scope_type": scope.scope_type.value,
                    "scope_key": scope.scope_key,
                    "category_id": scope.category_id,
                    "sort_type": scope.sort_type,
                    "enabled": scope.enabled,
                    "interval_minutes": scope.interval_minutes,
                    "last_success_at": as_utc(scope.last_success_at),
                    "last_error_at": as_utc(scope.last_error_at),
                }
                for scope in scopes
            ],
        }

    def _latest_snapshot(self, product_id: int) -> Snapshot | None:
        return self.session.scalar(
            select(Snapshot)
            .where(Snapshot.product_id == product_id)
            .order_by(Snapshot.observed_at.desc(), Snapshot.id.desc())
            .limit(1)
        )

    def _observation_stats(
        self, *, scope_key: str, sort_type: str
    ) -> dict[int, tuple[int, datetime | None]]:
        """Observed count and first observation per product in one scope.

        The current list reports how often each product was actually observed
        in the scope, not a placeholder of one.
        """

        rows = self.session.execute(
            select(
                RankObservation.product_id,
                func.count(RankObservation.id),
                func.min(RankObservation.observed_at),
            )
            .join(CollectionRun, CollectionRun.id == RankObservation.collection_run_id)
            .where(
                RankObservation.scope_key == scope_key,
                RankObservation.sort_type == sort_type,
                CollectionRun.status.in_(ELIGIBLE_STATUSES),
                CollectionRun.items_saved > 0,
            )
            .group_by(RankObservation.product_id)
        ).all()
        return {
            product_id: (int(count), as_utc(first_observed))
            for product_id, count, first_observed in rows
        }

    @staticmethod
    def _snapshot_dict(snapshot: Snapshot | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        return {
            "observed_at": as_utc(snapshot.observed_at),
            "price_toman": snapshot.price_toman,
            "discount_percent": snapshot.discount_percent,
            "rating_stars": snapshot.rating_stars,
            "rating_count": snapshot.rating_count,
            "availability_status": snapshot.availability_status,
            "currency_unit": snapshot.currency_unit,
            "source": snapshot.source,
            "variant_key": snapshot.variant_key,
            "seller": snapshot.seller,
            "warranty": snapshot.warranty,
            "is_historical_import": snapshot.is_historical_import,
        }

    def _product_item(
        self,
        product: Product,
        snapshot: Snapshot | None,
        **ranking: Any,
    ) -> dict[str, Any]:
        return {
            "id": product.id,
            "external_id": product.external_id,
            "title": product.title,
            "url": product.url,
            "image_url": product.image_url,
            "category_id": product.category_id,
            "price_toman": snapshot.price_toman if snapshot else None,
            "discount_percent": snapshot.discount_percent if snapshot else None,
            "rating_stars": snapshot.rating_stars if snapshot else None,
            "rating_count": snapshot.rating_count if snapshot else None,
            "availability_status": snapshot.availability_status if snapshot else None,
            "last_snapshot_at": as_utc(snapshot.observed_at) if snapshot else None,
            **ranking,
        }

    def _interval(self, scope_key: str, sort_type: str) -> int:
        configured = self.session.scalar(
            select(CollectionScope.interval_minutes).where(
                CollectionScope.scope_key == scope_key,
                CollectionScope.sort_type == sort_type,
            )
        )
        return configured or self.default_interval_minutes

    def _failed_run_count(
        self,
        scope_key: str,
        sort_type: str,
        start: datetime,
        end: datetime,
    ) -> int:
        return int(
            self.session.scalar(
                select(func.count(CollectionRun.id)).where(
                    CollectionRun.scope_key == scope_key,
                    CollectionRun.sort_type == sort_type,
                    CollectionRun.status == CollectionStatus.FAILED,
                    CollectionRun.started_at >= start,
                    CollectionRun.started_at <= end,
                )
            )
            or 0
        )

    @staticmethod
    def _sort_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        aliases = {
            "rank": "current_rank",
            "rank_improvement": "rank_improvement",
            "price": "price_toman",
            "rating": "rating_stars",
            "observations": "observation_count",
            "last_observed": "last_observed",
            "trend": "trend_score",
        }
        key = aliases.get(field, "current_rank")
        if not AnalyticsService._can_order(items, key):
            # The requested field cannot separate the rows in this period
            # (it is missing everywhere, or identical everywhere). Keeping the
            # observed rank order is honest; an arbitrary id order is not.
            key, descending = "current_rank", False

        def value(item: dict[str, Any]) -> tuple[bool, Any, int]:
            raw = item.get(key)
            # Null values always sort last, independent of direction.
            if isinstance(raw, datetime):
                sortable: Any = raw.timestamp()
            else:
                sortable = raw
            if sortable is None:
                return True, 0, int(item["id"])
            adjusted = -sortable if descending else sortable
            return False, adjusted, int(item["id"])

        return sorted(items, key=value)

    @staticmethod
    def _can_order(items: list[dict[str, Any]], key: str) -> bool:
        """True when the field holds at least two distinct values."""

        seen: list[Any] = []
        for item in items:
            raw = item.get(key)
            if raw is None:
                continue
            marker = raw.timestamp() if isinstance(raw, datetime) else raw
            if marker not in seen:
                seen.append(marker)
        return len(seen) > 1
