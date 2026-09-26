import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.aws.agent_core import (
    AgentCoreActionRequest,
    BedrockAgentCoreProvider,
    LocalAgentCoreProvider,
)
from app.services.aws.bedrock_provider import BedrockLLMProvider
from app.services.aws.config import AWSConfigManager
from app.services.aws.cost_tracker import cost_tracker
from app.services.aws.strands import (
    LocalStrandsProvider,
    StrandItem,
)
from app.services.llm.factory import get_llm_provider
from app.services.llm.provider import LLMMessage
from app.services.skills.registry import SkillRegistry
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(async_db: AsyncSession):
    async def override_get_db():
        yield async_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(async_db: AsyncSession) -> User:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="aws_tester@example.com",
        display_name="AWS AI Engineer",
        password_hash="hashed_pw",
        is_active=True,
    )
    async_db.add(user)
    await async_db.commit()
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token, _, _ = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def clean_cost_tracker():
    """Ensure clean cost tracker metrics before test runs."""
    cost_tracker.reset()
    yield cost_tracker
    cost_tracker.reset()


def test_aws_config_manager_masked_credentials():
    """Test AWS configuration masking for security audit compliance."""
    with patch.object(get_settings(), "AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE"):
        masked = AWSConfigManager.get_masked_credentials()
        assert masked["has_credentials"] is True
        assert masked["access_key_masked"] == "AKIA...MPLE"
        assert "default_model" in masked
        assert masked["timeout_seconds"] == 30.0

    with patch.object(get_settings(), "AWS_ACCESS_KEY_ID", None):
        with patch.dict("os.environ", {}, clear=True):
            masked_none = AWSConfigManager.get_masked_credentials()
            assert masked_none["access_key_masked"] == "None"


def test_aws_botocore_config_creation():
    """Test creation of botocore configuration with adaptive retries and timeouts."""
    cfg = AWSConfigManager.get_botocore_config(timeout=45.0, max_retries=5)
    assert cfg.connect_timeout == 45.0
    assert cfg.read_timeout == 45.0
    assert cfg.retries["max_attempts"] == 5
    assert cfg.retries["mode"] == "adaptive"


def test_bedrock_cost_tracker_calculation(clean_cost_tracker):
    """Test token and cost calculations across different model pricing tiers."""
    tracker = clean_cost_tracker

    # Claude 3.5 Sonnet: $3.00/M in, $15.00/M out
    sonnet_cost = tracker.calculate_cost(
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    # (10000 / 1000000 * 3.00) + (2000 / 1000000 * 15.00) = 0.030 + 0.030 = 0.060
    assert sonnet_cost == pytest.approx(0.060, rel=1e-3)

    # Claude 3 Haiku: $0.25/M in, $1.25/M out
    haiku_cost = tracker.calculate_cost(
        "anthropic.claude-3-haiku-20240307-v1:0",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    # (10000 / 1000000 * 0.25) + (2000 / 1000000 * 1.25) = 0.0025 + 0.0025 = 0.005
    assert haiku_cost == pytest.approx(0.005, rel=1e-3)

    # Record invocation and inspect summary
    rec = tracker.record_invocation(
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    assert rec.total_tokens == 12_000

    summary = tracker.get_summary()
    assert summary.total_requests == 1
    assert summary.total_input_tokens == 10_000
    assert summary.total_output_tokens == 2_000
    assert summary.total_cost_usd > 0.0
    assert "anthropic.claude-3-5-sonnet-20240620-v1:0" in summary.by_model


@pytest.mark.asyncio
async def test_bedrock_llm_provider_model_selection_and_fallback(clean_cost_tracker):
    """Test Bedrock LLM Provider model routing and local fallback when offline."""
    provider = BedrockLLMProvider()

    # Model routing
    assert "sonnet" in provider.select_model(fast=False).lower()
    assert "haiku" in provider.select_model(fast=True).lower()
    assert provider.select_model(model="custom-model") == "custom-model"

    # Execution with fallback when credentials are intentionally absent
    with patch.object(AWSConfigManager, "is_aws_available", return_value=False):
        response = await provider.generate("Summarize my active priorities", fast=True)
        assert response is not None
        assert response.provider == "aws-bedrock-fallback"
        assert response.model == provider.fast_model
        assert response.raw_response.get("fallback") is True


@pytest.mark.asyncio
async def test_bedrock_llm_provider_simulated_boto3_converse(clean_cost_tracker):
    """Test Bedrock LLM Provider handling real Converse API payload."""
    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "Target goal successfully planned and optimized."}],
            }
        },
        "stopReason": "end_turn",
        "usage": {
            "inputTokens": 1500,
            "outputTokens": 300,
            "totalTokens": 1800,
        },
        "metrics": {"latencyMs": 420},
    }

    provider = BedrockLLMProvider()

    with patch.object(AWSConfigManager, "is_aws_available", return_value=True):
        with patch.object(provider, "_get_client", return_value=mock_client):
            response = await provider.chat(
                [LLMMessage(role="user", content="Plan my roadmap")],
                temperature=0.3,
            )

            assert response.content == "Target goal successfully planned and optimized."
            assert response.provider == "aws-bedrock"
            assert response.raw_response["usage"]["inputTokens"] == 1500

            # Verify cost tracking recorded the invocation
            summary = clean_cost_tracker.get_summary()
            assert summary.total_requests == 1
            assert summary.total_input_tokens == 1500
            assert summary.total_output_tokens == 300


