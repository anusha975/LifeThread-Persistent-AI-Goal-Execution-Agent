from starlette.testclient import TestClient


def test_request_id_generated_automatically(client: TestClient) -> None:
    """Verify middleware assigns a unique Request ID when none is provided."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    req_id = response.headers["x-request-id"]
    assert len(req_id) >= 16


def test_request_id_propagated_from_header(client: TestClient) -> None:
    """Verify incoming X-Request-ID is preserved and returned."""
    custom_id = "custom-test-req-12345"
    response = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == custom_id


def test_process_time_header_present(client: TestClient) -> None:
    """Verify timing middleware appends process time header."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "x-process-time-ms" in response.headers
    duration = float(response.headers["x-process-time-ms"])
    assert duration >= 0.0


def test_cors_headers_on_options_request(client: TestClient) -> None:
    """Verify CORS preflight handling."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
