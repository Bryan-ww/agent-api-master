"""RAG document upload and retrieval endpoints."""

from __future__ import annotations

import asyncio
import selectors
import sys

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.core.auth_deps import auth_dependency, get_current_user
from src.models import User
from src.services.rag_service import rag_service

router = APIRouter(prefix="/rag", tags=["RAG"], dependencies=auth_dependency)


class RagUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str


class RagSearchRequest(BaseModel):
    query: str
    limit: int | None = None


class RagSearchResponse(BaseModel):
    results: list[dict]


@router.post("/documents", response_model=RagUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> RagUploadResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()
    try:
        document = rag_service.save_pdf(content, file.filename or "document.pdf")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(_ingest_document, document, user.identity)

    return RagUploadResponse(
        document_id=document.document_id,
        filename=document.filename,
        status="processing",
    )


@router.post("/search", response_model=RagSearchResponse)
async def search_documents(request: RagSearchRequest, user: User = Depends(get_current_user)) -> RagSearchResponse:
    results = await rag_service.search(request.query, user_id=user.identity, limit=request.limit)
    return RagSearchResponse(results=results)


def _ingest_document(document, user_id: str) -> None:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) as runner:
            runner.run(rag_service.ingest_pdf(document, user_id))
        return
    asyncio.run(rag_service.ingest_pdf(document, user_id))
