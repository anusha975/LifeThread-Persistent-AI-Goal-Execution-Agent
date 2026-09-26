import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import DocumentStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.schemas.document import (
    DocumentChunkListResponse,
    DocumentChunkResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResult,
)
from app.services.document import DocumentService
from app.services.document_pipeline.errors import (
    DocumentDuplicateError,
    DocumentExtractionError,
    DocumentValidationError,
)

logger = logging.getLogger("lifethread.api.documents")
router = APIRouter(prefix="/documents", tags=["Document Intelligence Pipeline"])


@router.post(
    "/upload",
    response_model=DocumentUploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload knowledge document (PDF, TXT, Markdown)",
)
async def upload_document(
    file: Annotated[UploadFile, File(description="File to upload (PDF, TXT, or Markdown)")],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    chunk_size: Annotated[
        int | None,
        Query(ge=50, le=5000, description="Optional custom chunk size in characters"),
    ] = None,
    chunk_overlap: Annotated[
        int | None,
        Query(ge=0, le=1000, description="Optional custom chunk overlap in characters"),
    ] = None,
    allow_duplicate: Annotated[
        bool,
        Query(description="Allow re-uploading identical document"),
    ] = False,
) -> DocumentUploadResult:
    """Execute end-to-end document intelligence pipeline:

    Upload -> validation -> extraction -> cleaning -> chunking -> metadata.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing.",
        )

    try:
        content_bytes = await file.read()
    except Exception as e:
        logger.error("Failed to read uploaded file: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file data.",
        ) from e

    try:
        result = await DocumentService.ingest_document(
            db=db,
            user_id=current_user.id,
            filename=file.filename,
            file_bytes=content_bytes,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            allow_duplicate=allow_duplicate,
        )
        await db.commit()
        return result
    except DocumentValidationError as e:
        await db.rollback()
        from app.core.audit import SecurityAuditService, SecurityEventType
        SecurityAuditService.record_event(
            event_type=SecurityEventType.FILE_UPLOAD_REJECTED,
            user_id=str(current_user.id),
            action="UPLOAD_DOCUMENT",
            details={"filename": file.filename, "reason": str(e)},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except DocumentDuplicateError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except DocumentExtractionError as e:
        await db.commit()  # Keep failed document record for audit
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Text extraction failed: {e!s}",
        ) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Unexpected error processing document upload: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing document.",
        ) from e


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List uploaded knowledge documents",
)
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Annotated[
        DocumentStatus | None,
        Query(alias="status", description="Filter by document status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    """List documents belonging to the authenticated user."""
    docs, total = await DocumentService.list_documents(
        db=db,
        user_id=current_user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
)
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DocumentResponse:
    """Retrieve details for a specific document owned by the user."""
    doc = await DocumentService.get_document(
        db=db, document_id=document_id, user_id=current_user.id
    )
    return DocumentResponse.model_validate(doc)


@router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunkListResponse,
    summary="Get extracted chunks for document",
)
async def get_document_chunks(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentChunkListResponse:
    """Retrieve text chunks extracted from a specific document."""
    chunks, total = await DocumentService.get_document_chunks(
        db=db,
        document_id=document_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return DocumentChunkListResponse(
        items=[DocumentChunkResponse.model_validate(c) for c in chunks],
        total=total,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all chunks",
)
async def delete_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Delete a document and cascade delete all its chunks."""
    await DocumentService.delete_document(db=db, document_id=document_id, user_id=current_user.id)
    await db.commit()
