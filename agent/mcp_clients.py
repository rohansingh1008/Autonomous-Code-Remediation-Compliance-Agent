import asyncio
import os

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

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
