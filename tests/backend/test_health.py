import pytest
from app.main import create_application
from starlette.testclient import TestClient


@pytest.fixture
def client():
    app = create_application()
    return TestClient(app)


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert data["version"] == "0.1.0"
    assert "/api/v1/health" in data["health"]
    assert "/api/v1/ready" in data["ready"]


def test_top_level_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "lifethread-api"
    assert data["version"] == "0.1.0"


def test_api_v1_health_check(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "lifethread-api"
    assert data["version"] == "0.1.0"


def test_api_v1_readiness_check(client: TestClient):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert data["service"] == "lifethread-api"
    assert "checks" in data
    assert "database" in data["checks"]
