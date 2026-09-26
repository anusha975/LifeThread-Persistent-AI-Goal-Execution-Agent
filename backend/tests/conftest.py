import pytest
from app.main import create_application
from app.middleware.security import get_rate_limiter
from app.services.observability.service import AgentObservabilityService
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_global_test_state():
    """Reset the singleton rate limiter and observability metrics between test cases."""
    get_rate_limiter().reset()
    AgentObservabilityService.reset()
    yield
    get_rate_limiter().reset()
    AgentObservabilityService.reset()


@pytest.fixture
def client():
    app = create_application()
    return TestClient(app)