@pytest.mark.asyncio
async def test_bedrock_llm_provider_retry_on_throttling(clean_cost_tracker):
    """Test adaptive retries and graceful fallback on AWS throttling exception."""
    from botocore.exceptions import ClientError

    mock_client = MagicMock()
    # Raise throttling error on first call, succeed on second call
    mock_client.converse.side_effect = [
        ClientError(
            error_response={"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            operation_name="Converse",
        ),
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Recovered after throttle retry."}],
                }
            },
            "usage": {"inputTokens": 100, "outputTokens": 50},
        },
    ]

    provider = BedrockLLMProvider(max_retries=2)

    with patch.object(AWSConfigManager, "is_aws_available", return_value=True):
        with patch.object(provider, "_get_client", return_value=mock_client):
            with patch("asyncio.sleep", return_value=None):
                res = await provider.generate("Test query")
                assert res.content == "Recovered after throttle retry."
                assert res.provider == "aws-bedrock"
                assert mock_client.converse.call_count == 2


def test_llm_factory_resolves_bedrock():
    """Test factory resolution of bedrock provider."""
    provider = get_llm_provider("bedrock")
    assert isinstance(provider, BedrockLLMProvider)

    aws_provider = get_llm_provider("aws")
    assert isinstance(aws_provider, BedrockLLMProvider)


@pytest.mark.asyncio
async def test_local_agent_core_executes_action_groups(async_db: AsyncSession, test_user: User):
    """Test LocalAgentCore provider executes real action group via LifeThread SkillRegistry."""
    SkillRegistry.initialize_default_skills()
    provider = LocalAgentCoreProvider()
    request = AgentCoreActionRequest(
        action_group="goal_management",
        action_name="goal_management",
        parameters={"action": "list"},
        user_id=test_user.id,
    )

    response = await provider.execute_action(request, db=async_db)
    assert response.success is True
    assert response.provider == "local-agentcore"
    assert response.action_name == "goal_management"
    assert len(response.trace_steps) >= 3
    assert any(step.step_type == "ACTION_CALL" for step in response.trace_steps)
    assert any(step.step_type == "ACTION_RESULT" for step in response.trace_steps)


@pytest.mark.asyncio
async def test_bedrock_agent_core_fallback(async_db: AsyncSession, test_user: User):
    """Test BedrockAgentCore gracefully delegates to LocalAgentCore when agent ID unconfigured."""
    SkillRegistry.initialize_default_skills()
    provider = BedrockAgentCoreProvider(agent_id=None)
    request = AgentCoreActionRequest(
        action_group="memory",
        action_name="memory",
        parameters={"action": "list"},
        user_id=test_user.id,
    )

    response = await provider.execute_action(request, db=async_db)
    assert response.success is True
    assert response.provider == "local-agentcore"


