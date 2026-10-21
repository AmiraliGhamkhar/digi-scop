"""Normalize volatile MCP payloads into strict observed facts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class NormalizationError(ValueError):
    pass


class _Card(BaseModel):
    model_config = ConfigDict(extra="allow", strict=False)

    id: int | str | None = None
    title: str
    url: str | None = None
    image_url: str | None = None
    price_toman: int | float | None = None
    discount_percent: int | float | None = None
    rating_stars: int | float | None = None
    rating_count: int | None = None
    in_stock: bool | None = None
    seller: str | None = None

    @field_validator("title")
    @classmethod
    def title_is_real(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("empty title")
        return value[:1000]


@dataclass(slots=True)
class NormalizedCategory:
    external_id: str
    title: str
    url: str | None = None
    parent_external_id: str | None = None


@dataclass(slots=True)
class NormalizedProduct:
    external_id: str
    identity_source: str
    title: str
    url: str | None
    image_url: str | None
    price_toman: int | None
    discount_percent: float | None
    rating_stars: float | None
    rating_count: int | None
    availability_status: str | None
    seller: str | None
    rank_position: int


@dataclass(slots=True)
class NormalizedRankingBatch:
    products: list[NormalizedProduct]
    categories: list[NormalizedCategory] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedPricePoint:
    observed_at: datetime
    price_toman: int
    variant_key: str
    seller: str | None
    warranty: str | None
    original_day: str


_DKP_RE = re.compile(r"(?:^|/)dkp-(\d+)(?:/|$)", re.IGNORECASE)


def canonical_product_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"digikala.com", "www.digikala.com"}:
        return None
    if not _DKP_RE.search(parsed.path):
        return None
    clean_path = parsed.path.rstrip("/") + "/"
    return urlunparse(("https", "www.digikala.com", clean_path, "", "", ""))


def _identity(card_id: int | str | None, url: str | None) -> tuple[str, str]:
    if card_id is not None and str(card_id).strip():
        return str(card_id).strip(), "upstream_id"
    canonical = canonical_product_url(url)
    if canonical:
        match = _DKP_RE.search(urlparse(canonical).path)
        if match:
            return match.group(1), "canonical_url_id"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]
        return f"url:{digest}", "canonical_url_hash"
    raise NormalizationError("product has neither a stable id nor a verified canonical URL")


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def _bounded_float(value: Any, minimum: float, maximum: float) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if minimum <= number <= maximum else None


def _nested_image(raw: dict[str, Any]) -> str | None:
    direct = raw.get("image_url") or raw.get("image")
    if isinstance(direct, str):
        return direct
    images = raw.get("images")
    if isinstance(images, dict):
        for key in ("main", "webp_url", "url"):
            candidate = images.get(key)
            if isinstance(candidate, str):
                return candidate
            if isinstance(candidate, dict):
                for nested_key in ("url", "webp_url", "storage_ids"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, str):
                        return nested
                    if isinstance(nested, list) and nested and isinstance(nested[0], str):
                        return nested[0]
    return None


def _normalize_categories(payload: dict[str, Any]) -> list[NormalizedCategory]:
    raw_values: list[Any] = []
    for key in ("categories", "subcategories", "sub_categories"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
    category = payload.get("category")
    if isinstance(category, dict):
        raw_values.append(category)
    seen: set[str] = set()
    result: list[NormalizedCategory] = []
    for raw in raw_values:
        if not isinstance(raw, dict):
            continue
        external = raw.get("id") or raw.get("category_id")
        title = raw.get("title") or raw.get("name")
        if external is None or not isinstance(title, str) or not title.strip():
            continue
        key = str(external)
        if key in seen:
            continue
        seen.add(key)
        parent = raw.get("parent_id")
        result.append(
            NormalizedCategory(
                external_id=key,
                title=" ".join(title.split())[:500],
                url=raw.get("url") if isinstance(raw.get("url"), str) else None,
                parent_external_id=str(parent) if parent is not None else None,
            )
        )
    return result


def normalize_ranking_payload(payload: Any, *, rank_offset: int = 0) -> NormalizedRankingBatch:
    if not isinstance(payload, dict):
        raise NormalizationError("ranking tool output must be a JSON object")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise NormalizationError("ranking tool output has no items list")

    products: list[NormalizedProduct] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"item {rank_offset + index}: expected an object")
            continue
        try:
            card = _Card.model_validate(raw)
            canonical = canonical_product_url(card.url)
            external_id, identity_source = _identity(card.id, card.url)
        except (ValidationError, NormalizationError) as exc:
            warnings.append(f"item {rank_offset + index}: {str(exc)[:160]}")
            continue
        if external_id in seen:
            warnings.append(f"item {rank_offset + index}: duplicate product id {external_id}")
            continue
        seen.add(external_id)
        price = _nonnegative_int(card.price_toman)
        discount = _bounded_float(card.discount_percent, 0, 100)
        rating = _bounded_float(card.rating_stars, 0, 5)
        rating_count = _nonnegative_int(card.rating_count)
        availability = (
            "in_stock"
            if card.in_stock is True
            else "out_of_stock"
            if card.in_stock is False
            else None
        )
        products.append(
            NormalizedProduct(
                external_id=external_id,
                identity_source=identity_source,
                title=card.title,
                # Only persist a verified canonical Digikala URL. An upstream
                # string on another host is not presented as a product link.
                url=canonical,
                image_url=_nested_image(raw),
                price_toman=price,
                discount_percent=discount,
                rating_stars=rating,
                rating_count=rating_count,
                availability_status=availability,
                seller=card.seller,
                rank_position=rank_offset + index,
            )
        )

    safe_metadata: dict[str, Any] = {}
    for key in (
        "returned",
        "fetched",
        "total_items_estimate",
        "total_items_scope",
        "total_pages",
        "total_slots",
        "page",
        "page_clamped",
        "page_requested",
        "items_from_search",
        "categories_truncated",
        "window_days",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe_metadata[key] = value
    return NormalizedRankingBatch(
        products=products,
        categories=_normalize_categories(payload),
        metadata=safe_metadata,
        warnings=warnings,
    )


def _parse_day(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
            return datetime.combine(parsed_date, time.min, tzinfo=UTC)
        except ValueError:
            return None


def normalize_price_chart(
    payload: Any,
) -> tuple[list[NormalizedPricePoint], list[str], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise NormalizationError("product_price_chart output must be a JSON object")
    raw_series: Any = None
    for key in ("series", "price_series", "charts", "variants"):
        if isinstance(payload.get(key), (list, dict)):
            raw_series = payload[key]
            break
    if isinstance(raw_series, dict):
        series_values = [
            {**value, "_series_key": key} if isinstance(value, dict) else value
            for key, value in raw_series.items()
        ]
    elif isinstance(raw_series, list):
        series_values = raw_series
    else:
        raise NormalizationError("product_price_chart output has no recognized series collection")

    result: list[NormalizedPricePoint] = []
    warnings: list[str] = []
    seen: set[tuple[datetime, str]] = set()
    for series_index, series in enumerate(series_values, start=1):
        if not isinstance(series, dict):
            warnings.append(f"price series {series_index}: expected an object")
            continue
        identity_parts = [
            series.get("id"),
            series.get("variant_id"),
            series.get("color"),
            series.get("size"),
            series.get("title"),
            series.get("_series_key"),
        ]
        readable = [str(part).strip() for part in identity_parts if part not in (None, "")]
        variant_key = "|".join(readable)[:255] if readable else f"series:{series_index}"
        points = series.get("points")
        if not isinstance(points, list):
            warnings.append(f"price series {series_index}: no points list")
            continue
        for point_index, point in enumerate(points, start=1):
            if not isinstance(point, dict):
                warnings.append(
                    f"price series {series_index} point {point_index}: expected an object"
                )
                continue
            observed_at = _parse_day(
                point.get("day") or point.get("date") or point.get("timestamp")
            )
            price = _nonnegative_int(point.get("price_toman"))
            if observed_at is None or price is None:
                warnings.append(
                    f"price series {series_index} point {point_index}: invalid day or Toman price"
                )
                continue
            unique = (observed_at, variant_key)
            if unique in seen:
                continue
            seen.add(unique)
            seller_raw = point.get("seller")
            seller = (
                seller_raw
                if isinstance(seller_raw, str)
                else seller_raw.get("name")
                if isinstance(seller_raw, dict) and isinstance(seller_raw.get("name"), str)
                else None
            )
            warranty_raw = point.get("warranty")
            warranty = (
                warranty_raw
                if isinstance(warranty_raw, str)
                else warranty_raw.get("title")
                if isinstance(warranty_raw, dict) and isinstance(warranty_raw.get("title"), str)
                else None
            )
            original_day = str(point.get("day") or point.get("date") or point.get("timestamp"))
            result.append(
                NormalizedPricePoint(
                    observed_at=observed_at,
                    price_toman=price,
                    variant_key=variant_key,
                    seller=seller,
                    warranty=warranty,
                    original_day=original_day,
                )
            )
    result.sort(key=lambda point: (point.observed_at, point.variant_key))
    metadata = {
        "window_days": payload.get("window_days"),
        "current_price_toman": _nonnegative_int(payload.get("current_price_toman")),
    }
    return result, warnings, metadata
