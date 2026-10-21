from __future__ import annotations

from app.mcp.normalizer import normalize_ranking_payload


def test_unparsable_numbers_cost_the_number_not_the_product():
    payload = {
        "items": [
            {"id": 1, "title": "سیلیکون", "price_toman": "نامشخص", "discount_percent": "زیاد"},
            {"id": 2, "title": "میکروفون", "price_toman": "12,000,000", "rating_stars": "4.5"},
        ]
    }
    batch = normalize_ranking_payload(payload)
    assert [product.external_id for product in batch.products] == ["1", "2"]
    assert batch.products[0].price_toman is None
    assert batch.products[0].discount_percent is None
    assert batch.products[1].price_toman == 12_000_000
    assert batch.products[1].rating_stars == 4.5
    assert batch.warnings == []


def test_formatted_and_persian_numbers_are_read_as_numbers():
    payload = {
        "items": [
            {
                "id": 3,
                "title": "کیبورد",
                "price_toman": "۱۲٬۰۰۰٬۰۰۰",
                "rating_count": "1,024",
                "in_stock": "true",
            }
        ]
    }
    batch = normalize_ranking_payload(payload)
    product = batch.products[0]
    assert product.price_toman == 12_000_000
    assert product.rating_count == 1024
    assert product.availability_status == "in_stock"


def test_an_unusable_id_falls_back_to_the_canonical_url():
    payload = {
        "items": [
            {
                "id": {"value": 5},
                "title": "کالا",
                "url": "https://www.digikala.com/product/dkp-777/",
            }
        ]
    }
    batch = normalize_ranking_payload(payload)
    assert batch.products[0].external_id == "777"
    assert batch.products[0].identity_source == "canonical_url_id"


def test_a_card_without_an_identity_is_still_reported_as_a_warning():
    payload = {"items": [{"title": "بی‌هویت"}]}
    batch = normalize_ranking_payload(payload)
    assert batch.products == []
    assert len(batch.warnings) == 1
    assert "stable id" in batch.warnings[0]