@pytest.mark.asyncio
async def test_strands_local_provider_indexing_and_isolation(test_user):
    """Test Strands context provider indexing and strict tenant isolation."""
    provider = LocalStrandsProvider()
    other_user_id = uuid.uuid4()

    item_user1 = StrandItem(
        user_id=test_user.id,
        title="SQL Join Difficulty",
        content="I often get confused between LEFT JOIN and FULL OUTER JOIN syntax in PostgreSQL.",
        category="weakness",
    )
    item_user2 = StrandItem(
        user_id=other_user_id,
        title="Kubernetes Ingress",
        content="Configuring Traefik ingress routes for microservices.",
        category="knowledge",
    )

    await provider.index(item_user1)
    await provider.index(item_user2)

    # Search as test_user
    results = await provider.search(query="SQL JOIN", user_id=test_user.id)
    assert len(results) >= 1
    assert results[0].title == "SQL Join Difficulty"
    assert "LEFT JOIN" in results[0].content

    # Strict tenant check: test_user cannot see user2's strand
    k8s_results = await provider.search(query="Kubernetes Ingress", user_id=test_user.id)
    assert len(k8s_results) == 0

    # User 2 can see their own strand
    u2_results = await provider.search(query="Kubernetes Ingress", user_id=other_user_id)
    assert len(u2_results) >= 1
    assert u2_results[0].title == "Kubernetes Ingress"


@pytest.mark.asyncio
async def test_api_aws_status_and_costs(client: AsyncClient, auth_headers: dict[str, str], clean_cost_tracker):
    """Test REST API /api/v1/aws/status and /api/v1/aws/costs endpoints."""
    # Status endpoint
    status_res = await client.get("/api/v1/aws/status", headers=auth_headers)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "region" in status_data
    assert "default_model" in status_data
    assert "access_key_masked" in status_data

    # Costs endpoint
    clean_cost_tracker.record_invocation(
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        input_tokens=5000,
        output_tokens=1000,
    )
    costs_res = await client.get("/api/v1/aws/costs", headers=auth_headers)
    assert costs_res.status_code == 200
    costs_data = costs_res.json()
    assert costs_data["total_requests"] >= 1
    assert costs_data["total_input_tokens"] >= 5000
    assert costs_data["total_cost_usd"] > 0


@pytest.mark.asyncio
async def test_api_agent_core_invoke_and_strands_endpoints(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Test REST API AgentCore invocation and Strands index/search endpoints."""
    SkillRegistry.initialize_default_skills()
    # 1. AgentCore invoke
    core_payload = {
        "action_group": "goal_management",
        "action_name": "goal_management",
        "parameters": {"action": "list"},
    }
    invoke_res = await client.post(
        "/api/v1/aws/agent-core/invoke",
        json=core_payload,
        headers=auth_headers,
    )
    assert invoke_res.status_code == 200
    invoke_data = invoke_res.json()
    assert invoke_data["success"] is True
    assert "trace_steps" in invoke_data

    # 2. Strands index
    index_payload = {
        "title": "AWS Bedrock Architecture",
        "content": "Using Bedrock Claude 3.5 Sonnet for planning and Haiku for classification.",
        "category": "preference",
    }
    index_res = await client.post(
        "/api/v1/aws/strands/index",
        json=index_payload,
        headers=auth_headers,
    )
    assert index_res.status_code == 200
    assert "strand_id" in index_res.json()

    # 3. Strands search
    search_payload = {
        "query": "Bedrock Claude Sonnet",
        "limit": 5,
        "min_score": 0.3,
    }
    search_res = await client.post(
        "/api/v1/aws/strands/search",
        json=search_payload,
        headers=auth_headers,
    )
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert len(search_data) >= 1
    assert "Bedrock" in search_data[0]["title"]
