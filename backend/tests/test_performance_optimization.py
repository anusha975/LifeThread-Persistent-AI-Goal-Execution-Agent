"""Test suite for Module 43: Performance Optimization.

Validates:
1. Database query caching and strict mutation invalidation in GoalService.
2. Vector search embedding cache and cosine distance mathematical correctness.
3. RAG retrieval caching and user-scoped invalidation.
4. Context construction memoization and deep copy safety.
5. CachedLLMProvider deterministic completions caching vs stochastic bypass.
6. MCP client connection pooling and tool discovery caching.
7. GZip compression middleware performance thresholds.
8. Preservation of functional correctness with zero regression across cached systems.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.base import Base
from app.db.models.goal import GoalStatus
from app.db.models.user import User
from app.main import app
from app.schemas.goal import GoalCreate, GoalUpdate
from app.services.context_engine import (
    ContextBudget,
    ContextBuilder,
    ContextItem,
    ContextSource,
)
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.goal import GoalService
from app.services.llm.cached_provider import CachedLLMProvider
from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import LLMMessage
from app.services.rag.models import RAGQueryRequest, RetrievedChunk
from app.services.rag.service import RAGService
from app.services.semantic_retriever import SemanticMemoryRetriever
from httpx import ASGITransport, AsyncClient
from mcp_server.client import MCPClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine):
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_users(db_session: AsyncSession):
    user_a = User(
        id=uuid.uuid4(),
        email="user_a@lifethread.ai",
        password_hash="dummy_hash_a",
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="user_b@lifethread.ai",
        password_hash="dummy_hash_b",
        is_active=True,
    )
    db_session.add(user_a)
    db_session.add(user_b)
    await db_session.commit()
    return user_a, user_b


# =============================================================================
# 1. DATABASE QUERY CACHING & MUTATION INVALIDATION
# =============================================================================


@pytest.mark.asyncio
async def test_goal_service_query_caching_and_invalidation(
    db_session: AsyncSession, test_users
):
    """Verify that GoalService caches queries and invalidates only the mutating user's cache."""
    user_a, user_b = test_users

    # Initial creation for User A
    goal_in = GoalCreate(
        title="Complete Marathon",
        objective="Train and finish 42km in under 4 hours",
        deadline=datetime.now(UTC),
    )
    created = await GoalService.create_goal(db_session, user_a.id, goal_in)
    assert created.id is not None

    # First list: cache miss, populates cache
    goals_1, total_1 = await GoalService.list_goals(db_session, user_a.id)
    assert total_1 == 1
    assert goals_1[0].title == "Complete Marathon"

    # Second list: cache hit (should return identical results)
    goals_2, total_2 = await GoalService.list_goals(db_session, user_a.id)
    assert total_2 == 1
    assert goals_2[0].id == created.id

    # User B should have empty list and not see User A's data
    goals_b, total_b = await GoalService.list_goals(db_session, user_b.id)
    assert total_b == 0

    # Mutate User A via update: must invalidate User A cache
    await GoalService.update_goal(
        db_session, created, GoalUpdate(title="Run Ultra Marathon")
    )

    # List again: should fetch fresh updated data from DB
    goals_updated, _ = await GoalService.list_goals(db_session, user_a.id)
    assert goals_updated[0].title == "Run Ultra Marathon"

    # Status mutation (pause/complete/resume) also invalidates
    await GoalService.pause_goal(db_session, created)
    goals_paused, _ = await GoalService.list_goals(db_session, user_a.id)
    assert goals_paused[0].status == GoalStatus.PAUSED

    # Delete invalidates cache
    await GoalService.delete_goal(db_session, created)
    goals_deleted, total_del = await GoalService.list_goals(db_session, user_a.id)
    assert total_del == 0


# =============================================================================
# 2. VECTOR SEARCH & EMBEDDING CACHING
# =============================================================================


