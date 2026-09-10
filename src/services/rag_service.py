"""RAG document ingestion and retrieval backed by Qdrant."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import selectors
import sys
import uuid
from dataclasses import dataclass
from inspect import Traceback
from pathlib import Path
from typing import Any
from qdrant_client import QdrantClient
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog
from langchain_openai import OpenAIEmbeddings
from qdrant_client.http import models as qmodels
from src.utils.paddle_ocr import safe_filename, extract_pdf_markdown_with_paddle_api, clean_ocr_markdown

logger = structlog.get_logger(__name__)


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    upload_dir: Path = Field(default=Path("data/rag/uploads"), validation_alias="RAG_UPLOAD_DIR")
    collection_name: str = Field(default="aegra_rag", validation_alias="QDRANT_COLLECTION")

    qdrant_url: str = Field(default="http://192.168.2.14:6333", validation_alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")

    embedding_model: str = Field(default="text-embedding-v1", validation_alias="RAG_EMBEDDING_MODEL")
    embedding_api_key: str | None = Field(default="sk-686781d2af0c45f8800947870e2195d4", validation_alias="OPENAI_API_KEY")
    embedding_base_url: str | None = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", validation_alias="OPENAI_BASE_URL")
    vector_size: int = Field(default=1536, validation_alias="RAG_VECTOR_SIZE")

    # 新增：Embedding 批处理大小：Dashscope API限制一次最大提交25个chunk
    embedding_batch_size: int = Field(default=25, validation_alias="RAG_EMBEDDING_BATCH_SIZE")
    # 或者增大 chunk 大小减少数量
    chunk_size: int = Field(default=2000, validation_alias="RAG_CHUNK_SIZE")  # 从1000增加到2000
    chunk_overlap: int = Field(default=200, validation_alias="RAG_CHUNK_OVERLAP")
    max_search_results: int = Field(default=6, validation_alias="RAG_MAX_SEARCH_RESULTS")

    paddle_job_url: str = Field(default="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs", validation_alias="PADDLE_OCR_JOB_URL")
    paddle_token: str = Field(default="d4dd5978071af6e68e34a21e27330898fa00ffe8", validation_alias="PADDLE_OCR_TOKEN")
    paddle_model: str = Field(default="PaddleOCR-VL-1.6", validation_alias="PADDLE_OCR_MODEL")

    paddle_poll_interval_seconds: float = Field(default=3, validation_alias="PADDLE_OCR_POLL_INTERVAL_SECONDS")
    paddle_poll_timeout_seconds: float = Field(default=600, validation_alias="PADDLE_OCR_POLL_TIMEOUT_SECONDS")
    paddle_request_timeout_seconds: float = Field(default=60, validation_alias="PADDLE_OCR_REQUEST_TIMEOUT_SECONDS")


@dataclass(frozen=True)
class RagDocument:
    document_id: str
    filename: str
    path: Path
    sha256: str


class RagService:
    def __init__(self, settings: RagSettings | None = None) -> None:
        self.settings = settings or RagSettings()
        self._client: Any | None = None
        self._embeddings: Any | None = None

    def save_pdf(self, content: bytes, filename: str) -> RagDocument:
        """ 上传文件保存再本地 """
        if not content:
            raise ValueError("Uploaded PDF is empty")
        safe_name = safe_filename(filename)
        document_id = uuid.uuid4().hex
        digest = hashlib.sha256(content).hexdigest()
        target_dir: Path = self.settings.upload_dir / document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        path: Path = target_dir / safe_name
        path.write_bytes(content)
        return RagDocument(document_id=document_id, filename=safe_name, path=path, sha256=digest)

    async def ingest_pdf(self, document: RagDocument, user_id: str) -> None:
        """ RAG复杂流程处理 """
        params = {
            "path": document.path,
            "paddle_job_url": self.settings.paddle_job_url,
            "paddle_token": self.settings.paddle_token,
            "paddle_model": self.settings.paddle_model,
            "paddle_request_timeout_seconds": self.settings.paddle_request_timeout_seconds,
            "paddle_poll_timeout_seconds": self.settings.paddle_poll_timeout_seconds,
            "paddle_poll_interval_seconds": self.settings.paddle_poll_interval_seconds,
        }

        try:
            # 1、使用PaddleOCR提取PDF文本：异步线程处理
            text = await asyncio.to_thread(extract_pdf_markdown_with_paddle_api, **params)

            # 2、清理OCR识别的文本：PDF文件返回的是MD格式
            text = clean_ocr_markdown(text)

            # 3、分 chunk：块大小、重叠部分
            chunks = self._chunk_text(text, self.settings.chunk_size, self.settings.chunk_overlap)
            if not chunks:
                logger.warning("rag_ingest_empty_document", document_id=document.document_id, filename=document.filename)
                return

            # 4、文本向量化：OpenAI Embedding API
            vectors = await self._embed_documents(chunks)

            # 5、将 chunk 和向量保存到 Qdrant
            await asyncio.to_thread(self._upsert_chunks, document, user_id, chunks, vectors)

            logger.info("rag_ingest_completed", document_id=document.document_id, filename=document.filename, chunks=len(chunks),)
        except Exception:
            logger.exception("rag_ingest_failed", document_id=document.document_id, filename=document.filename)
            raise


    async def search(self, query: str, user_id: str = "anonymous", limit: int | None = None) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        vector = await self._embed_query(query)
        result =  await asyncio.to_thread(self._search_qdrant, vector, user_id, limit or self.settings.max_search_results)
        print(result)
        return result

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key,
                check_compatibility=False,
            )
            self._ensure_collection()
        return self._client

    def _get_embeddings(self) -> Any:
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model=self.settings.embedding_model,
                api_key=self.settings.embedding_api_key,
                base_url=self.settings.embedding_base_url,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            )
        return self._embeddings

    def _ensure_collection(self) -> None:
        assert self._client is not None
        if self._client.collection_exists(self.settings.collection_name):
            return
        self._client.create_collection(
            collection_name=self.settings.collection_name,
            vectors_config=qmodels.VectorParams(size=self.settings.vector_size, distance=qmodels.Distance.COSINE),
        )
        self._client.create_payload_index(
            collection_name=self.settings.collection_name,
            field_name="user_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )

    async def _embed_documents(self, chunks: list[str]) -> list[list[float]]:
        """使用并发批处理提升性能: 分批次、限并发数（信号量）"""
        embeddings = self._get_embeddings()

        max_batch_size = self.settings.embedding_batch_size
        batches = [
            chunks[i:i + max_batch_size]
            for i in range(0, len(chunks), max_batch_size)
        ]

        logger.info("embedding_start", total_chunks=len(chunks), total_batches=len(batches))

        # 并发处理所有批次（限制并发数避免过载）
        semaphore = asyncio.Semaphore(3)  # 最多3个并发请求

        async def embed_batch(batch_index: int, batch: list[str]) -> tuple[int, list[list[float]]]:
            async with semaphore:
                logger.info("embedding_batch_start", batch_index=batch_index + 1, total_batches=len(batches), batch_size=len(batch))
                try:
                    vectors = await embeddings.aembed_documents(batch)
                    logger.info("embedding_batch_success", batch_index=batch_index + 1, vectors_count=len(vectors))
                    return batch_index, vectors
                except Exception as e:
                    logger.exception("embedding_batch_failed", batch_index=batch_index + 1, error=str(e))
                    raise

        # 并发执行所有批次
        tasks = [embed_batch(i, batch) for i, batch in enumerate(batches)]
        results = await asyncio.gather(*tasks)

        # 按原始顺序合并结果
        results.sort(key=lambda x: x[0])
        all_vectors = [vector for _, vectors in results for vector in vectors]

        logger.info("embedding_completed", total_chunks=len(chunks), total_vectors=len(all_vectors))
        return all_vectors


    async def _embed_query(self, query: str) -> list[float]:
        embeddings = self._get_embeddings()
        return await embeddings.aembed_query(query)

    def _upsert_chunks(
        self,
        document: RagDocument,
        user_id: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> None:
        client = self._get_client()
        points = [
            qmodels.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document.document_id}:{idx}")),
                vector=vector,
                payload={
                    "user_id": user_id,
                    "document_id": document.document_id,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "chunk_index": idx,
                    "text": chunk,
                },
            )
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        client.upsert(collection_name=self.settings.collection_name, points=points)

    def _search_qdrant(self, vector: list[float], user_id: str, limit: int) -> list[dict[str, Any]]:
        client = self._get_client()
        query_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="user_id",
                    match=qmodels.MatchValue(value=user_id),
                )
            ]
        )

        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=self.settings.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            hits = response.points
        else:
            hits = client.search(
                collection_name=self.settings.collection_name,
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )

        results: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                {
                    "score": hit.score,
                    "document_id": payload.get("document_id"),
                    "filename": payload.get("filename"),
                    "chunk_index": payload.get("chunk_index"),
                    "text": payload.get("text", ""),
                }
            )
        return results

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + chunk_size, len(normalized))
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(normalized):
                break
            start = max(end - overlap, start + 1)
        return chunks

rag_service = RagService()


if __name__ == '__main__':
    document_id, safe_name = "d172e3496143418d8bf3927a338d70f9", "_2021_-_.pdf"
    file_path: Path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) /  rag_service.settings.upload_dir / document_id / safe_name
    rag_document = RagDocument(document_id=document_id, filename=safe_name, path=file_path, sha256="")

    # 方式1：最简单（推荐）
    try:
        # asyncio.run(rag_service.ingest_pdf(rag_document, "1"))
        asyncio.run(rag_service.search("温度和湿度数据", "100", 1))
    except Exception as e:
        import traceback
        traceback.print_exc()
