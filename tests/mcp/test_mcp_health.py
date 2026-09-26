import pytest
from mcp_server.server import create_mcp_app
from starlette.testclient import TestClient


@pytest.fixture
def mcp_client():
    app = create_mcp_app()
    return TestClient(app)


def test_mcp_health_endpoint(mcp_client: TestClient):
    response = mcp_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "server_name" in data
    assert data["transport"] in ["http", "stdio"]


def test_mcp_info_endpoint(mcp_client: TestClient):
    response = mcp_client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "protocol_version" in data
    assert "capabilities" in data
    assert "tools" in data["capabilities"]
