from starlette.testclient import TestClient


def test_api_v1_health(client: TestClient) -> None:
    """Verify that /api/v1/health returns HTTP 200 with structured status ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "lifethread-api"
    assert data["version"] == "0.1.0"


def test_api_v1_ready(client: TestClient) -> None:
    """Verify that /api/v1/ready returns HTTP 200 with readiness status."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert data["service"] == "lifethread-api"
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]


def test_top_level_health(client: TestClient) -> None:
    """Verify that top-level /health alias returns HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_endpoint(client: TestClient) -> None:
    """Verify root endpoint returns system links and version."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "LifeThread API"
    assert "/api/v1/health" in data["health"]
    assert "/api/v1/ready" in data["ready"]
