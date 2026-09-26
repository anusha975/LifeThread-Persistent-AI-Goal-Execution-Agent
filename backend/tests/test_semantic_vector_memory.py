import uuid

import pytest
from app.db.base import Base
from app.db.models.memory import MemoryType
from app.schemas.memory import MemoryCreate, MemoryUpdate
from app.services.embeddings.base import EmbeddingGenerationError
from app.services.embeddings.mock import MockEmbeddingProvider
from app.services.memory import MemoryService
from app.services.semantic_retriever import SemanticMemoryRetriever
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    """Create in-memory SQLite engine with fresh schema for Semantic Memory tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def mock_embedding_provider() -> MockEmbeddingProvider:
    """Return a mock embedding provider with standard 1536 dimension."""
    return MockEmbeddingProvider(dimension=1536)


@pytest.mark.asyncio
async def test_mock_embedding_provider_deterministic_and_normalized(
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Generate embeddings through an abstraction, deterministic and unit-normalized."""
    emb1 = await mock_embedding_provider.generate_embedding("Learn Python async programming")
    emb2 = await mock_embedding_provider.generate_embedding("Learn Python async programming")
    emb3 = await mock_embedding_provider.generate_embedding("Prepare for marathon race")

    assert len(emb1) == 1536
    assert emb1 == emb2  # Deterministic
    assert emb1 != emb3  # Distinct content produces different vectors

    # Verify unit normalization: sqrt(sum(x^2)) ~= 1.0
    norm_sq = sum(x * x for x in emb1)
    assert 0.999 <= norm_sq <= 1.001


@pytest.mark.asyncio
async def test_semantic_vector_search_and_ranking(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Store embeddings, implement similarity search, return ranked memories."""
    user_id = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    # Setup controlled orthogonal / collinear embeddings for precise testing
    dim = 1536
    vec_query = [1.0] + [0.0] * (dim - 1)
    vec_high = [0.9] + [0.1] * 10 + [0.0] * (dim - 11)  # high cosine similarity
    vec_med = [0.5] + [0.5] * 10 + [0.0] * (dim - 11)  # medium cosine similarity
    vec_low = [0.0] + [1.0] + [0.0] * (dim - 2)  # orthogonal / near 0 similarity

    mock_embedding_provider.set_embedding("query: python career", vec_query)
    mock_embedding_provider.set_embedding("Senior Python backend developer role", vec_high)
    mock_embedding_provider.set_embedding("General software engineering concepts", vec_med)
    mock_embedding_provider.set_embedding("Baking sourdough artisan bread", vec_low)

    async with session_factory() as session:
        # Store memories with embeddings
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Baking sourdough artisan bread",
                memory_type=MemoryType.PREFERENCE,
            ),
            embedding_provider=mock_embedding_provider,
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Senior Python backend developer role",
                memory_type=MemoryType.GOAL,
            ),
            embedding_provider=mock_embedding_provider,
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="General software engineering concepts",
                memory_type=MemoryType.SEMANTIC,
            ),
            embedding_provider=mock_embedding_provider,
        )

        # Execute semantic retrieval
        results = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="query: python career",
            top_k=10,
            similarity_threshold=0.0,
        )

        assert len(results) == 3
        # Check ranking: highest similarity first
        assert "Senior Python backend" in results[0].memory.content
        assert "General software engineering" in results[1].memory.content
        assert "Baking sourdough" in results[2].memory.content

        assert results[0].similarity_score > results[1].similarity_score
        assert results[1].similarity_score > results[2].similarity_score
        # Check distance relation: distance = 1 - similarity
        for res in results:
            assert abs((1.0 - res.similarity_score) - res.distance) < 0.01


@pytest.mark.asyncio
async def test_top_k_retrieval(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Support top-k retrieval."""
    user_id = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    async with session_factory() as session:
        for i in range(10):
            await MemoryService.store_memory(
                db=session,
                user_id=user_id,
                create_data=MemoryCreate(
                    content=f"Knowledge item #{i} regarding system optimization",
                    memory_type=MemoryType.SEMANTIC,
                ),
                embedding_provider=mock_embedding_provider,
            )

        top_3 = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="optimization",
            top_k=3,
        )
        assert len(top_3) == 3

        top_5 = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="optimization",
            top_k=5,
        )
        assert len(top_5) == 5


@pytest.mark.asyncio
async def test_similarity_threshold_filtering(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Add similarity thresholds."""
    user_id = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    dim = 1536
    v_query = [1.0] + [0.0] * (dim - 1)
    # Unit vectors with exact cosine similarity 0.95 and 0.10
    v_high = [0.95, (1.0 - 0.95**2) ** 0.5] + [0.0] * (dim - 2)  # 0.95 similarity
    v_low = [0.10, (1.0 - 0.10**2) ** 0.5] + [0.0] * (dim - 2)  # 0.10 similarity

    mock_embedding_provider.set_embedding("query: health", v_query)
    mock_embedding_provider.set_embedding("Cardiovascular exercise 3 times a week", v_high)
    mock_embedding_provider.set_embedding("Fixing compiler warnings in C++ code", v_low)

    async with session_factory() as session:
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Cardiovascular exercise 3 times a week",
                memory_type=MemoryType.GOAL,
            ),
            embedding_provider=mock_embedding_provider,
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Fixing compiler warnings in C++ code",
                memory_type=MemoryType.EPISODIC,
            ),
            embedding_provider=mock_embedding_provider,
        )

        # With high threshold (0.8), only the health memory should qualify
        results = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="query: health",
            similarity_threshold=0.8,
        )

        assert len(results) == 1
        assert "Cardiovascular exercise" in results[0].memory.content
        assert results[0].similarity_score >= 0.8


@pytest.mark.asyncio
async def test_metadata_filtering(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Support metadata filtering."""
    user_id = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    async with session_factory() as session:
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Weekly running mileage goal",
                memory_type=MemoryType.GOAL,
                metadata={"category": "fitness", "priority": "high"},
            ),
            embedding_provider=mock_embedding_provider,
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Completed 10k run in 52 minutes",
                memory_type=MemoryType.EPISODIC,
                metadata={"category": "fitness", "priority": "normal"},
            ),
            embedding_provider=mock_embedding_provider,
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Prepare Q3 roadmap presentation",
                memory_type=MemoryType.GOAL,
                metadata={"category": "work", "priority": "high"},
            ),
            embedding_provider=mock_embedding_provider,
        )

        # Filter by category == fitness AND priority == high
        results = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="running and roadmap",
            metadata_filter={"category": "fitness", "priority": "high"},
        )

        assert len(results) == 1
        assert results[0].memory.content == "Weekly running mileage goal"
        assert results[0].memory.metadata["category"] == "fitness"
        assert results[0].memory.metadata["priority"] == "high"


