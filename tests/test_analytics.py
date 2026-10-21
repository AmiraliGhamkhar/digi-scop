from __future__ import annotations

from sqlalchemy import select

from app.models import Product
from app.services.analytics_service import AnalyticsService


def by_external(items, external_id):
    return next(item for item in items if item["external_id"] == external_id)


def test_improving_worsening_and_unchanged_rank_calculations(session_factory, seeded_market):
    with session_factory() as db:
        service = AnalyticsService(db, default_interval_minutes=1440)
        items, _ = service.historical_rankings(days=7, now=seeded_market["now"])
    improving = by_external(items, "201")
    worsening = by_external(items, "202")
    unchanged = by_external(items, "203")
    assert (improving["start_rank"], improving["end_rank"], improving["rank_improvement"]) == (
        20,
        5,
        15,
    )
    assert worsening["rank_improvement"] == -7
    assert unchanged["rank_improvement"] == 0
    assert improving["average_rank"] == 12.5
    assert improving["best_rank"] == 5


def test_missing_observation_presence_excludes_failed_runs(session_factory, seeded_market):
    with session_factory() as db:
        items, coverage = AnalyticsService(db).historical_rankings(days=7, now=seeded_market["now"])
    missing = by_external(items, "204")
    assert missing["observation_count"] == 3
    assert missing["presence_rate"] == 75.0
    assert coverage["successful_runs"] == 4
    assert coverage["failed_runs_excluded"] == 1


def test_incomplete_period_is_never_marked_complete(session_factory, seeded_market):
    with session_factory() as db:
        service = AnalyticsService(db)
        seven = service.coverage(days=7, now=seeded_market["now"])
        thirty = service.coverage(days=30, now=seeded_market["now"])
    assert seven["expected_runs"] == 7
    assert seven["coverage_percent"] < 100
    assert seven["complete"] is False
    assert seven["label"] == "تاریخچه کامل نیست"
    assert thirty["expected_runs"] == 30
    assert thirty["coverage_percent"] < seven["coverage_percent"]


def test_category_observation_does_not_duplicate_product_identity(session_factory, seeded_market):
    category_key = f"category:{seeded_market['category_a']}"
    with session_factory() as db:
        service = AnalyticsService(db)
        global_items, _ = service.historical_rankings(days=7, now=seeded_market["now"])
        category_items, _ = service.historical_rankings(
            days=7, scope_key=category_key, now=seeded_market["now"]
        )
        product_count = len(list(db.scalars(select(Product))))
    assert product_count == 5
    assert by_external(global_items, "201")["id"] == by_external(category_items, "201")["id"]
    assert all(item["sufficient_history"] is False for item in category_items)


def test_trends_are_ranking_indicators_not_sales_growth(session_factory, seeded_market):
    with session_factory() as db:
        result = AnalyticsService(db).trends(
            days=7, scope_key="global", sort_type="best_selling", limit=10, now=seeded_market["now"]
        )
    assert result["not_sales_growth"] is True
    assert result["items"][0]["external_id"] == "201"
    assert result["items"][0]["rank_improvement"] == 15
    assert "normalized_rank_improvement" in result["items"][0]["trend_components"]
    assert "0.55" in result["formula"]


def test_current_list_uses_latest_successful_observed_run(session_factory, seeded_market):
    with session_factory() as db:
        items, run = AnalyticsService(db).current_rankings()
    assert run.status.value == "success"
    assert by_external(items, "201")["current_rank"] == 5
    assert by_external(items, "201")["rank_change"] == 5
    assert all(item["observation_count"] == 1 for item in items)


def test_price_history_without_ranking_history_stays_separate(session_factory, seeded_market):
    price_only_id = seeded_market["products"][4]
    with session_factory() as db:
        service = AnalyticsService(db)
        items, _ = service.historical_rankings(days=30, now=seeded_market["now"])
        detail = service.product_detail(price_only_id)
    assert all(item["id"] != price_only_id for item in items)
    assert detail["ranking_history"] == []
    assert len(detail["price_history"]) == 1
    assert detail["price_history"][0]["is_historical_import"] is True


def test_empty_coverage_is_explicit(session_factory):
    with session_factory() as db:
        coverage = AnalyticsService(db).coverage(days=7)
    assert coverage["coverage_percent"] == 0
    assert coverage["complete"] is False
    assert coverage["label"] == "داده کافی برای مقایسه وجود ندارد"
