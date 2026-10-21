"""Minimal, standards-aware MCP Streamable HTTP client.

The upstream is stateless today, but this client also preserves an optional
Mcp-Session-Id so the adapter remains usable with a stateful compatible server.
"""

from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, Self

import httpx

logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    """Base error safe for service-level handling."""


class MCPHTTPError(MCPError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class MCPRateLimitError(MCPHTTPError):
    def __init__(self, retry_after: float | None) -> None:
        self.retry_after = retry_after
        suffix = f"; retry after {retry_after:g}s" if retry_after is not None else ""
        super().__init__(429, f"MCP endpoint rate limited the request{suffix}")


class MCPProtocolError(MCPError):
    pass


class MCPToolError(MCPError):
    def __init__(self, tool_name: str, message: str, *, transient: bool = False) -> None:
        self.tool_name = tool_name
        self.transient = transient
        super().__init__(message)


SleepCallable = Callable[[float], Awaitable[None]]


class MCPClient:
    """Reusable async client for JSON-RPC over MCP Streamable HTTP."""

    TRANSIENT_STATUSES: ClassVar[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
    TRANSIENT_TOOL_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:retry|temporar|cdn|rate.?limit|try again|درخواست.*دوباره)", re.IGNORECASE
    )

    def __init__(
        self,
        endpoint: str,
        *,
        protocol_version: str = "2024-11-05",
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_base_seconds: float = 1.0,
        max_retry_delay_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.endpoint = endpoint
        self.protocol_version = protocol_version
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self._sleep = sleep
        self._random = random_source
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            transport=transport,
            follow_redirects=False,
            headers={"user-agent": "digiscope/0.1"},
        )
        self._owns_client = client is None
        self._request_id = 0
        self._initialized = False
        self._initialize_lock = asyncio.Lock()
        self.session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self.negotiated_protocol_version: str | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {
                "serverInfo": self.server_info,
                "protocolVersion": self.negotiated_protocol_version,
            }
        async with self._initialize_lock:
            if self._initialized:
                return {
                    "serverInfo": self.server_info,
                    "protocolVersion": self.negotiated_protocol_version,
                }
            response = await self._rpc(
                "initialize",
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "DigiScope", "version": "0.1.0"},
                },
                initialize_request=True,
            )
            if not isinstance(response, dict):
                raise MCPProtocolError("initialize result is not an object")
            protocol = response.get("protocolVersion")
            if protocol is not None and not isinstance(protocol, str):
                raise MCPProtocolError("initialize protocolVersion is not a string")
            self.negotiated_protocol_version = protocol or self.protocol_version
            self.server_info = response.get("serverInfo") or {}
            self._initialized = True
            # A notification intentionally has no JSON-RPC id. Stateless servers may
            # answer 202/empty; a JSON response is tolerated and ignored.
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                expect_response=False,
            )
            return response

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.initialize()
        result = await self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
            raise MCPProtocolError("tools/list did not return an object list")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self.initialize()
        last_message = "MCP tool failed"
        for attempt in range(self.max_retries + 1):
            result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
            if not isinstance(result, dict):
                raise MCPProtocolError(f"{name} result is not an object")
            if result.get("isError") is True:
                message = self._content_text(result) or f"{name} returned an unspecified tool error"
                transient = bool(self.TRANSIENT_TOOL_RE.search(message))
                last_message = message[:500]
                if transient and attempt < self.max_retries:
                    delay = self._tool_retry_delay(message, attempt)
                    logger.warning(
                        "Transient MCP tool error",
                        extra={"event": "mcp_tool_retry", "tool": name, "attempt": attempt + 1},
                    )
                    await self._sleep(delay)
                    continue
                raise MCPToolError(name, last_message, transient=transient)
            return self._decode_tool_result(name, result)
        raise MCPToolError(name, last_message, transient=True)

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        initialize_request: bool = False,
    ) -> Any:
        request_id = self._next_id()
        payload, response_headers = await self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            expect_response=True,
            initialize_request=initialize_request,
        )
        session_id = response_headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id
        if not isinstance(payload, dict):
            raise MCPProtocolError("MCP response is not a JSON object")
        if payload.get("jsonrpc") not in (None, "2.0"):
            raise MCPProtocolError("MCP response has an unsupported JSON-RPC version")
        if "id" in payload and payload["id"] != request_id:
            raise MCPProtocolError("MCP response id does not match the request")
        if payload.get("error") is not None:
            error = payload["error"]
            if isinstance(error, dict):
                code = error.get("code", "unknown")
                message = str(error.get("message") or "JSON-RPC error")
                raise MCPProtocolError(f"JSON-RPC error {code}: {message[:400]}")
            raise MCPProtocolError(f"JSON-RPC error: {str(error)[:400]}")
        if "result" not in payload:
            raise MCPProtocolError("MCP response has neither result nor error")
        return payload["result"]

    async def _send(
        self,
        body: dict[str, Any],
        *,
        expect_response: bool,
        initialize_request: bool = False,
    ) -> tuple[Any, httpx.Headers]:
        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            headers = {
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            }
            if self.session_id:
                headers["mcp-session-id"] = self.session_id
            if self._initialized and not initialize_request:
                headers["mcp-protocol-version"] = (
                    self.negotiated_protocol_version or self.protocol_version
                )
            started = time.monotonic()
            try:
                response = await self._client.post(self.endpoint, headers=headers, json=body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exception = exc
                if attempt >= self.max_retries:
                    kind = "timed out" if isinstance(exc, httpx.TimeoutException) else "failed"
                    raise MCPHTTPError(0, f"MCP network request {kind}") from exc
                await self._sleep(self._backoff_delay(attempt))
                continue
            duration_ms = round((time.monotonic() - started) * 1000)
            logger.info(
                "MCP request completed",
                extra={
                    "event": "mcp_request",
                    "method": body.get("method"),
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "attempt": attempt + 1,
                },
            )
            if response.status_code in self.TRANSIENT_STATUSES:
                retry_after = self._parse_retry_after(response.headers.get("retry-after"))
                if attempt < self.max_retries:
                    delay = retry_after if retry_after is not None else self._backoff_delay(attempt)
                    await self._sleep(min(delay, self.max_retry_delay_seconds))
                    continue
                if response.status_code == 429:
                    raise MCPRateLimitError(retry_after)
                raise MCPHTTPError(
                    response.status_code,
                    f"MCP endpoint returned transient HTTP {response.status_code}",
                )
            if response.is_error:
                raise MCPHTTPError(
                    response.status_code, f"MCP endpoint returned HTTP {response.status_code}"
                )
            if not expect_response and not response.content:
                return None, response.headers
            if not response.content:
                if expect_response:
                    raise MCPProtocolError("MCP endpoint returned an empty response")
                return None, response.headers
            return self._parse_response(response.text), response.headers
        raise MCPHTTPError(0, f"MCP request failed: {type(last_exception).__name__}")

    def _backoff_delay(self, attempt: int) -> float:
        base = self.retry_base_seconds * (2**attempt)
        jitter = base * 0.2 * self._random()
        return min(base + jitter, self.max_retry_delay_seconds)

    def _tool_retry_delay(self, message: str, attempt: int) -> float:
        # The hosted service may explicitly ask for a 15–30 second retry after
        # riding out Digikala's CDN challenge. Honour the first stated bound
        # while retaining a configurable safety ceiling.
        match = re.search(
            r"(?:retry(?:\s+(?:in|after))?\s*)?(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(?:s|sec|seconds?)?",
            message,
            re.IGNORECASE,
        ) or re.search(
            r"retry(?:\s+(?:in|after))?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)",
            message,
            re.IGNORECASE,
        )
        if match:
            return min(float(match.group(1)), self.max_retry_delay_seconds)
        return self._backoff_delay(attempt)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value.strip()))
        except ValueError:
            try:
                target = email.utils.parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                return max(0.0, (target - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _parse_response(text: str) -> Any:
        stripped = text.strip()
        if not stripped:
            raise MCPProtocolError("MCP endpoint returned an empty response")
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # SSE allows multiple events and multiple data lines in an event. Select
        # the last JSON event, matching the upstream verifier's behaviour while
        # correctly joining multiline data.
        candidates: list[str] = []
        event_data: list[str] = []
        for line in stripped.splitlines() + [""]:
            if line.startswith("data:"):
                event_data.append(line[5:].lstrip())
            elif line == "" and event_data:
                candidates.append("\n".join(event_data))
                event_data = []
        for candidate in reversed(candidates):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise MCPProtocolError("MCP response was neither JSON nor valid JSON in an SSE data event")

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        content = result.get("content")
        if not isinstance(content, list):
            return ""
        chunks = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in (None, "text")
        ]
        return "\n".join(str(chunk) for chunk in chunks if chunk)

    def _decode_tool_result(self, name: str, result: dict[str, Any]) -> Any:
        structured = result.get("structuredContent")
        if structured is not None:
            if isinstance(structured, (dict, list)):
                return structured
            raise MCPProtocolError(f"{name} structuredContent has an unexpected type")
        content = result.get("content")
        if not isinstance(content, list):
            raise MCPProtocolError(f"{name} result has no content list")
        parse_errors = 0
        for item in content:
            if not isinstance(item, dict) or item.get("type") not in (None, "text"):
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                parse_errors += 1
        suffix = " (text was not valid JSON)" if parse_errors else ""
        raise MCPProtocolError(f"{name} did not return JSON tool content{suffix}")