@pytest.mark.asyncio
async def test_prevent_cross_user_retrieval(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Acceptance Criteria & Requirement: Prevent cross-user retrieval.

    A semantic query retrieves relevant memories while never returning another user's data.
    """
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    # Set identical embedding for query and both user memories
    dim = 1536
    v_target = [1.0] + [0.0] * (dim - 1)
    mock_embedding_provider.set_embedding("Confidential secret project details", v_target)
    mock_embedding_provider.set_embedding("query: confidential secret", v_target)

    async with session_factory() as session:
        # User B stores sensitive memory
        user_b_memory = await MemoryService.store_memory(
            db=session,
            user_id=user_b,
            create_data=MemoryCreate(
                content="Confidential secret project details",
                memory_type=MemoryType.SEMANTIC,
                metadata={"owner": "User B"},
            ),
            embedding_provider=mock_embedding_provider,
        )

        # User A searches with identical query
        user_a_results = await retriever.retrieve(
            db=session,
            user_id=user_a,
            query="query: confidential secret",
            similarity_threshold=0.0,
        )

        # User A MUST receive empty list, never User B's memory
        assert len(user_a_results) == 0
        assert not any(r.memory.id == user_b_memory.id for r in user_a_results)

        # User B searches with identical query and receives their memory
        user_b_results = await retriever.retrieve(
            db=session,
            user_id=user_b,
            query="query: confidential secret",
            similarity_threshold=0.0,
        )
        assert len(user_b_results) == 1
        assert user_b_results[0].memory.id == user_b_memory.id
        assert user_b_results[0].memory.user_id == user_b


@pytest.mark.asyncio
async def test_embedding_failure_handling(
    session_factory: async_sessionmaker,
) -> None:
    """Requirement: Handle embedding failures & preserve original memory text."""
    user_id = uuid.uuid4()
    failing_provider = MockEmbeddingProvider(
        fail_always=False,
        fail_on_substrings=["FAIL_TRIGGER"],
    )
    retriever = SemanticMemoryRetriever(embedding_provider=failing_provider)

    async with session_factory() as session:
        # 1. Storing memory when embedding generation fails
        # Memory creation must NOT crash; content must be preserved intact!
        original_text = "Critical observation with FAIL_TRIGGER inside content"
        memory = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content=original_text,
                memory_type=MemoryType.EPISODIC,
                metadata={"test": "failure_handling"},
            ),
            embedding_provider=failing_provider,
        )

        assert memory.id is not None
        assert memory.content == original_text  # Original text preserved
        assert memory.embedding is None  # Embedding set to None gracefully

        # 2. Updating memory when embedding generation fails
        updated_memory = await MemoryService.update_memory(
            db=session,
            memory_id=memory.id,
            user_id=user_id,
            update_data=MemoryUpdate(content="Updated content with another FAIL_TRIGGER"),
            embedding_provider=failing_provider,
        )
        assert updated_memory.content == "Updated content with another FAIL_TRIGGER"

        # 3. Querying retriever when embedding generation fails raises EmbeddingGenerationError
        with pytest.raises(EmbeddingGenerationError) as exc_info:
            await retriever.retrieve(
                db=session,
                user_id=user_id,
                query="Query containing FAIL_TRIGGER",
            )
        assert "FAIL_TRIGGER" in str(exc_info.value)


@pytest.mark.asyncio
async def test_preserve_original_memory_text(
    session_factory: async_sessionmaker,
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Requirement: Preserve original memory text."""
    user_id = uuid.uuid4()
    retriever = SemanticMemoryRetriever(embedding_provider=mock_embedding_provider)

    complex_text = (
        "### Milestone #4 Review\n"
        "- Completed unit tests with 100% coverage.\n"
        "- Next steps: Deploy to staging & run integration checks.\n"
        "Special characters: !@#$%^&*()_+-=[]{}|;':\",.<>/?\n"
        "Unicode: 🚀 LifeThread AI Platform 🤖"
    )
    async with session_factory() as session:
        saved_memory = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content=complex_text,
                memory_type=MemoryType.EPISODIC,
            ),
            embedding_provider=mock_embedding_provider,
        )

        results = await retriever.retrieve(
            db=session,
            user_id=user_id,
            query="Milestone Review staging",
            similarity_threshold=-1.0,
        )

        assert len(results) >= 1
        retrieved_content = results[0].memory.content
        assert retrieved_content == complex_text
        assert retrieved_content == saved_memory.content
