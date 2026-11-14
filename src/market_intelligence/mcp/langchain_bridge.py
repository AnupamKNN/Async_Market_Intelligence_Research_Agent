from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool, ToolException
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

from market_intelligence.core.config import PROJECT_ROOT

SERVER_MODULES = {
    "analytics": "market_intelligence.mcp.internal_analytics.server",
    "research": "market_intelligence.mcp.external_research.server",
    "sentiment": "market_intelligence.mcp.sentiment_server",
}


class MCPToolBridge:
    """Manage MCP server subprocesses and expose their tools to LangChain.

    Usage:
        async with MCPToolBridge() as bridge:
            tools = bridge.tools
            # Use tools with LangGraph or LangChain.
    """

    def __init__(
        self,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self.project_root = project_root
        self._exit_stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._tools: list[StructuredTool] = []
        self._started = False

    async def __aenter__(self) -> MCPToolBridge:
        """Start both MCP servers and discover their tools."""

        if self._started:
            raise RuntimeError("MCPToolBridge is already running.")

        if not self.project_root.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {self.project_root}")

        try:
            for server_alias, module in SERVER_MODULES.items():
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", module],
                    cwd=self.project_root,
                )

                client = Client(parameters)

                connected_client = await self._exit_stack.enter_async_context(client)

                self._clients[server_alias] = connected_client

                mcp_tools = await self._list_all_tools(connected_client)

                for mcp_tool in mcp_tools:
                    self._tools.append(
                        self._create_langchain_tool(
                            server_alias=server_alias, client=connected_client, mcp_tool=mcp_tool
                        )
                    )

            if not self._tools:
                raise RuntimeError("No tools were discovered from the MCP servers.")

            self._started = True
            return self

        except BaseException:
            await self._exit_stack.aclose()
            self._clients.clear()
            self._tools.clear()
            raise

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Shut down all MCP server subprocesses."""
        self._started = False
        self._clients.clear()
        self._tools.clear()
        await self._exit_stack.aclose()

    @staticmethod
    async def _list_all_tools(client: Client) -> list[Any]:
        """Discover every tool, handling MCP pagination."""

        discovered: list[Any] = []
        cursor: str | None = None

        while True:
            page = await client.list_tools(cursor=cursor)
            discovered.extend(page.tools)

            cursor = page.next_cursor

            if cursor is None:
                break

        return discovered

    @staticmethod
    def _serialize_result(result: Any, tool_name: str) -> str:
        """Convert MCP results into a LangChain-compatible response."""

        if result.is_error:
            error_message = [
                block.text for block in result.content if isinstance(block, TextContent)
            ]

            detail = "\n".join(error_message) or "The MCP server returned an unspecified error,"

            raise ToolException(f"MCP tool '{tool_name}' failed: {detail}")

        if result.structured_content is not None:
            return json.dumps(
                result.structured_content,
                ensure_ascii=False,
                default=str,
            )

        text_blocks = [block.text for block in result.content if isinstance(block, TextContent)]

        if text_blocks:
            return "\n".join(text_blocks)

        return json.dumps(
            {"status": "completed", "content": []},
            ensure_ascii=False,
        )

    def _create_langchain_tool(
        self, server_alias: str, client: Client, mcp_tool: Any
    ) -> StructuredTool:
        """Convert one MCP tool definition into a LangChain tool."""

        original_name = mcp_tool.name
        qualified_name = f"{server_alias}__{original_name}"

        input_schema = dict(mcp_tool.input_schema)

        if input_schema.get("type") != "object":
            raise ValueError(
                f"Unsupported MCP input schema for '{qualified_name}'. "
                "Expected a JSON object schema."
            )

        if not isinstance(input_schema.get("properties"), dict):
            raise ValueError(f"Invalid input schema for '{qualified_name}'.")

        description = mcp_tool.description or f"MCP tool '{original_name}' from {server_alias}."

        async def invoke_mcp_tool(**arguments: Any) -> str:
            """Invoke the original MCP tool through its live client."""

            result = await client.call_tool(
                original_name,
                arguments,
            )

            return self._serialize_result(
                result,
                qualified_name,
            )

        return StructuredTool.from_function(
            coroutine=invoke_mcp_tool,
            name=qualified_name,
            description=description,
            args_schema=input_schema,
            infer_schema=False,
            metadata={"mcp_server": server_alias, "mcp_tool": original_name},
        )

    @property
    def tools(self) -> list[StructuredTool]:
        """Return discovered LangChain tools."""

        if not self._started:
            raise RuntimeError("Start MCPToolBridge using 'async with' before accessing tools.")
        return list(self._tools)

    @property
    def server_names(self) -> list[str]:
        """Return the names of connected MCP servers."""

        return list(self._clients)
