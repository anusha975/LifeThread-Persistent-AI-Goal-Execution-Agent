import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.rag.models import RAGQueryRequest, RAGQueryResponse
from app.services.rag.service import RAGService

logger = logging.getLogger("lifethread.api.rag")
router = APIRouter(prefix="/rag", tags=["RAG Engine"])


@router.post(
    "/query",
    response_model=RAGQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question over uploaded knowledge documents",
)
async def query_knowledge_documents(
    request: RAGQueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> RAGQueryResponse:
    """Execute end-to-end retrieval-augmented generation pipeline over authenticated user documents:

    Query -> embedding -> vector retrieval -> metadata filtering -> reranking
    -> context construction -> LLM -> cited response.
    """
    from app.core.prompt_guard import PromptGuard

    _, safe_query = PromptGuard.inspect_and_defend(
        text=request.query,
        user_id=str(current_user.id),
        action="RAG_QUERY_SCAN",
    )
    request.query = safe_query

    rag_service = RAGService()
    return await rag_service.query(
        db=db,
        user_id=current_user.id,
        request=request,
    )
