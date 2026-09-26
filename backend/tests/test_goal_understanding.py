import json
from datetime import UTC, datetime

import pytest
from app.core.token_store import TokenDenylist
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.llm import get_llm_provider_dep
from app.main import create_application
from app.services.llm.mock import MockLLMProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """Fixture providing an inspectable MockLLMProvider."""
    return MockLLMProvider()


@pytest.fixture
async def app_client(mock_llm: MockLLMProvider):
    """Fixture creating an in-memory SQLite database and authenticated test client with mock LLM."""
    TokenDenylist.clear()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_llm():
        yield mock_llm

    app = create_application()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider_dep] = override_get_llm

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Register and login user
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "engineer@example.com",
                "password": "StrongPassword123!",
                "display_name": "AI Engineer",
                "timezone": "America/New_York",
            },
        )
        assert reg_resp.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "engineer@example.com", "password": "StrongPassword123!"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        yield client, mock_llm, session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_understand_goal_interview_ready_success(app_client):
    """Test standard goal extraction: 'I need to become interview-ready for an AI Engineer role in 10 days.'"""
    client, mock_llm, session_factory = app_client

    ref_time = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
    llm_payload = {
        "title": "AI Engineer Interview Preparation",
        "objective": "Become interview-ready for an AI Engineer role",
        "description": "Comprehensive preparation covering AI systems, ML algorithms, and coding.",
        "deadline": "2026-10-04T12:00:00Z",
        "priority": "high",
        "constraints": [{"type": "time", "value": "10 days", "metadata": {"days": 10}}],
        "success_criteria": [
            "Pass mock interview with score >= 85%",
            "Solve 20 system design problems",
            "Review transformer architectures",
        ],
        "milestones": [
            {"title": "Core ML & Transformers Review", "deadline": "2026-09-28T12:00:00Z"},
            {"title": "System Design Practice", "deadline": "2026-10-02T12:00:00Z"},
        ],
        "is_ambiguous": False,
        "missing_information": [],
        "clarification_questions": [],
        "confidence_score": 0.95,
    }
    mock_llm.set_response(json.dumps(llm_payload))

    raw_input = "I need to become interview-ready for an AI Engineer role in 10 days."
    resp = await client.post(
        "/api/v1/goals/understand",
        json={
            "text": raw_input,
            "reference_time": ref_time.isoformat(),
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    # 1. Verify structured extraction matches requirements
    assert data["objective"] == "Become interview-ready for an AI Engineer role"
    assert data["title"] == "AI Engineer Interview Preparation"
    assert data["priority"] == "high"
    assert len(data["constraints"]) == 1
    assert data["constraints"][0]["type"] == "time"
    assert data["constraints"][0]["value"] == "10 days"
    assert len(data["success_criteria"]) == 3
    assert "Pass mock interview with score >= 85%" in data["success_criteria"]
    assert data["deadline"] == "2026-10-04T12:00:00Z"
    assert data["is_ambiguous"] is False
    assert data["needs_clarification"] is False

    # 2. Requirement 10: Store raw user request separately from structured interpretation
    assert data["raw_request"] == raw_input
    assert "structured_interpretation" in data
    assert data["structured_interpretation"]["objective"] == data["objective"]
    assert data["structured_interpretation"]["priority"] == "high"

    # 3. Verify no goal was automatically created in the database
    list_resp = await client.get("/api/v1/goals")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_detect_ambiguity_and_missing_information(app_client):
    """Test that vague goals trigger ambiguity detection and generate clarification questions."""
    client, mock_llm, _ = app_client

    llm_payload = {
        "title": "Improve Coding Skills",
        "objective": "Get better at coding stuff soon",
        "description": None,
        "deadline": None,
        "priority": "medium",
        "constraints": [],
        "success_criteria": [],
        "milestones": [],
        "is_ambiguous": True,
        "missing_information": [
            "Target programming language or framework",
            "Concrete deliverable or benchmark",
            "Target timeline",
        ],
        "clarification_questions": [
            "What specific language or domain do you want to master?",
            "What timeline or deadline do you have in mind?",
        ],
        "confidence_score": 0.45,
    }
    mock_llm.set_response(json.dumps(llm_payload))

    resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": "I want to get better at coding stuff soon."},
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["is_ambiguous"] is True
    assert data["needs_clarification"] is True
    assert len(data["missing_information"]) >= 1
    assert len(data["clarification_questions"]) >= 1
    assert data["confidence_score"] <= 0.6


@pytest.mark.asyncio
async def test_malformed_llm_json_safely_rejected(app_client):
    """Test that non-JSON output from LLM is safely caught and returns HTTP 422 instead of crashing."""
    client, mock_llm, _ = app_client

    # Model returns raw natural language instead of required JSON
    mock_llm.set_response(
        "Sure! I can help you prepare for an AI Engineer role. First, let's look at Python..."
    )

    resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": "I need to prepare for AI Engineer interview."},
    )

    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "MALFORMED_LLM_OUTPUT"
    assert "Invalid JSON" in data["error"]["message"]


@pytest.mark.asyncio
async def test_malformed_llm_schema_mismatch_safely_rejected(app_client):
    """Test that JSON with missing mandatory fields is safely rejected with HTTP 422."""
    client, mock_llm, _ = app_client

    # Missing mandatory 'objective' and 'title'
    mock_llm.set_response(json.dumps({"some_key": "some_value"}))

    resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": "I need to prepare for AI Engineer interview."},
    )

    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "MALFORMED_LLM_OUTPUT"
    assert "Schema validation failed" in data["error"]["message"]


