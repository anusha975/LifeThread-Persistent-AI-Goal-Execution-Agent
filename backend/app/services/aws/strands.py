import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.aws.config import AWSConfigManager

logger = logging.getLogger("lifethread.aws.strands")


class StrandItem(BaseModel):
    """Normalized context strand item representing a semantic memory, milestone, or learning node."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: uuid.UUID
    goal_id: uuid.UUID | None = None
    title: str
    content: str
    category: str = Field(default="general", description="goal_context, weakness, preference, reflection")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StrandSearchResult(BaseModel):
    """Normalized search result from strand context retrieval."""

    model_config = ConfigDict(from_attributes=True)

    strand_id: str
    title: str
    content: str
    category: str
    score: float = Field(ge=0.0, le=1.0, description="Relevance similarity score")
    goal_id: str | None = None
    citation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseStrandsProvider(ABC):
    """Abstract interface for managing and searching semantic context strands."""

    @abstractmethod
    async def search(
        self,
        query: str,
        user_id: uuid.UUID,
        *,
        goal_id: uuid.UUID | None = None,
        limit: int = 5,
        min_score: float = 0.5,
        db: AsyncSession | None = None,
    ) -> list[StrandSearchResult]:
        """Search relevant semantic strands matching query for the specified user."""
        pass

    @abstractmethod
    async def index(
        self,
        item: StrandItem,
        db: AsyncSession | None = None,
    ) -> str:
        """Index a new strand item into the semantic context base."""
        pass


class LocalStrandsProvider(BaseStrandsProvider):
    """In-memory and local database context strand provider for development and testing."""

    def __init__(self) -> None:
        self._strands: dict[str, StrandItem] = {}

    async def index(
        self,
        item: StrandItem,
        db: AsyncSession | None = None,
    ) -> str:
        self._strands[item.id] = item
        logger.debug("Indexed local strand item '%s' for user %s", item.id, item.user_id)
        return item.id

    async def search(
        self,
        query: str,
        user_id: uuid.UUID,
        *,
        goal_id: uuid.UUID | None = None,
        limit: int = 5,
        min_score: float = 0.5,
        db: AsyncSession | None = None,
    ) -> list[StrandSearchResult]:
        query_words = set(query.lower().split())
        results: list[tuple[float, StrandItem]] = []

        for item in self._strands.values():
            # Strict tenant isolation check
            if item.user_id != user_id:
                continue
            if goal_id and item.goal_id and item.goal_id != goal_id:
                continue

            content_lower = (item.title + " " + item.content).lower()
            matching_words = sum(1 for w in query_words if w in content_lower)
            score = (matching_words / max(len(query_words), 1)) if query_words else 0.5
            # Small boost if matching category or exact phrase
            if query.lower() in content_lower:
                score = min(1.0, score + 0.3)
            if score >= min_score:
                results.append((score, item))

        results.sort(key=lambda x: x[0], reverse=True)
        top_results = results[:limit]

        return [
            StrandSearchResult(
                strand_id=item.id,
                title=item.title,
                content=item.content,
                category=item.category,
                score=round(score, 3),
                goal_id=str(item.goal_id) if item.goal_id else None,
                citation=f"LocalStrand:{item.category}/{item.title}",
                metadata=item.metadata,
            )
            for score, item in top_results
        ]


class BedrockStrandsProvider(BaseStrandsProvider):
    """AWS Bedrock Knowledge Bases context strands adapter.

    Queries Amazon Bedrock Knowledge Bases using Retrieve API with:
    - Exact user_id metadata filtering to guarantee tenant isolation
    - Similarity score thresholding
    - Graceful fallback to LocalStrandsProvider when knowledge base is not configured or offline
    """

    def __init__(
        self,
        knowledge_base_id: str | None = None,
        fallback_provider: BaseStrandsProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.knowledge_base_id = knowledge_base_id or settings.AWS_STRANDS_KNOWLEDGE_BASE_ID
        self.fallback = fallback_provider or LocalStrandsProvider()

    async def index(
        self,
        item: StrandItem,
        db: AsyncSession | None = None,
    ) -> str:
        # In AWS Bedrock Knowledge Bases, documents are synced via S3 data sources.
        # We index in fallback/local store to ensure instant retrieval availability
        return await self.fallback.index(item, db)

    async def search(
        self,
        query: str,
        user_id: uuid.UUID,
        *,
        goal_id: uuid.UUID | None = None,
        limit: int = 5,
        min_score: float = 0.5,
        db: AsyncSession | None = None,
    ) -> list[StrandSearchResult]:
        if not self.knowledge_base_id or not AWSConfigManager.is_aws_available():
            logger.info("Bedrock Knowledge Base ID or credentials unconfigured; falling back to LocalStrandsProvider.")
            return await self.fallback.search(
                query=query,
                user_id=user_id,
                goal_id=goal_id,
                limit=limit,
                min_score=min_score,
                db=db,
            )

        try:
            client = AWSConfigManager.get_client("bedrock-agent-runtime")
            # Build tenant filter
            retrieval_filter: dict[str, Any] = {
                "equals": {
                    "key": "user_id",
                    "value": str(user_id),
                }
            }

            retrieval_config: dict[str, Any] = {
                "vectorSearchConfiguration": {
                    "numberOfResults": limit,
                    "filter": retrieval_filter,
                }
            }

            response = await asyncio.to_thread(
                client.retrieve,
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration=retrieval_config,
            )

            results: list[StrandSearchResult] = []
            for item in response.get("retrievalResults", []):
                score = float(item.get("score", 0.0))
                if score < min_score:
                    continue
                content = item.get("content", {}).get("text", "")
                loc = item.get("location", {})
                results.append(
                    StrandSearchResult(
                        strand_id=str(uuid.uuid4()),
                        title=loc.get("s3Location", {}).get("uri", "AWS Bedrock Strand"),
                        content=content,
                        category="knowledge_base",
                        score=score,
                        goal_id=str(goal_id) if goal_id else None,
                        citation=f"AWS Bedrock KB:{self.knowledge_base_id}",
                        metadata=item.get("metadata", {}),
                    )
                )

            if not results:
                # If remote returned empty, check local fallback
                return await self.fallback.search(
                    query=query,
                    user_id=user_id,
                    goal_id=goal_id,
                    limit=limit,
                    min_score=min_score,
                    db=db,
                )

            return results

        except Exception as e:
            logger.warning("Bedrock Strands retrieval failed (%s); falling back to LocalStrandsProvider.", e)
            return await self.fallback.search(
                query=query,
                user_id=user_id,
                goal_id=goal_id,
                limit=limit,
                min_score=min_score,
                db=db,
            )


# Singleton factory instance
_local_strands_instance = LocalStrandsProvider()


def get_strands_provider() -> BaseStrandsProvider:
    """Factory helper to obtain the configured Strands provider instance."""
    settings = get_settings()
    if settings.AWS_STRANDS_KNOWLEDGE_BASE_ID and AWSConfigManager.is_aws_available():
        return BedrockStrandsProvider(
            knowledge_base_id=settings.AWS_STRANDS_KNOWLEDGE_BASE_ID,
            fallback_provider=_local_strands_instance,
        )
    return _local_strands_instance
