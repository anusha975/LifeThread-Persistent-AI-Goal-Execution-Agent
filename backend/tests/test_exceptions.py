from app.core.exceptions import LifeThreadException, lifethread_exception_handler
from fastapi import FastAPI
from starlette.testclient import TestClient


def test_404_not_found_structured_error(client: TestClient) -> None:
    """Verify non-existent routes return standardized structured error payloads."""
    response = client.get("/api/v1/non-existent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]
    assert "request_id" in data["error"]
    assert data["error"]["request_id"] == response.headers.get("x-request-id")


def test_custom_lifethread_exception():
    """Verify LifeThreadException handler returns structured payload."""
    test_app = FastAPI()
    test_app.add_exception_handler(LifeThreadException, lifethread_exception_handler)

    @test_app.get("/trigger-error")
    def trigger():
        raise LifeThreadException(
            message="Resource conflict occurred",
            code="RESOURCE_CONFLICT",
            status_code=409,
            details={"conflict_id": 99},
        )

    client = TestClient(test_app)
    response = client.get("/trigger-error", headers={"X-Request-ID": "test-err-req"})
    assert response.status_code == 409
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "RESOURCE_CONFLICT"
    assert data["error"]["message"] == "Resource conflict occurred"
    assert data["error"]["details"] == {"conflict_id": 99}
