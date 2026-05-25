import logging
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..workers.pipeline_orchestrator import process_document
from ..query.query_orchestrator import answer_question
from ..services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    conversationHistory: list[dict[str, Any]] = []


class SetRepositoryRequest(BaseModel):
    repository: str


ALLOWED_REPOSITORIES = {"pending_review", "reviewer_approved", "certified", "rejected"}


@router.get("/health")
async def health() -> dict[str, str]:
    """This function provides a basic health check endpoint."""
    return {"status": "ok"}


@router.post("/internal/process/{document_id}")
async def trigger_process(document_id: str) -> dict[str, str]:
    """This function manually triggers processing for one document."""
    await process_document(document_id)
    return {"status": "queued", "documentId": document_id}


@router.post("/query/answer")
async def query_answer(payload: QueryRequest) -> dict[str, Any]:
    """This function runs the query orchestration pipeline."""
    return await answer_question(payload.question, payload.conversationHistory)


@router.post("/internal/set-repository/{document_id}")
async def set_repository(document_id: str, payload: SetRepositoryRequest) -> dict[str, Any]:
    """Flips the repository tag on every Qdrant chunk that belongs to a document."""
    if payload.repository not in ALLOWED_REPOSITORIES:
        raise HTTPException(
            status_code=400,
            detail=f"repository must be one of {sorted(ALLOWED_REPOSITORIES)}",
        )
    logger.info(
        "[set-repository] documentId=%s -> repository=%s",
        document_id,
        payload.repository,
    )
    try:
        qdrant = QdrantService()
        updated = qdrant.update_repository(document_id, payload.repository)

        if updated == 0:
            # Document ID was not found in Qdrant at all.
            # This can happen if processing failed or document was never indexed.
            raise HTTPException(
                status_code=404,
                detail=f"No chunks found in Qdrant for document {document_id}. "
                       f"Document may not have been processed yet.",
            )

        logger.info(
            "[set-repository] documentId=%s repository=%s updatedChunks=%d",
            document_id,
            payload.repository,
            updated,
        )
        return {
            "success": True,
            "documentId": document_id,
            "repository": payload.repository,
            "updatedChunks": updated,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "[set-repository] failed documentId=%s repository=%s error=%s",
            document_id,
            payload.repository,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/internal/update-chunks")
async def update_chunks(payload: dict[str, Any]) -> dict[str, Any]:
    """Legacy placeholder kept for backward compatibility. Use /internal/set-repository instead."""
    return {"status": "not_implemented", "payload": payload}
