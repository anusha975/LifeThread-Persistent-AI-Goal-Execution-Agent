from typing import Any

import httpx
import pytest
from mcp_server.client import MCPClient, MCPClientError
from mcp_server.schemas import JSONRPCErrorCode
from mcp_server.server import create_mcp_app
from starlette.testclient import TestClient

VALID_API_KEY = "lifethread-mcp-secret-key"


@pytest.fixture
def app():
    return create_mcp_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# ============================================================================
# HEALTH & METADATA TESTS
# ============================================================================


def test_mcp_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "tools_count" in data
    assert data["tools_count"] >= 3
    assert data["transport"] in ["streamable_http", "http"]


def test_mcp_info_endpoint(client: TestClient):
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["protocol_version"] == "2024-11-05"
    assert data["capabilities"]["streamable_http"] is True


# ============================================================================
# AUTHENTICATION & TRACING TESTS
# ============================================================================


def test_unauthenticated_request_rejected(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/list",
    }
    # No Auth header
    res = client.post("/mcp", json=payload)
    assert res.status_code == 401
    assert "Unauthorized" in res.json()["error"]["message"]


def test_invalid_api_key_rejected(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/list",
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert res.status_code == 401


def test_request_tracing_header_propagated(client: TestClient):
    res = client.get("/health", headers={"X-Request-ID": "custom_trace_999"})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == "custom_trace_999"


# ============================================================================
# TOOL DISCOVERY & EXECUTION TESTS
# ============================================================================


def test_mcp_tool_discovery(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-tools-list",
        "method": "tools/list",
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_API_KEY}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "req-tools-list"
    tools = body["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "ping" in tool_names
    assert "echo" in tool_names
    assert "calculate" in tool_names

    calc_tool = next(t for t in tools if t["name"] == "calculate")
    assert "inputSchema" in calc_tool
    assert "properties" in calc_tool["inputSchema"]


def test_mcp_tool_execution_success(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-calc-1",
        "method": "tools/call",
        "params": {
            "name": "calculate",
            "arguments": {"a": 20.0, "b": 4.0, "operation": "divide"},
        },
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_API_KEY}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is None
    result = body["result"]
    assert result["isError"] is False
    assert len(result["content"]) == 1
    content_text = result["content"][0]["text"]
    assert '"result": 5.0' in content_text or "5.0" in content_text


def test_mcp_tool_input_validation_error(client: TestClient):
    """Acceptance Criteria: Server returns structured errors when invalid arguments are supplied."""
    payload = {
        "jsonrpc": "2.0",
        "id": "req-calc-bad",
        "method": "tools/call",
        "params": {
            "name": "calculate",
            "arguments": {
                "a": "not-a-number",  # invalid float
                "operation": "invalid_op",  # invalid operation
            },
        },
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_API_KEY}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"] is None
    assert body["error"] is not None
    assert body["error"]["code"] == JSONRPCErrorCode.INVALID_PARAMS.value
    assert "validation_errors" in body["error"]["data"]


def test_mcp_unknown_tool_call(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-unknown",
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool",
            "arguments": {},
        },
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_API_KEY}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is not None
    assert body["error"]["code"] == JSONRPCErrorCode.METHOD_NOT_FOUND.value


# ============================================================================
# STREAMABLE HTTP (SSE) TESTS
# ============================================================================


def test_mcp_streamable_http_execution(client: TestClient):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-stream-1",
        "method": "tools/call",
        "params": {
            "name": "echo",
            "arguments": {"text": "hello stream", "repeat": 2},
        },
    }
    res = client.post(
        "/mcp",
        json=payload,
        headers={
            "Authorization": f"Bearer {VALID_API_KEY}",
            "Accept": "text/event-stream",
        },
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert "event: progress" in text
    assert "event: message" in text
    assert "hello stream hello stream" in text


def test_mcp_sse_endpoint(client: TestClient):
    res = client.get(
        "/sse",
        headers={"Authorization": f"Bearer {VALID_API_KEY}"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert "event: endpoint" in res.text


# ============================================================================
# EXTERNAL MCP CLIENT INTEGRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_external_mcp_client_roundtrip(app: Any):
    """Acceptance Criteria: An external MCP client can connect, discover tools, call tools, and handle errors."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        client = MCPClient(
            base_url="http://testserver",
            api_key=VALID_API_KEY,
            http_client=http_client,
        )

        # 1. Initialize
        init_res = await client.initialize()
        assert init_res["protocolVersion"] == "2024-11-05"

        # 2. Discover tools
        tools = await client.discover_tools()
        assert len(tools) >= 3
        tool_names = [t["name"] for t in tools]
        assert "ping" in tool_names
        assert "calculate" in tool_names

        # 3. Call tool with valid parameters
        res = await client.call_tool(
            tool_name="calculate",
            arguments={"a": 12.0, "b": 3.0, "operation": "multiply"},
        )
        assert res["isError"] is False
        assert res["data"] == {"result": 36.0, "operation": "multiply"}

        # 4. Call tool with invalid parameters -> Expect structured MCPClientError
        with pytest.raises(MCPClientError) as exc_info:
            await client.call_tool(
                tool_name="calculate",
                arguments={"a": "bad_operand", "operation": "add"},
            )
        assert exc_info.value.code == JSONRPCErrorCode.INVALID_PARAMS.value
        assert "validation" in exc_info.value.message.lower()