@pytest.mark.asyncio
async def test_vector_search_embedding_cache_and_math(db_session: AsyncSession):
    """Verify that SemanticMemoryRetriever caches query embeddings and computes correct cosine similarities."""
    embed_call_count = 0

    class MockEmbeddingProvider(BaseEmbeddingProvider):
        @property
        def dimension(self) -> int:
            return 4

        async def generate_embedding(self, text: str) -> list[float]:
            nonlocal embed_call_count
            embed_call_count += 1
            if "marathon" in text:
                return [1.0, 0.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0, 0.0]

        async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
            return [await self.generate_embedding(t) for t in texts]

    mock_provider = MockEmbeddingProvider()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_provider)
    u_id = uuid.uuid4()

    # Clear retriever static cache before test
    retriever._embedding_cache.clear()

    # First call: cache miss, calls generate_embedding
    await retriever.retrieve(db=db_session, user_id=u_id, query="marathon")
    assert embed_call_count == 1

    # Second call with identical query: cache hit, skips generate_embedding
    await retriever.retrieve(db=db_session, user_id=u_id, query="marathon")
    assert embed_call_count == 1  # Unchanged!

    # Test optimized cosine similarity math with precomputed norm_b
    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0, 0.0]
    norm_b = 1.0

    sim, dist = retriever._cosine_similarity_and_distance(vec_a, vec_b, norm_b=norm_b)
    assert pytest.approx(sim, 1e-4) == 1.0
    assert pytest.approx(dist, 1e-4) == 0.0

    # Orthogonal vectors
    vec_c = [0.0, 1.0, 0.0, 0.0]
    sim_ortho, dist_ortho = retriever._cosine_similarity_and_distance(
        vec_c, vec_b, norm_b=norm_b
    )
    assert pytest.approx(sim_ortho, 1e-4) == 0.0
    assert pytest.approx(dist_ortho, 1e-4) == 1.0


# =============================================================================
# 3. RAG RETRIEVAL CACHING
# =============================================================================


@pytest.mark.asyncio
async def test_rag_retrieval_caching_and_invalidation(db_session: AsyncSession):
    """Verify RAGService caches deterministic query results and invalidates per user."""
    mock_retriever = MagicMock()
    sample_chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        filename="notes.txt",
        content="Marathon training begins with zone 2 cardio.",
        chunk_index=0,
        metadata={"source": "notes"},
        similarity_score=0.95,
        distance=0.05,
    )
    mock_retriever.retrieve = AsyncMock(return_value=[sample_chunk])

    mock_llm = MockLLMProvider(default_response="Zone 2 cardio is effective for marathon training.")
    rag_service = RAGService(retriever=mock_retriever, llm_provider=mock_llm)
    user_id = uuid.uuid4()
    rag_service.invalidate_user_rag_cache(user_id)

    req = RAGQueryRequest(query="marathon training", top_k=3)

    # Initial retrieval: miss, retriever called
    res1 = await rag_service.query(db=db_session, user_id=user_id, request=req)
    assert res1.has_results is True
    assert mock_retriever.retrieve.call_count == 1

    # Identical retrieval: hit, retriever NOT called again
    res2 = await rag_service.query(db=db_session, user_id=user_id, request=req)
    assert res2.answer == res1.answer
    assert mock_retriever.retrieve.call_count == 1  # Unchanged!

    # User cache invalidation
    rag_service.invalidate_user_rag_cache(user_id)

    # Retrieval after invalidation: miss, retriever called again
    await rag_service.query(db=db_session, user_id=user_id, request=req)
    assert mock_retriever.retrieve.call_count == 2


# =============================================================================
# 4. CONTEXT ENGINE BUILDER MEMOIZATION
# =============================================================================


def test_context_builder_memoization_and_safety():
    """Verify ContextBuilder caches identical candidate sets and returns independent copies."""
    builder = ContextBuilder()
    u_id = uuid.uuid4()

    items = [
        ContextItem(
            id=str(uuid.uuid4()),
            source=ContextSource.MEMORIES,
            content="User prefers morning workout",
            user_id=u_id,
            source_attribution="Memory: #1",
        ),
        ContextItem(
            id=str(uuid.uuid4()),
            source=ContextSource.CURRENT_GOAL,
            content="Run half-marathon in October",
            user_id=u_id,
            source_attribution="Goal: #1",
        ),
    ]

    budget = ContextBudget(total_tokens=100)

    # First build: cache miss
    res1 = builder.build(user_id=u_id, items=items, budget=budget)
    assert len(res1.items) == 2

    # Second build with identical items & budget: cache hit
    res2 = builder.build(user_id=u_id, items=items, budget=budget)
    assert len(res2.items) == 2

    # Check that modifying res2 does not mutate res1 (deep copy safety)
    res2.items.pop()
    assert len(res2.items) == 1
    assert len(res1.items) == 2

    # Different budget -> re-computes
    small_budget = ContextBudget(total_tokens=5)
    res3 = builder.build(user_id=u_id, items=items, budget=small_budget)
    assert len(res3.items) <= 1


