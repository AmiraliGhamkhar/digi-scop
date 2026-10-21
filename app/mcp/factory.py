"""Construct the configured replaceable market-data adapter."""

from app.config import Settings
from app.mcp.adapter import DigikalaMCPAdapter
from app.mcp.client import MCPClient


def build_adapter(settings: Settings) -> DigikalaMCPAdapter:
    client = MCPClient(
        str(settings.digikala_mcp_url),
        protocol_version=settings.mcp_protocol_version,
        timeout=settings.mcp_request_timeout,
        max_retries=settings.mcp_max_retries,
        retry_base_seconds=settings.mcp_retry_base_seconds,
        max_retry_delay_seconds=settings.mcp_max_retry_delay_seconds,
    )
    return DigikalaMCPAdapter(client)
