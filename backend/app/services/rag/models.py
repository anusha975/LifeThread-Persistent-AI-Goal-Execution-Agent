import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class RetrievedChunk:
    """Internal representation of a retrieved document chunk with similarity scores."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    content: str
    chunk_index: int
    metadata: dict[str, Any]
    similarity_score: float
    distance: float
    page_number: int | None = None
    rerank_score: float | None = None


class Citation(BaseModel):
    """Source provenance citation for a grounded fact or answer statement."""

    citation_index: int = Field(..., description="Numeric citation reference index (e.g. 1, 2)")
    document_id: uuid.UUID = Field(..., description="UUID of source document")
    filename: str = Field(..., description="Original filename of the cited document")
    chunk_id: uuid.UUID = Field(..., description="UUID of cited chunk")
    chunk_index: int = Field(..., description="Sequential index of the cited chunk")
    page_number: int | None = Field(default=None, description="Page number if document is PDF")
    excerpt: str = Field(..., description="Short snippet demonstrating provenance")
    relevance_score: float = Field(..., description="Relevance score (0.0 to 1.0)")


class RAGQueryRequest(BaseModel):
    """User request payload for retrieval-augmented generation question answering."""

    query: str = Field(..., min_length=1, description="Question or prompt to answer from documents")
    top_k: int = Field(
        default=5, ge=1, le=50, description="Maximum number of candidate chunks to retrieve"
    )
    similarity_threshold: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Minimum vector similarity threshold for chunks (-1.0 to 1.0)",
    )
    rerank: bool = Field(default=True, description="Whether to apply keyword/hybrid reranking")
    metadata_filter: dict[str, Any] | None = Field(
        default=None, description="Optional key-value filters on chunk metadata"
    )
    document_ids: list[uuid.UUID] | None = Field(
        default=None, description="Optional filter to restrict retrieval to specific documents"
    )
    max_context_chars: int = Field(
        default=4000,
        ge=500,
        le=20000,
        description="Maximum characters of document context to feed to LLM",
    )


class RAGQueryResponse(BaseModel):
    """Structured response payload returned by RAGService."""

    query: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    chunks_retrieved: int = 0
    chunks_used: int = 0
    model: str = "mock-model"
    has_results: bool = True
