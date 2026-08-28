#!/usr/bin/env python3
"""Oficjalny serwer MCP dla FitMentor oparty na SDK `mcp`.

Uruchomienie:
    python3 mcp_server.py
"""

from __future__ import annotations

import json
from typing import Any, Callable

import anyio
import mcp_types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

from chat import BMI_TOOL, PRODUCT_TOOL, analyze_product, calculate_bmi
from body_tracking import (
    GET_BODY_MEASUREMENTS_TOOL,
    SAVE_BODY_MEASUREMENTS_TOOL,
    get_body_measurements,
    save_body_measurements,
)
from rag import RAG_TOOL, search_knowledge_base


TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "calculate_bmi": calculate_bmi,
    "analyze_product": analyze_product,
    "search_knowledge_base": search_knowledge_base,
    "save_body_measurements": save_body_measurements,
    "get_body_measurements": get_body_measurements,
}


def _build_tool(tool_definition: dict[str, Any]) -> types.Tool:
    function = tool_definition.get("function", {})
    return types.Tool(
        name=function["name"],
        description=function.get("description", ""),
        inputSchema=function.get("parameters", {"type": "object", "properties": {}}),
    )


TOOLS = [
    _build_tool(BMI_TOOL),
    _build_tool(PRODUCT_TOOL),
    _build_tool(RAG_TOOL),
    _build_tool(SAVE_BODY_MEASUREMENTS_TOOL),
    _build_tool(GET_BODY_MEASUREMENTS_TOOL),
]


async def handle_list_tools(
    ctx: ServerRequestContext[Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def handle_call_tool(
    ctx: ServerRequestContext[Any],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    tool_name = params.name
    arguments = params.arguments or {}

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Nieznane narzędzie: {tool_name}")],
            structuredContent={"error": f"Nieznane narzędzie: {tool_name}"},
            isError=True,
        )

    try:
        result = tool_fn(**arguments)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=False,
        )
    except Exception as exc:  # pragma: no cover - zależne od danych wejściowych
        message = str(exc)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            structuredContent={"error": message},
            isError=True,
        )


async def main() -> None:
    server = Server(
        "fitmentor-mcp",
        version="1.0.0",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main, backend="trio")
