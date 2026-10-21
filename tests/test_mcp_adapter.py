from __future__ import annotations

import pytest

from app.mcp.adapter import DigikalaMCPAdapter
from app.mcp.client import MCPProtocolError
from app.models import ScopeType


class StubClient:
    def __init__(self, responses=None, tools=None):
        self.responses = list(responses or [])
        self.tools = tools or []
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses.pop(0)

    async def list_tools(self):
        return self.tools

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_global_best_selling_honors_verified_30_item_cap():
    payload = {"items": [{"id": i, "title": f"p{i}"} for i in range(1, 31)]}
    client = StubClient([payload])
    adapter = DigikalaMCPAdapter(client)  # type: ignore[arg-type]
    batch = await adapter.fetch_ranking(
        scope_type=ScopeType.GLOBAL, category_external_id=None, limit=50
    )
    assert client.calls == [("best_selling", {"limit": 30})]
    assert len(batch.products) == 30
    assert batch.metadata["truncated_by_upstream_contract"] is True
    assert any("maximum of 30" in warning for warning in batch.warnings)


@pytest.mark.asyncio
async def test_category_uses_documented_pagination_and_total_slots_for_ranks():
    page1 = {
        "total_slots": 3,
        "total_pages": 2,
        "items": [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}],
        "category": {"id": 11, "title": "mobile"},
    }
    page2 = {
        "total_slots": 2,
        "total_pages": 2,
        "items": [{"id": 3, "title": "c"}, {"id": 4, "title": "d"}],
    }
    client = StubClient([page1, page2])
    adapter = DigikalaMCPAdapter(client)  # type: ignore[arg-type]
    batch = await adapter.fetch_ranking(
        scope_type=ScopeType.CATEGORY, category_external_id="11", limit=5
    )
    assert [item.rank_position for item in batch.products] == [1, 2, 4, 5]
    assert client.calls[0][0] == "browse_category"
    assert client.calls[0][1]["sort"] == "best_selling"
    assert client.calls[1][1]["page"] == 2
    assert batch.categories[0].external_id == "11"


@pytest.mark.asyncio
async def test_price_chart_keeps_variant_specific_points():
    client = StubClient(
        [
            {
                "window_days": 30,
                "series": [
                    {
                        "variant_id": 1,
                        "color": "red",
                        "points": [
                            {"day": "2026-10-01", "price_toman": 100, "seller": {"name": "s"}}
                        ],
                    },
                    {
                        "variant_id": 2,
                        "color": "blue",
                        "points": [{"day": "2026-10-01", "price_toman": 90}],
                    },
                ],
            }
        ]
    )
    adapter = DigikalaMCPAdapter(client)  # type: ignore[arg-type]
    result = await adapter.fetch_price_history("123")
    assert len(result.points) == 2
    assert result.points[0].variant_key != result.points[1].variant_key
    assert result.metadata["window_days"] == 30
    assert client.calls == [("product_price_chart", {"id": 123})]


@pytest.mark.asyncio
async def test_tool_discovery_requires_relevant_contracts():
    client = StubClient(tools=[{"name": "best_selling"}])
    adapter = DigikalaMCPAdapter(client)  # type: ignore[arg-type]
    with pytest.raises(MCPProtocolError, match="missing required"):
        await adapter.discover()


@pytest.mark.asyncio
async def test_non_numeric_category_and_product_ids_are_not_guessed():
    adapter = DigikalaMCPAdapter(StubClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="numeric category"):
        await adapter.fetch_ranking(
            scope_type=ScopeType.CATEGORY, category_external_id="phones", limit=10
        )
    with pytest.raises(ValueError, match="numeric Digikala"):
        await adapter.fetch_price_history("url:hash")