@pytest.mark.asyncio
async def test_never_invent_constraints(app_client):
    """Test Requirement 9: Never invent constraints if the user does not state them."""
    client, mock_llm, _ = app_client

    llm_payload = {
        "title": "Learn Rust",
        "objective": "Learn Rust programming fundamentals",
        "description": None,
        "deadline": None,
        "priority": "medium",
        "constraints": [],  # No constraints stated
        "success_criteria": ["Build a CLI tool in Rust"],
        "milestones": [],
        "is_ambiguous": False,
        "missing_information": [],
        "clarification_questions": [],
        "confidence_score": 0.9,
    }
    mock_llm.set_response(json.dumps(llm_payload))

    resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": "I want to learn Rust programming fundamentals."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["constraints"] == []
    assert data["structured_interpretation"]["constraints"] == []


@pytest.mark.asyncio
async def test_timezone_date_normalization(app_client):
    """Test Requirement 8: Normalize relative dates using user timezone."""
    client, mock_llm, _ = app_client

    # User in Asia/Kolkata timezone (+05:30)
    ref_time = datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC)

    # LLM returns localized ISO string for relative 10-day deadline
    # 2026-09-24 + 10 days in Asia/Kolkata = 2026-10-04 15:30:00+05:30 -> 2026-10-04T10:00:00Z in UTC
    llm_payload = {
        "title": "Launch Mobile App",
        "objective": "Launch mobile app on App Store in 10 days",
        "description": None,
        "deadline": "2026-10-04T15:30:00+05:30",
        "priority": "high",
        "constraints": [{"type": "time", "value": "10 days", "metadata": {}}],
        "success_criteria": ["App submitted to App Store review"],
        "milestones": [],
        "is_ambiguous": False,
        "missing_information": [],
        "clarification_questions": [],
        "confidence_score": 0.95,
    }
    mock_llm.set_response(json.dumps(llm_payload))

    resp = await client.post(
        "/api/v1/goals/understand",
        json={
            "text": "Launch mobile app on App Store in 10 days",
            "timezone": "Asia/Kolkata",
            "reference_time": ref_time.isoformat(),
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    # Normalized to UTC
    assert data["deadline"] == "2026-10-04T10:00:00Z"


@pytest.mark.asyncio
async def test_clarification_answers_workflow(app_client):
    """Test that providing clarification answers resolves previously detected ambiguity."""
    client, mock_llm, _ = app_client

    llm_payload = {
        "title": "Machine Learning Specialization",
        "objective": "Complete Stanford CS229 Machine Learning course in 30 days",
        "description": "Covering supervised learning, unsupervised learning, and deep learning.",
        "deadline": "2026-10-24T12:00:00Z",
        "priority": "high",
        "constraints": [{"type": "scope", "value": "Stanford CS229 syllabus", "metadata": {}}],
        "success_criteria": ["Complete all 5 problem sets", "Score >= 90% on final exam"],
        "milestones": [],
        "is_ambiguous": False,
        "missing_information": [],
        "clarification_questions": [],
        "confidence_score": 0.95,
    }
    mock_llm.set_response(json.dumps(llm_payload))

    resp = await client.post(
        "/api/v1/goals/understand",
        json={
            "text": "I want to finish the machine learning course.",
            "clarification_answers": {
                "What specific course?": "Stanford CS229 Machine Learning",
                "What timeline?": "30 days",
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_ambiguous"] is False
    assert data["needs_clarification"] is False


@pytest.mark.asyncio
async def test_llm_markdown_fence_stripping(app_client):
    """Test that models returning JSON wrapped in ```json ... ``` codeblocks are parsed cleanly."""
    client, mock_llm, _ = app_client

    wrapped_content = """```json
{
  "title": "Write Technical Blog Post",
  "objective": "Publish an in-depth article on Vector Databases",
  "description": null,
  "deadline": null,
  "priority": "medium",
  "constraints": [],
  "success_criteria": ["Publish on Medium", "Attain 500 claps"],
  "milestones": [],
  "is_ambiguous": false,
  "missing_information": [],
  "clarification_questions": [],
  "confidence_score": 0.92
}
```"""
    mock_llm.set_response(wrapped_content)

    resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": "I want to publish an in-depth article on Vector Databases."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Write Technical Blog Post"
    assert data["objective"] == "Publish an in-depth article on Vector Databases"
