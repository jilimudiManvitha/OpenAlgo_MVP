"""Read-only MCP handshake and instance check using the installed Codex entry."""

import asyncio
import json
import tomllib
from datetime import timedelta
from pathlib import Path

from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters


async def main():
    config = tomllib.loads((Path.home() / ".codex/config.toml").read_text())["mcp_servers"][
        "openalgo"
    ]
    params = StdioServerParameters(
        command=config["command"], args=config["args"], env=config.get("env")
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=30)
        ) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            required = {
                "list_watchlists",
                "get_watchlist",
                "create_watchlist",
                "add_watchlist_symbols",
                "remove_watchlist_symbols",
                "replace_watchlist_symbols",
                "rename_watchlist",
                "delete_watchlist",
                "get_expired_expiry_dates",
                "get_expired_contracts",
                "get_expired_historical_data",
                "place_order",
                "get_quote",
            }
            assert required <= names, f"Missing tools: {sorted(required - names)}"
            result = await session.call_tool("list_watchlists", {})
            contents = [json.loads(block.text) for block in result.content if block.type == "text"]
            payload = contents[0]["data"]
            success = payload.get("status") == "success"
            print(
                json.dumps(
                    {
                        "mcp_initialized": True,
                        "server": initialized.serverInfo.name,
                        "tool_count": len(names),
                        "all_required_tools_present": True,
                        "watchlist_api_available": success,
                        "watchlists": payload.get("data") if success else None,
                        "error_status": payload.get("code") if not success else None,
                        "error_type": payload.get("error_type") if not success else None,
                    },
                    indent=2,
                )
            )
            return success


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
