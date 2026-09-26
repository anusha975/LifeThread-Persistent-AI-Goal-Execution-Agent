import hashlib
import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.context_engine.tokenizer import count_tokens


class ContextSource(StrEnum):
    """Context sources strictly ordered by life-agent context priority.

    Priority hierarchy:
    1. Current task
    2. Current goal state
    3. Current constraints
    4. Recent relevant conversation
    5. Relevant memories
    6. Relevant documents
    7. Relevant historical events
    """

    CURRENT_TASK = "current_task"
    CURRENT_GOAL = "current_goal"
    CONSTRAINTS = "constraints"
    CONVERSATION = "conversation"
    MEMORIES = "memories"
    DOCUMENTS = "documents"
    HISTORICAL_EVENTS = "historical_events"

    @property
    def default_priority(self) -> int:
        """Return 1-indexed priority ranking (1 is highest priority)."""
        mapping = {
            ContextSource.CURRENT_TASK: 1,
            ContextSource.CURRENT_GOAL: 2,
            ContextSource.CONSTRAINTS: 3,
            ContextSource.CONVERSATION: 4,
            ContextSource.MEMORIES: 5,
            ContextSource.DOCUMENTS: 6,
            ContextSource.HISTORICAL_EVENTS: 7,
        }
        return mapping[self]

    @property
    def display_label(self) -> str:
        """Human-readable section header for prompt construction."""
        labels = {
            ContextSource.CURRENT_TASK: "Current Task",
            ContextSource.CURRENT_GOAL: "Current Goal State",
            ContextSource.CONSTRAINTS: "Current Constraints",
            ContextSource.CONVERSATION: "Recent Relevant Conversation",
            ContextSource.MEMORIES: "Relevant Memories",
            ContextSource.DOCUMENTS: "Relevant Documents",
            ContextSource.HISTORICAL_EVENTS: "Relevant Historical Events",
        }
        return labels[self]


class ContextItem(BaseModel):
    """An individual candidate unit of agent context."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the context item",
    )
    source: ContextSource = Field(description="Context source classification")
    content: str = Field(description="Raw text content of the context item")
    user_id: uuid.UUID = Field(description="Owner user ID for strict multi-tenant isolation")
    source_attribution: str = Field(
        description="Human-readable provenance citation (e.g. Document: file.pdf #chunk 1)"
    )
    tokens: int = Field(
        default=0,
        ge=0,
        description="Token count of content. Computed automatically if 0.",
    )
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance score normalized between 0.0 and 1.0",
    )
    priority: int | None = Field(
        default=None,
        ge=1,
        description="Custom priority override. If None, defaults to source.default_priority",
    )
    timestamp: datetime | None = Field(
        default=None,
        description="Temporal timestamp for recency scoring / chronological ordering",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured provenance and context metadata",
    )

    @model_validator(mode="after")
    def compute_tokens_if_zero(self) -> "ContextItem":
        if self.tokens <= 0 and self.content:
            self.tokens = count_tokens(self.content)
        return self

    @property
    def effective_priority(self) -> int:
        """Effective priority: custom override if present, else source default."""
        return self.priority if self.priority is not None else self.source.default_priority

    @property
    def normalized_content(self) -> str:
        """Normalized string for deduplication."""
        return re.sub(r"\s+", " ", self.content.strip().lower())

    @property
    def content_hash(self) -> str:
        """Deterministic SHA256 digest of normalized content."""
        return hashlib.sha256(self.normalized_content.encode("utf-8")).hexdigest()


class ContextBudget(BaseModel):
    """Token-aware context budget manager with per-source quotas and threshold controls."""

    total_tokens: int = Field(
        default=4000,
        ge=1,
        description="Absolute maximum token budget allocated for context",
    )
    reserved_tokens_per_source: dict[ContextSource, int] = Field(
        default_factory=dict,
        description="Minimum guaranteed token budget reserved per source category",
    )
    max_tokens_per_source: dict[ContextSource, int] = Field(
        default_factory=dict,
        description="Maximum token ceiling per source category to prevent starvation",
    )
    min_relevance_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score required for candidate consideration",
    )
    used_tokens: int = Field(
        default=0,
        ge=0,
        description="Current consumed token count",
    )
    tokens_used_by_source: dict[ContextSource, int] = Field(
        default_factory=dict,
        description="Token consumption breakdown by source category",
    )

    @property
    def remaining_tokens(self) -> int:
        """Unused tokens remaining under the total budget."""
        return max(0, self.total_tokens - self.used_tokens)

    def can_fit(self, tokens: int, source: ContextSource) -> bool:
        """Check if an item of given token size fits within the total and source budget."""
        if tokens <= 0:
            return True
        if self.used_tokens + tokens > self.total_tokens:
            return False
        if source in self.max_tokens_per_source:
            current_src = self.tokens_used_by_source.get(source, 0)
            if current_src + tokens > self.max_tokens_per_source[source]:
                return False
        return True

    def consume(self, item: ContextItem) -> bool:
        """Consume budget for an item. Returns True if successfully allocated."""
        if not self.can_fit(item.tokens, item.source):
            return False
        self.used_tokens += item.tokens
        self.tokens_used_by_source[item.source] = (
            self.tokens_used_by_source.get(item.source, 0) + item.tokens
        )
        return True

    def reset(self) -> None:
        """Reset budget consumption counters."""
        self.used_tokens = 0
        self.tokens_used_by_source.clear()


class BuiltContext(BaseModel):
    """The structured result returned by ContextBuilder."""

    items: list[ContextItem] = Field(
        default_factory=list,
        description="Included context items sorted deterministically",
    )
    total_tokens: int = Field(
        ge=0,
        description="Total tokens consumed across all included items",
    )
    token_budget: int = Field(
        ge=1,
        description="Total token budget ceiling configured",
    )
    items_by_source: dict[str, list[ContextItem]] = Field(
        default_factory=dict,
        description="Included items grouped by source",
    )
    sources_included: list[str] = Field(
        default_factory=list,
        description="Distinct source categories present in the context",
    )
    dropped_items_count: int = Field(
        default=0,
        ge=0,
        description="Number of candidate items excluded due to budget, threshold, or deduplication",
    )
    formatted_prompt: str = Field(
        default="",
        description="Deterministic, formatted markdown/XML prompt representation",
    )