# =============================================================================
# 5. CACHED LLM PROVIDER
# =============================================================================


@pytest.mark.asyncio
async def test_cached_llm_provider_behavior():
    """Verify CachedLLMProvider caches deterministic queries and bypasses stochastic calls."""
    mock = MockLLMProvider()
    mock.set_responses(["Generated answer 1", "Generated answer 2", "Generated answer 3"])
    cached = CachedLLMProvider(mock, max_cache_size=100, ttl_seconds=300.0)

    # 1. Deterministic request (temperature <= 0.1)
    messages = [LLMMessage(role="user", content="What is 2 + 2?")]

    res1 = await cached.chat(messages=messages, temperature=0.0)
    assert res1.content == "Generated answer 1"
    assert len(mock.call_history) == 1

    # Second deterministic call: should hit cache
    res2 = await cached.chat(messages=messages, temperature=0.0)
    assert res2.content == "Generated answer 1"
    assert len(mock.call_history) == 1  # Not incremented!
    assert cached.cache_hits == 1
    assert cached.cache_misses == 1

    # 2. Stochastic request (temperature > 0.1): must bypass cache to preserve randomness
    stoch_messages = [LLMMessage(role="user", content="Write a random creative poem")]

    res3 = await cached.chat(messages=stoch_messages, temperature=0.7)
    assert res3.content == "Generated answer 2"
    assert len(mock.call_history) == 2

    res4 = await cached.chat(messages=stoch_messages, temperature=0.7)
    assert res4.content == "Generated answer 3"
    assert len(mock.call_history) == 3  # Incremented again because cache bypassed

    # 3. Cache clearing
    cached.clear_cache()
    assert len(cached._cache) == 0
    assert cached.cache_hits == 0


# =============================================================================
# 6. MCP CLIENT CONNECTION POOLING & TOOL DISCOVERY CACHING
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_client_pooling_and_discovery_cache():
    """Verify MCPClient reuses HTTP client and caches tool discovery."""
    client = MCPClient(base_url="http://mock-mcp-server:8000")

    # Reused client instance from connection pool
    http_client1 = client._get_http_client()
    http_client2 = client._get_http_client()
    assert http_client1 is http_client2

    # Mock post response for tool listing
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {
            "tools": [
                {"name": "fetch_calendar", "description": "Fetches calendar events"},
                {"name": "send_email", "description": "Sends notification email"},
            ]
        },
    }
    http_client1.post = AsyncMock(return_value=mock_response)

    # First call: hits HTTP endpoint
    tools1 = await client.list_tools()
    assert len(tools1) == 2
    assert http_client1.post.call_count == 1

    # Second call without force_refresh: hits memory cache
    tools2 = await client.list_tools()
    assert len(tools2) == 2
    assert http_client1.post.call_count == 1  # Unchanged

    # Call with force_refresh=True: bypasses cache
    tools3 = await client.list_tools(force_refresh=True)
    assert len(tools3) == 2
    assert http_client1.post.call_count == 2

    # Clean shutdown
    await client.aclose()
    assert client._internal_client is None or client._internal_client.is_closed


# =============================================================================
# 7. GZIP COMPRESSION MIDDLEWARE VERIFICATION
# =============================================================================


@pytest.mark.asyncio
async def test_gzip_compression_on_api_endpoints():
    """Verify GZipMiddleware compresses responses when Accept-Encoding gzip is requested."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Request with gzip accept encoding
        resp_gzip = await ac.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        assert resp_gzip.status_code == 200
        assert resp_gzip.headers.get("content-encoding") == "gzip"

        # Request explicitly specifying identity encoding: should not compress
        resp_plain = await ac.get("/openapi.json", headers={"Accept-Encoding": "identity"})
        assert resp_plain.status_code == 200
        assert resp_plain.headers.get("content-encoding") is None
