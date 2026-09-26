import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.factory import get_embedding_provider
from app.services.llm.factory import get_llm_provider
from app.services.llm.provider import BaseLLMProvider, LLMMessage
from app.services.rag.citation_service import CitationService
from app.services.rag.context_builder import ContextBuilder
from app.services.rag.models import (
    RAGQueryRequest,
    RAGQueryResponse,
    RetrievedChunk,
)
from app.services.rag.reranker import Reranker
from app.services.rag.retriever import Retriever

logger = logging.getLogger("lifethread.rag.service")
audit_logger = logging.getLogger("lifethread.audit.rag.service")


class RAGService:
    """End-to-end Retrieval-Augmented Generation Service orchestrating:

    Query -> embedding -> vector retrieval -> metadata filtering -> reranking
    -> context construction -> LLM -> cited response.
    """

    _rag_cache: dict[str, tuple[float, RAGQueryResponse]] = {}
    _cache_ttl_seconds: float = 60.0

    @classmethod
    def invalidate_user_rag_cache(cls, user_id: uuid.UUID) -> None:
        """Evict all cached RAG responses for the given user."""
        prefix = f"{user_id}:"
        keys_to_del = [k for k in cls._rag_cache if k.startswith(prefix)]
        for k in keys_to_del:
            cls._rag_cache.pop(k, None)

    def __init__(
        self,
        retriever: Retriever | None = None,
        reranker: Reranker | None = None,
        context_builder: ContextBuilder | None = None,
        citation_service: CitationService | None = None,
        llm_provider: BaseLLMProvider | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> None:
        emb_prov = embedding_provider or get_embedding_provider()
        self.retriever = retriever or Retriever(embedding_provider=emb_prov)
        self.reranker = reranker or Reranker()
        self.context_builder = context_builder or ContextBuilder()
        self.citation_service = citation_service or CitationService()
        self.llm_provider = llm_provider or get_llm_provider()

    async def query(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: RAGQueryRequest,
    ) -> RAGQueryResponse:
        """Execute full RAG pipeline for the authenticated user."""
        clean_query = request.query.strip()
        if not clean_query:
            return RAGQueryResponse(
                query=request.query,
                answer="Please provide a valid question or query.",
                citations=[],
                chunks_retrieved=0,
                chunks_used=0,
                has_results=False,
            )

        # Check RAG response cache
        doc_ids_str = ",".join(str(d) for d in sorted(request.document_ids or []))
        cache_key = f"{user_id}:{clean_query}:{request.top_k}:{request.similarity_threshold}:{request.rerank}:{doc_ids_str}"
        now = time.time()
        if cache_key in self._rag_cache:
            ts, cached_resp = self._rag_cache[cache_key]
            if now - ts < self._cache_ttl_seconds:
                return cached_resp

        # 1. Query Embedding & Vector Retrieval (Strict user isolation & metadata filtering)
        retrieved_chunks = await self.retriever.retrieve(
            db=db,
            user_id=user_id,
            query=clean_query,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            metadata_filter=request.metadata_filter,
            document_ids=request.document_ids,
        )

        # 2. Handle No-Result Case (Requirement 9)
        if not retrieved_chunks:
            audit_logger.info(
                "AUDIT [RAG_NO_RESULTS] user_id=%s query='%s'",
                user_id,
                clean_query[:50],
            )
            return RAGQueryResponse(
                query=clean_query,
                answer="I could not find any relevant information in your uploaded documents to answer this question.",
                citations=[],
                chunks_retrieved=0,
                chunks_used=0,
                has_results=False,
            )

        # 3. Optional Hybrid Reranking (Requirement 5)
        chunks_to_use: list[RetrievedChunk] = retrieved_chunks
        if request.rerank:
            chunks_to_use = self.reranker.rerank(clean_query, retrieved_chunks)

        # 4. Context Construction with Prompt Injection Defense (Requirement 6 & 10)
        context_str, used_chunks = self.context_builder.build_context(
            chunks=chunks_to_use,
            max_chars=request.max_context_chars,
        )

        # 5. Extract Structured Citations (Requirement 7)
        citations = self.citation_service.extract_citations(used_chunks)

        # 6. LLM Completion with Grounding Instructions
        prompt_messages = self.context_builder.construct_llm_prompt(
            query=clean_query,
            context_str=context_str,
        )

        llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in prompt_messages]

        llm_response = await self.llm_provider.chat(
            messages=llm_messages,
            temperature=0.2,  # Low temperature for factual grounding
        )

        raw_answer = llm_response.content.strip()

        audit_logger.info(
            "AUDIT [RAG_COMPLETED] user_id=%s query='%s' retrieved=%d used=%d citations=%d model=%s",
            user_id,
            clean_query[:50],
            len(retrieved_chunks),
            len(used_chunks),
            len(citations),
            llm_response.model,
        )

        rag_resp = RAGQueryResponse(
            query=clean_query,
            answer=raw_answer,
            citations=citations,
            chunks_retrieved=len(retrieved_chunks),
            chunks_used=len(used_chunks),
            model=llm_response.model,
            has_results=True,
        )
        self._rag_cache[cache_key] = (now, rag_resp)
        return rag_resp
