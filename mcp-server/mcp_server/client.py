import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mcp_server.schemas import JSONRPCRequest, JSONRPCResponse

logger = logging.getLogger("lifethread.mcp.client")


class MCPClientError(Exception):
    """Exception raised by MCPClient when a JSON-RPC error is returned."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


class MCPClient:
    """External client facilitating connection, discovery, and execution against an MCP server."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        api_key: str | None = "lifethread-mcp-secret-key",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._external_client = http_client
        self._internal_client: httpx.AsyncClient | None = None
        self._request_counter = 0
        self._discovery_cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl_seconds = 60.0

    def _get_http_client(self) -> httpx.AsyncClient:
        """Provide a pooled persistent HTTP client with connection reuse."""
        if self._external_client:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            self._internal_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._internal_client

    async def aclose(self) -> None:
        """Dispose persistent pooled HTTP connections."""
        if self._internal_client and not self._internal_client.is_closed:
            await self._internal_client.aclose()

    def _get_headers(self, accept_stream: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": f"client_{uuid.uuid4().hex[:12]}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if accept_stream:
            headers["Accept"] = "text/event-stream"
        return headers

    async def _post_rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        accept_stream: bool = False,
    ) -> JSONRPCResponse:
        self._request_counter += 1
        req_id = f"req-{self._request_counter}"
        payload = JSONRPCRequest(
            id=req_id,
            method=method,
            params=params or {},
        ).model_dump()

        headers = self._get_headers(accept_stream=accept_stream)
        url = f"{self.base_url}/mcp"

        client = self._get_http_client()
        res = await client.post(url, json=payload, headers=headers)

        if res.status_code == 401:
            raise MCPClientError(
                code=-32001,
                message="Unauthorized: Invalid or missing API key on MCP server.",
            )

        data = res.json()
        response = JSONRPCResponse.model_validate(data)

        if response.error:
            raise MCPClientError(
                code=response.error.code,
                message=response.error.message,
                data=response.error.data,
            )

        return response

    async def initialize(self) -> dict[str, Any]:
        """Perform MCP protocol initialization handshake."""
        resp = await self._post_rpc("initialize")
        return resp.result or {}

    async def discover_tools(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Discover available tools and their input schemas from the MCP server with caching."""
        now = time.time()
        if not force_refresh and "tools" in self._discovery_cache:
            ts, cached_tools = self._discovery_cache["tools"]
            if now - ts < self._cache_ttl_seconds:
                return cached_tools

        resp = await self._post_rpc("tools/list")
        result = resp.result or {}
        tools = result.get("tools", [])
        self._discovery_cache["tools"] = (now, tools)
        return tools

    async def list_tools(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Alias for discover_tools."""
        return await self.discover_tools(force_refresh=force_refresh)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool on the MCP server and return parsed content or data."""
        params = {"name": tool_name, "arguments": arguments}
        resp = await self._post_rpc("tools/call", params=params)
        result = resp.result or {}

        # Parse MCP content block
        content_items = result.get("content", [])
        if content_items and isinstance(content_items[0], dict):
            text_payload = content_items[0].get("text", "")
            try:
                parsed_json = json.loads(text_payload)
                return {
                    "isError": result.get("isError", False),
                    "data": parsed_json,
                }
            except json.JSONDecodeError:
                return {
                    "isError": result.get("isError", False),
                    "data": text_payload,
                }

        return result

    async def call_tool_stream(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a tool using Streamable HTTP (SSE) and stream intermediate events."""
        self._request_counter += 1
        req_id = f"stream-req-{self._request_counter}"
        payload = JSONRPCRequest(
            id=req_id,
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        ).model_dump()

        headers = self._get_headers(accept_stream=True)
        url = f"{self.base_url}/mcp"

        client = self._external_client or httpx.AsyncClient()
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code == 401:
                    raise MCPClientError(
                        code=-32001,
                        message="Unauthorized: Invalid or missing API key.",
                    )

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line.removeprefix("data: ").strip()
                        if data_str:
                            try:
                                yield json.loads(data_str)
                            except json.JSONDecodeError:
                                yield {"raw": data_str}
        finally:
            if not self._external_client:
                await client.aclose()
