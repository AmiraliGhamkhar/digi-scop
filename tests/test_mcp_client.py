from __future__ import annotations

import json

import httpx
import pytest

from app.mcp.client import (
    MCPClient,
    MCPHTTPError,
    MCPProtocolError,
    MCPRateLimitError,
    MCPToolError,
)


def rpc_response(
    request: httpx.Request, result: object, *, headers: dict | None = None
) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": body.get("id"), "result": result},
        headers=headers,
    )


def standard_handler(tool_result: dict | None = None, *, sse: bool = False, structured=None):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((body, dict(request.headers)))
        method = body["method"]
        if method == "initialize":
            return rpc_response(
                request,
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "fixture", "version": "1"},
                },
                headers={"Mcp-Session-Id": "session-abc"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return rpc_response(
                request,
                {"tools": [{"name": "best_selling", "inputSchema": {"type": "object"}}]},
            )
        if method == "tools/call":
            if structured is not None:
                result = {"structuredContent": structured, "content": []}
            else:
                result = {
                    "content": [{"type": "text", "text": json.dumps(tool_result or {"items": []})}]
                }
            if sse:
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
                return httpx.Response(
                    200,
                    text=f"event: message\ndata: {payload}\n\n",
                    headers={"content-type": "text/event-stream"},
                )
            return rpc_response(request, result)
        raise AssertionError(method)

    return handler, calls


@pytest.mark.asyncio
async def test_initialization_tool_discovery_and_session_reuse():
    handler, calls = standard_handler()
    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    tools = await client.list_tools()
    assert tools[0]["name"] == "best_selling"
    assert client.server_info["name"] == "fixture"
    assert client.session_id == "session-abc"
    notification = next(
        headers for body, headers in calls if body["method"] == "notifications/initialized"
    )
    listing = next(headers for body, headers in calls if body["method"] == "tools/list")
    assert notification["mcp-session-id"] == "session-abc"
    assert listing["mcp-protocol-version"] == "2024-11-05"
    await client.close()


@pytest.mark.asyncio
async def test_tool_text_json_and_sse_response():
    handler, _ = standard_handler({"items": [{"id": 1}]}, sse=True)
    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    result = await client.call_tool("best_selling", {"limit": 1})
    assert result == {"items": [{"id": 1}]}
    await client.close()


@pytest.mark.asyncio
async def test_tool_structured_content_is_supported():
    handler, _ = standard_handler(structured={"items": [{"id": 2}]})
    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    assert await client.call_tool("best_selling", {}) == {"items": [{"id": 2}]}
    await client.close()


@pytest.mark.asyncio
async def test_invalid_json_response_is_protocol_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json or sse")

    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    with pytest.raises(MCPProtocolError, match="neither JSON"):
        await client.initialize()
    await client.close()


@pytest.mark.asyncio
async def test_json_rpc_error_is_reported():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32600, "message": "bad request"},
            },
        )

    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    with pytest.raises(MCPProtocolError, match="-32600"):
        await client.initialize()
    await client.close()


@pytest.mark.asyncio
async def test_permanent_tool_error_is_not_retried():
    handler, calls = standard_handler()

    async def error_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "tools/call":
            return rpc_response(
                request,
                {"isError": True, "content": [{"type": "text", "text": "invalid product id"}]},
            )
        return await handler(request)

    client = MCPClient(
        "https://example.test/mcp",
        transport=httpx.MockTransport(error_handler),
        max_retries=2,
        retry_base_seconds=0,
    )
    with pytest.raises(MCPToolError) as caught:
        await client.call_tool("product_details", {"id": -1})
    assert caught.value.transient is False
    assert (
        sum(body["method"] == "tools/call" for body, _ in calls) == 0
    )  # intercepted, not delegated
    await client.close()


@pytest.mark.asyncio
async def test_transient_tool_error_retries_then_succeeds():
    attempts = 0
    sleeps = []
    base, _ = standard_handler({"items": []})

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        body = json.loads(request.content)
        if body["method"] == "tools/call":
            attempts += 1
            if attempts == 1:
                return rpc_response(
                    request,
                    {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": "Digikala temporarily blocked this region; retry shortly",
                            }
                        ],
                    },
                )
        return await base(request)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = MCPClient(
        "https://example.test/mcp",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_seconds=0.5,
        sleep=sleep,
        random_source=lambda: 0,
    )
    assert await client.call_tool("best_selling", {}) == {"items": []}
    assert attempts == 2
    assert sleeps == [0.5]
    await client.close()


@pytest.mark.asyncio
async def test_http_503_has_bounded_retry():
    attempts = 0
    sleeps = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        body = json.loads(request.content)
        # The initialized notification is sent after a successful initialize and
        # must not count as a retry attempt.
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="busy")
        return rpc_response(
            request, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "ok"}}
        )

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = MCPClient(
        "https://example.test/mcp",
        transport=httpx.MockTransport(handler),
        max_retries=2,
        retry_base_seconds=1,
        sleep=sleep,
        random_source=lambda: 0,
    )
    await client.initialize()
    assert attempts == 3
    assert sleeps == [1, 2]
    await client.close()


@pytest.mark.asyncio
async def test_timeout_is_retried_and_sanitized():
    attempts = 0
    sleeps = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("secret upstream detail", request=request)

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = MCPClient(
        "https://example.test/mcp",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_seconds=0,
        sleep=sleep,
    )
    with pytest.raises(MCPHTTPError, match="timed out") as caught:
        await client.initialize()
    assert "secret" not in str(caught.value)
    assert attempts == 2
    assert len(sleeps) == 1
    await client.close()


@pytest.mark.asyncio
async def test_rate_limit_respects_retry_after():
    attempts = 0
    sleeps = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        body = json.loads(request.content)
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return rpc_response(
            request, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "ok"}}
        )

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = MCPClient(
        "https://example.test/mcp",
        transport=httpx.MockTransport(handler),
        max_retries=1,
        sleep=sleep,
    )
    await client.initialize()
    assert sleeps == [7.0]
    await client.close()


@pytest.mark.asyncio
async def test_exhausted_rate_limit_exposes_retry_after():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "12"})

    client = MCPClient(
        "https://example.test/mcp", transport=httpx.MockTransport(handler), max_retries=0
    )
    with pytest.raises(MCPRateLimitError) as caught:
        await client.initialize()
    assert caught.value.retry_after == 12
    await client.close()
