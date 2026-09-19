"""
Thin synchronous wrapper around FastMCP's Client so LangGraph nodes (which are
plain sync functions) can call tools on the two MCP servers without every
node needing to know about asyncio.

Each call spawns the target server as a stdio subprocess, calls one tool, and
tears the connection down. That's the simplest thing that works correctly for
a prototype. See README "Extend this first" for how to upgrade to a
persistent session pool.
"""

import asyncio
import os

from fastmcp import Client

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_SERVER = os.path.join(_HERE, "mcp_servers", "github_server.py")
COMPLIANCE_SERVER = os.path.join(_HERE, "mcp_servers", "compliance_server.py")


async def _call(server_path: str, tool_name: str, **kwargs):
    async with Client(server_path) as client:
        result = await client.call_tool(tool_name, kwargs)
        return result.data if hasattr(result, "data") else result


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Fallback for environments that already have a running event loop.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def call_github_tool(tool_name: str, **kwargs):
    return _run(_call(GITHUB_SERVER, tool_name, **kwargs))


def call_compliance_tool(tool_name: str, **kwargs):
    return _run(_call(COMPLIANCE_SERVER, tool_name, **kwargs))
