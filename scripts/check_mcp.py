"""Live MCP contract and optional data smoke check."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.config import Settings
from app.mcp.factory import build_adapter
from app.models import ScopeType


async def check(call_data: bool) -> int:
    settings = Settings()
    adapter = build_adapter(settings)
    try:
        tools = await adapter.discover()
        report = {
            "endpoint": str(settings.digikala_mcp_url),
            "protocol": adapter.client.negotiated_protocol_version,
            "server": adapter.client.server_info,
            "tool_count": len(tools),
            "tools": sorted(tools),
            "required_tools_present": True,
        }
        if call_data:
            batch = await adapter.fetch_ranking(
                scope_type=ScopeType.GLOBAL,
                category_external_id=None,
                limit=3,
            )
            report["live_data"] = {
                "products": len(batch.products),
                "first_external_id": batch.products[0].external_id if batch.products else None,
                "warnings": batch.warnings,
            }
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI must report every connectivity failure
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "endpoint": str(settings.digikala_mcp_url),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the configured Digikala MCP endpoint")
    parser.add_argument(
        "--call-data", action="store_true", help="also call best_selling for three live cards"
    )
    raise SystemExit(asyncio.run(check(parser.parse_args().call_data)))


if __name__ == "__main__":
    main()
