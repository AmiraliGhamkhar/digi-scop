"""Replaceable adapter between DigiScope and the Digikala MCP contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.mcp.client import MCPClient, MCPProtocolError
from app.mcp.normalizer import (
    NormalizedPricePoint,
    NormalizedRankingBatch,
    normalize_price_chart,
    normalize_ranking_payload,
)
from app.models import ScopeType


@dataclass(slots=True)
class PriceHistoryBatch:
    points: list[NormalizedPricePoint]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MarketDataAdapter(ABC):
    @abstractmethod
    async def fetch_ranking(
        self,
        *,
        scope_type: ScopeType,
        category_external_id: str | None,
        limit: int,
        sort_type: str = "best_selling",
    ) -> NormalizedRankingBatch:
        raise NotImplementedError

    @abstractmethod
    async def fetch_price_history(self, external_product_id: str) -> PriceHistoryBatch:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class DigikalaMCPAdapter(MarketDataAdapter):
    """Adapter using only tool arguments verified in the upstream repository."""

    MCP_LIST_LIMIT: ClassVar[int] = 30
    CATEGORY_SORTS: ClassVar[frozenset[str]] = frozenset(
        {
            "relevance",
            "popular",
            "newest",
            "best_selling",
            "cheapest",
            "expensive",
            "fastest",
            "buyers_choice",
            "featured",
        }
    )
    REQUIRED_TOOLS: ClassVar[frozenset[str]] = frozenset(
        {"best_selling", "browse_category", "search_digikala", "product_price_chart"}
    )

    def __init__(self, client: MCPClient) -> None:
        self.client = client

    async def discover(self) -> dict[str, dict[str, Any]]:
        tools = await self.client.list_tools()
        result = {str(tool.get("name")): tool for tool in tools if tool.get("name")}
        missing = self.REQUIRED_TOOLS - result.keys()
        if missing:
            raise MCPProtocolError(
                f"MCP server is missing required tools: {', '.join(sorted(missing))}"
            )
        return result

    async def fetch_ranking(
        self,
        *,
        scope_type: ScopeType,
        category_external_id: str | None,
        limit: int,
        sort_type: str = "best_selling",
    ) -> NormalizedRankingBatch:
        if not 1 <= limit <= 50:
            raise ValueError("ranking limit must be between 1 and 50")
        if scope_type == ScopeType.GLOBAL:
            if sort_type != "best_selling":
                raise ValueError("the verified global tool only supports the best_selling method")
            requested = min(limit, self.MCP_LIST_LIMIT)
            payload = await self.client.call_tool("best_selling", {"limit": requested})
            batch = normalize_ranking_payload(payload)
            batch.metadata.update(
                {
                    "tool": "best_selling",
                    "requested_limit": limit,
                    "upstream_limit": self.MCP_LIST_LIMIT,
                    "truncated_by_upstream_contract": limit > self.MCP_LIST_LIMIT,
                }
            )
            if limit > self.MCP_LIST_LIMIT:
                batch.warnings.append(
                    "best_selling has a documented maximum of 30 and no page argument; "
                    "the requested global top 50 cannot be fully observed"
                )
            batch.products = [
                product for product in batch.products if product.rank_position <= limit
            ]
            return batch

        if scope_type != ScopeType.CATEGORY:
            raise ValueError(f"unsupported scope type: {scope_type}")
        if not category_external_id:
            raise ValueError("category_external_id is required for a category ranking")
        try:
            category_id = int(category_external_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("browse_category requires a numeric category id") from exc
        if sort_type not in self.CATEGORY_SORTS:
            raise ValueError(f"unsupported category sort: {sort_type}")

        products = []
        categories = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {
            "tool": "browse_category",
            "requested_limit": limit,
            "pages_fetched": 0,
        }
        seen_products: set[str] = set()
        offset = 0
        page = 1
        while offset < limit:
            payload = await self.client.call_tool(
                "browse_category",
                {
                    "category_id": category_id,
                    "sort": sort_type,
                    "page": page,
                    "limit": min(self.MCP_LIST_LIMIT, limit - len(products)),
                },
            )
            if not isinstance(payload, dict):
                raise MCPProtocolError("browse_category output is not an object")
            batch = normalize_ranking_payload(payload, rank_offset=offset)
            metadata["pages_fetched"] = page
            metadata.update({f"last_{key}": value for key, value in batch.metadata.items()})
            warnings.extend(batch.warnings)
            categories.extend(batch.categories)
            for product in batch.products:
                if product.external_id not in seen_products and product.rank_position <= limit:
                    seen_products.add(product.external_id)
                    products.append(product)
                elif product.external_id in seen_products:
                    warnings.append(
                        f"page {page}: duplicate product {product.external_id} was not stored twice"
                    )
            raw_items = payload.get("items")
            raw_count = len(raw_items) if isinstance(raw_items, list) else 0
            total_slots = payload.get("total_slots")
            stride = total_slots if isinstance(total_slots, int) and total_slots > 0 else raw_count
            if raw_count == 0 or stride <= 0:
                break
            offset += stride
            total_pages = payload.get("total_pages")
            if isinstance(total_pages, int) and page >= total_pages:
                break
            page += 1
            # At most three pages are needed for a supported top-50 request. The
            # guard protects against an inconsistent upstream pager.
            if page > 3:
                warnings.append("category pagination stopped at the conservative three-page bound")
                break
        products.sort(key=lambda product: product.rank_position)
        return NormalizedRankingBatch(
            products=products,
            categories=_deduplicate_categories(categories),
            metadata=metadata,
            warnings=warnings,
        )

    async def fetch_price_history(self, external_product_id: str) -> PriceHistoryBatch:
        try:
            product_id = int(external_product_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("product_price_chart requires a numeric Digikala product id") from exc
        payload = await self.client.call_tool("product_price_chart", {"id": product_id})
        points, warnings, metadata = normalize_price_chart(payload)
        metadata["tool"] = "product_price_chart"
        return PriceHistoryBatch(points=points, warnings=warnings, metadata=metadata)

    async def close(self) -> None:
        await self.client.close()


class MockMCPAdapter(MarketDataAdapter):
    """Deterministic adapter for tests and explicit development fixtures."""

    def __init__(
        self,
        ranking_payloads: dict[str, dict[str, Any]] | None = None,
        price_payloads: dict[str, dict[str, Any]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.ranking_payloads = ranking_payloads or {}
        self.price_payloads = price_payloads or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch_ranking(
        self,
        *,
        scope_type: ScopeType,
        category_external_id: str | None,
        limit: int,
        sort_type: str = "best_selling",
    ) -> NormalizedRankingBatch:
        key = "global" if scope_type == ScopeType.GLOBAL else f"category:{category_external_id}"
        self.calls.append(("ranking", {"scope": key, "limit": limit, "sort": sort_type}))
        if key in self.errors:
            raise self.errors[key]
        payload = self.ranking_payloads.get(key, {"items": []})
        batch = normalize_ranking_payload(payload)
        batch.products = [product for product in batch.products if product.rank_position <= limit]
        batch.metadata.update({"tool": "mock", "requested_limit": limit, "fixture": True})
        return batch

    async def fetch_price_history(self, external_product_id: str) -> PriceHistoryBatch:
        key = f"price:{external_product_id}"
        self.calls.append(("price", {"external_id": external_product_id}))
        if key in self.errors:
            raise self.errors[key]
        payload = self.price_payloads.get(external_product_id, {"series": []})
        points, warnings, metadata = normalize_price_chart(payload)
        metadata.update({"tool": "mock", "fixture": True})
        return PriceHistoryBatch(points=points, warnings=warnings, metadata=metadata)


def _deduplicate_categories(categories):  # type: ignore[no-untyped-def]
    seen: set[str] = set()
    result = []
    for category in categories:
        if category.external_id not in seen:
            seen.add(category.external_id)
            result.append(category)
    return result
