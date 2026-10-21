from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_readiness_and_dashboard(client):
    health = client.get("/health")
    ready = client.get("/ready")
    dashboard = client.get("/api/dashboard")
    assert health.status_code == 200 and health.json()["database"] == "ready"
    assert ready.status_code == 200
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["monitored_products"] == 5
    assert payload["ranking_observations"] > 0
    assert payload["coverage"]["30d"]["complete"] is False
    assert payload["terminology"]["ranking"] == "current observed ranking"


def test_categories_return_parent_child_contract(client, seeded_market):
    response = client.get("/api/categories")
    assert response.status_code == 200
    ids = {category["id"] for category in response.json()}
    assert seeded_market["category_a"] in ids
    assert all("children" in category for category in response.json())


def test_products_search_pagination_period_and_category_filter(client, seeded_market):
    search = client.get("/api/products", params={"q": "رو به رشد", "period": "7d"})
    assert search.status_code == 200
    assert search.json()["pagination"]["total"] == 1
    assert search.json()["items"][0]["external_id"] == "201"

    page = client.get("/api/products", params={"limit": 1, "offset": 1})
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["pagination"]["offset"] == 1

    category = client.get("/api/products", params={"category_id": seeded_market["category_a"]})
    assert category.status_code == 200
    assert category.json()["pagination"]["total"] == 2
    assert category.json()["scope_key"] == f"category:{seeded_market['category_a']}"


def test_rankings_current_and_historical_data_basis(client):
    current = client.get("/api/rankings", params={"period": "current", "limit": 10})
    history = client.get("/api/rankings", params={"period": "7d", "limit": 10})
    assert current.status_code == 200
    assert current.json()["data_basis"] == "current_observed_ranking"
    assert current.json()["coverage"] is None
    assert history.status_code == 200
    assert history.json()["data_basis"] == "stored_observed_ranking_history"
    assert history.json()["coverage"]["complete"] is False
    assert history.json()["items"][0]["observation_count"] >= 2


def test_current_rankings_report_the_observed_count(client):
    response = client.get("/api/rankings", params={"period": "current", "limit": 10})
    assert response.status_code == 200
    counts = {item["external_id"]: item["observation_count"] for item in response.json()["items"]}
    assert counts["201"] == 4
    assert counts["204"] == 3


def test_query_validation_and_scope_errors(client):
    assert client.get("/api/rankings", params={"period": "1y"}).status_code == 422
    assert client.get("/api/rankings", params={"limit": 51}).status_code == 422
    assert client.get("/api/rankings", params={"scope": "category"}).status_code == 422
    assert (
        client.get("/api/rankings", params={"scope": "category", "category_id": 99999}).status_code
        == 404
    )
    assert client.get("/api/products", params={"sort": "DROP TABLE products"}).status_code == 422


def test_product_detail_and_missing_product(client, seeded_market):
    product_id = seeded_market["products"][0]
    response = client.get(f"/api/products/{product_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ranking_history"]
    assert payload["price_history"]
    assert "ranking" in payload["history_limits"]
    assert client.get("/api/products/999999").status_code == 404


def test_trends_endpoint_discloses_formula_and_insufficient_data(client, seeded_market):
    response = client.get("/api/market/trends", params={"period": "7d"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["not_sales_growth"] is True
    assert payload["items"][0]["rank_improvement"] > 0
    category = client.get(
        "/api/market/trends",
        params={"scope": "category", "category_id": seeded_market["category_a"]},
    )
    assert category.status_code == 200
    assert category.json()["items"] == []


def test_collection_status_has_runs_errors_and_configured_scopes(client):
    response = client.get("/api/collection/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"]
    assert payload["scopes"]
    assert any(run["status"] == "failed" and run["error_message"] for run in payload["runs"])


def test_manual_collection_requires_auth_and_runs_with_admin_token(client):
    body = {"include_global": True, "limit": 3}
    duplicate = {"include_global": False, "category_ids": [1, 1]}
    assert (
        client.post(
            "/api/collection/run",
            json=duplicate,
            headers={"X-Admin-Token": "test-admin-secret"},
        ).status_code
        == 422
    )
    assert client.post("/api/collection/run", json=body).status_code == 401
    assert (
        client.post(
            "/api/collection/run", json=body, headers={"X-Admin-Token": "wrong"}
        ).status_code
        == 401
    )
    response = client.post(
        "/api/collection/run", json=body, headers={"X-Admin-Token": "test-admin-secret"}
    )
    assert response.status_code == 200
    assert response.json()["outcomes"][0]["items_saved"] == 3
    limited = client.post(
        "/api/collection/run", json=body, headers={"X-Admin-Token": "test-admin-secret"}
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "2"


def test_manual_collection_is_disabled_without_configured_token(settings, engine, mock_adapter):
    no_token = settings.model_copy(update={"admin_token": None})
    app = create_app(no_token, engine=engine, adapter=mock_adapter)
    with TestClient(app) as local:
        response = local.post("/api/collection/run", json={"include_global": True})
    assert response.status_code == 503


def test_csv_export_has_utf8_bom_filters_and_formula_protection(client):
    response = client.get("/api/export.csv", params={"period": "7d", "limit": 50})
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    decoded = response.content.decode("utf-8-sig")
    assert "رتبه مشاهده‌شده" in decoded
    assert "'=فرمول آزمایشی" in decoded
    assert response.headers["x-digiscope-data-basis"] == "stored_observed_ranking_history"
    filtered = client.get("/api/export.csv", params={"q": "رو به رشد", "limit": 10})
    assert "محصول رو به رشد" in filtered.content.decode("utf-8-sig")
    assert "محصول نزولی" not in filtered.content.decode("utf-8-sig")


def test_empty_results_are_valid_and_explicit(empty_client):
    dashboard = empty_client.get("/api/dashboard")
    rankings = empty_client.get("/api/rankings")
    assert dashboard.status_code == 200
    assert dashboard.json()["collection_health"] == "no_data"
    assert rankings.status_code == 200
    assert rankings.json()["items"] == []
    assert rankings.json()["pagination"]["total"] == 0


def test_frontend_is_rtl_responsive_and_uses_api_data(client):
    page = client.get("/")
    css = client.get("/static/css/app.css")
    javascript = client.get("/static/js/app.js")
    assert page.status_code == 200
    assert 'lang="fa" dir="rtl"' in page.text
    assert "/static/vendor/chart.umd.min.js" in page.text
    assert "period-button" in page.text and "category-select" in page.text
    assert "@media(max-width:620px)" in css.text
    assert "api.rankings" in javascript.text
    assert "mock data" not in javascript.text.lower()
    # The export link must not inherit the page size of the table.
    assert "EXPORT_LIMIT = 50" in javascript.text
    assert "params.limit = EXPORT_LIMIT" in javascript.text
    assert page.headers["content-security-policy"].startswith("default-src 'self'")
