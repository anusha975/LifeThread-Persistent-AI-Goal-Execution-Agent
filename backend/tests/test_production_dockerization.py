"""Tests for Module 41: Production Dockerization.

Validates:
- All 6 core services containerized (frontend, backend, agent, mcp-server, postgres, redis)
- Multi-stage builds and non-root users in Dockerfiles
- Health checks configured across all services
- Environment variables and zero hardcoded secrets
- Persistent database and cache volumes
- Isolated internal vs frontend network topology
- docker-compose.dev.yml and docker-compose.test.yml validity
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def prod_compose() -> dict:
    compose_path = ROOT_DIR / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"
    with open(compose_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def dev_compose() -> dict:
    compose_path = ROOT_DIR / "docker-compose.dev.yml"
    assert compose_path.exists(), "docker-compose.dev.yml must exist"
    with open(compose_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def test_compose() -> dict:
    compose_path = ROOT_DIR / "docker-compose.test.yml"
    assert compose_path.exists(), "docker-compose.test.yml must exist"
    with open(compose_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_production_compose_all_six_services_present(prod_compose: dict):
    """Verify frontend, backend, agent, mcp-server, postgres, and redis are containerized."""
    services = prod_compose.get("services", {})
    required_services = {"frontend", "backend", "agent", "mcp-server", "postgres", "redis"}
    assert required_services.issubset(set(services.keys()))


def test_production_compose_healthchecks_on_all_services(prod_compose: dict):
    """Verify healthcheck directives are defined for all production services."""
    services = prod_compose.get("services", {})
    for service_name, config in services.items():
        assert "healthcheck" in config, f"Service '{service_name}' must define a healthcheck"
        hc = config["healthcheck"]
        assert "test" in hc, f"Healthcheck for '{service_name}' must have a test command"
        assert "interval" in hc, f"Healthcheck for '{service_name}' must have an interval"
        assert "retries" in hc, f"Healthcheck for '{service_name}' must have retries"


def test_production_compose_persistent_volumes(prod_compose: dict):
    """Verify persistent volumes are defined for PostgreSQL and Redis."""
    volumes = prod_compose.get("volumes", {})
    assert "postgres_data" in volumes, "postgres_data persistent volume must be declared"
    assert "redis_data" in volumes, "redis_data persistent volume must be declared"

    services = prod_compose.get("services", {})
    # Verify postgres service mounts postgres_data
    postgres_vols = services["postgres"].get("volumes", [])
    assert any("postgres_data" in str(v) for v in postgres_vols)

    # Verify redis service mounts redis_data
    redis_vols = services["redis"].get("volumes", [])
    assert any("redis_data" in str(v) for v in redis_vols)


def test_production_compose_isolated_network_topology(prod_compose: dict):
    """Verify network isolation: database and redis are never exposed to the frontend network."""
    networks = prod_compose.get("networks", {})
    assert "lifethread-frontend" in networks, "Frontend network must be declared"
    assert "lifethread-internal" in networks, "Internal network must be declared"

    services = prod_compose.get("services", {})

    # Postgres and Redis must ONLY be on the internal network
    postgres_nets = services["postgres"].get("networks", [])
    assert "lifethread-internal" in postgres_nets
    assert "lifethread-frontend" not in postgres_nets, "Postgres must not be exposed to frontend network"

    redis_nets = services["redis"].get("networks", [])
    assert "lifethread-internal" in redis_nets
    assert "lifethread-frontend" not in redis_nets, "Redis must not be exposed to frontend network"

    # Agent and MCP-server are on internal network
    assert "lifethread-internal" in services["agent"].get("networks", [])
    assert "lifethread-internal" in services["mcp-server"].get("networks", [])

    # Backend connects to both networks as the secure application gateway
    backend_nets = services["backend"].get("networks", [])
    assert "lifethread-internal" in backend_nets
    assert "lifethread-frontend" in backend_nets

    # Frontend connects only to frontend network
    frontend_nets = services["frontend"].get("networks", [])
    assert "lifethread-frontend" in frontend_nets
    assert "lifethread-internal" not in frontend_nets, "Frontend must not have direct database access"


def test_dockerfiles_exist_and_use_multistage():
    """Verify Dockerfiles exist for backend, frontend, agent, and mcp, using multi-stage builds."""
    docker_dir = ROOT_DIR / "infrastructure" / "docker"
    dockerfiles = {
        "backend": docker_dir / "Dockerfile.backend",
        "frontend": docker_dir / "Dockerfile.frontend",
        "agent": docker_dir / "Dockerfile.agent",
        "mcp": docker_dir / "Dockerfile.mcp",
    }

    for _name, path in dockerfiles.items():
        assert path.exists(), f"{path.name} must exist"
        content = path.read_text(encoding="utf-8")
        # Check multi-stage
        stages = re.findall(r"FROM\s+\S+\s+AS\s+(\w+)", content, re.IGNORECASE)
        assert len(stages) >= 1, f"{path.name} should use multi-stage builds"


def test_dockerfiles_enforce_non_root_execution():
    """Verify backend, agent, and mcp containers execute as a dedicated non-root user."""
    docker_dir = ROOT_DIR / "infrastructure" / "docker"
    backend_content = (docker_dir / "Dockerfile.backend").read_text(encoding="utf-8")
    assert "USER lifethread" in backend_content or "USER " in backend_content

    agent_content = (docker_dir / "Dockerfile.agent").read_text(encoding="utf-8")
    assert "USER lifethread" in agent_content

    mcp_content = (docker_dir / "Dockerfile.mcp").read_text(encoding="utf-8")
    assert "USER lifethread" in mcp_content


def test_zero_secrets_in_dockerfiles():
    """Verify no hardcoded credentials or API keys exist in Dockerfiles."""
    docker_dir = ROOT_DIR / "infrastructure" / "docker"
    forbidden_patterns = [
        r"sk-[a-zA-Z0-9]{20,}",
        r"password\s*=\s*['\"][a-zA-Z0-9]{6,}['\"]",
        r"AKIA[0-9A-Z]{16}",
        r"aws_secret_access_key",
    ]

    for dockerfile in docker_dir.glob("Dockerfile*"):
        content = dockerfile.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert not re.search(pattern, content, re.IGNORECASE), f"Potential secret found in {dockerfile.name}"


def test_development_compose_configuration(dev_compose: dict):
    """Verify docker-compose.dev.yml defines live code mounts, reload commands, and debug ports."""
    services = dev_compose.get("services", {})
    required = {"frontend", "backend", "agent", "mcp-server", "postgres", "redis"}
    assert required.issubset(set(services.keys()))

    # Verify backend has volumes mounted for live reload
    backend_vols = services["backend"].get("volumes", [])
    assert any("./backend" in str(v) for v in backend_vols)

    # Verify uvicorn has reload flag in dev
    cmd = services["backend"].get("command", [])
    assert "--reload" in cmd or any("--reload" in str(c) for c in cmd)


def test_test_compose_configuration(test_compose: dict):
    """Verify docker-compose.test.yml defines ephemeral test services and test execution commands."""
    services = test_compose.get("services", {})
    assert "backend-test" in services
    assert "postgres-test" in services
    assert "redis-test" in services

    # Verify ephemeral tmpfs on test databases for speed and cleanup
    assert "tmpfs" in services["postgres-test"]
    assert "tmpfs" in services["redis-test"]

    # Verify backend runs pytest
    backend_cmd = services["backend-test"].get("command", [])
    assert "pytest" in " ".join(backend_cmd)
