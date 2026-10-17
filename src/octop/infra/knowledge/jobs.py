"""In-process document indexing jobs."""

from __future__ import annotations

import asyncio
from typing import Any

from octop.infra.knowledge.chunk import chunk_text
from octop.infra.knowledge.embed import embed_knowledge_texts
from octop.infra.knowledge.files import document_path
from octop.infra.knowledge.gate import assert_knowledge_usable
from octop.infra.knowledge.index import KnowledgeIndex
from octop.infra.knowledge.ocr import optional_ocr_extractor
from octop.infra.knowledge.params import get_advanced_settings
from octop.infra.knowledge.parse import parse_document

# Parsing/OCR also consumes memory; only one document should be in flight.
INDEX_CONCURRENCY = 1
_index_semaphore: asyncio.Semaphore | None = None


def reset_index_semaphore_for_tests() -> None:
    """Drop the cached semaphore so tests can change INDEX_CONCURRENCY."""
    global _index_semaphore
    _index_semaphore = None


def _get_index_semaphore() -> asyncio.Semaphore:
    global _index_semaphore
    if _index_semaphore is None:
        _index_semaphore = asyncio.Semaphore(INDEX_CONCURRENCY)
    return _index_semaphore


def process_document(services: Any, kb_id: str, doc_id: str) -> None:
    """Synchronously parse, embed, and atomically replace one document's chunks."""
    repo = services.knowledge_repo
    document = repo.get_document(doc_id)
    base = repo.get_base(kb_id)
    if document is None or document.kb_id != kb_id or base is None:
        raise LookupError("knowledge document or base not found")
    # Enterprise/shared indexes retain the control-plane embedding gate.
    # Personal indexes are edge-local and select their ONNX model below, so a
    # missing enterprise provider must never prevent private indexing.
    if base.shared:
        assert_knowledge_usable(
            services.settings_repo.get, getattr(services, "provider_repo", None)
        )
    if document.is_dir:
        return
    repo.update_document(doc_id, status="processing", error_message="")
    try:
        path = document_path(kb_id, doc_id, document.filename)
        try:
            ocr = optional_ocr_extractor(services, personal=not base.shared)
        except TypeError as exc:
            # Compatibility for test doubles and third-party integrations
            # implementing the pre-scope one-argument helper.
            if "unexpected keyword argument 'personal'" not in str(exc):
                raise
            ocr = optional_ocr_extractor(services)
        text = parse_document(path, ocr=ocr)
        knobs = get_advanced_settings(services.settings_repo.get)
        chunks = chunk_text(text, size=knobs["chunk_size"], overlap=knobs["chunk_overlap"])
        if not (text or "").strip() or not chunks:
            raise ValueError("knowledge document has no extractable text")
        try:
            embeddings = embed_knowledge_texts(services, chunks, base=base)
        except TypeError as exc:
            # Keep compatibility with small test/integration doubles written
            # before the scope-aware ``base`` argument was introduced.
            if "unexpected keyword argument 'base'" not in str(exc):
                raise
            embeddings = embed_knowledge_texts(services, chunks)
        KnowledgeIndex(kb_id).replace_doc_chunks(doc_id, chunks, embeddings)
        dimension = len(embeddings[0]) if embeddings else 0
        repo.update_document(doc_id, status="ready", error_message="", chunk_count=len(chunks))
        if dimension and base.embedding_dim != dimension:
            repo.update_base(kb_id, embedding_dim=dimension)
    except Exception as exc:
        repo.update_document(doc_id, status="failed", error_message=str(exc), chunk_count=0)
        raise


def enqueue_index_document(services: Any, kb_id: str, doc_id: str) -> asyncio.Task[None]:
    """Schedule CPU- and I/O-bound indexing outside the event loop."""
    loop = asyncio.get_running_loop()
    sem = _get_index_semaphore()

    async def _run() -> None:
        async with sem:
            await loop.run_in_executor(None, process_document, services, kb_id, doc_id)

    return asyncio.create_task(_run())


def reindex_all_documents(
    services: Any,
    embedding_model: str,
    *,
    shared_only: bool = False,
    personal_only: bool = False,
    personal_owner_id: int | None = None,
) -> int:
    """Reset indexes after an embedding change and schedule fresh work.

    Enterprise setting changes only touch shared bases.  Personal model changes
    can explicitly pass ``personal_only=True``; that path never checks the
    enterprise embedding gate and never mutates shared rows.
    """
    if shared_only and personal_only:
        raise ValueError("shared_only and personal_only cannot both be enabled")
    if not shared_only and not personal_only:
        documents = services.knowledge_repo.reindex_all_documents(embedding_model)
    else:
        documents = []
        bases = (
            services.knowledge_repo.list_shared()
            if shared_only
            else [
                base
                for base in services.knowledge_repo.list_all()
                if not base.shared
                and (personal_owner_id is None or int(base.owner_user_id) == int(personal_owner_id))
            ]
        )
        for base in bases:
            services.knowledge_repo.update_base(
                base.id, embedding_model=embedding_model, embedding_dim=0
            )
            for document in services.knowledge_repo.list_documents(base.id):
                if document.is_dir:
                    continue
                services.knowledge_repo.update_document(
                    document.id, status="pending", error_message="", chunk_count=0
                )
                refreshed = services.knowledge_repo.get_document(document.id)
                if refreshed is not None:
                    documents.append(refreshed)
    for document in documents:
        enqueue_index_document(services, document.kb_id, document.id)
    return len(documents)


def resume_pending_index_jobs(services: Any) -> None:
    """Resume pending work and jobs interrupted by a prior process shutdown."""
    documents = services.knowledge_repo.resume_pending_documents()
    for document in documents:
        enqueue_index_document(services, document.kb_id, document.id)


def retry_failed_index_jobs(
    services: Any,
    *,
    personal_only: bool = False,
    personal_owner_id: int | None = None,
) -> int:
    """Re-enqueue documents whose last attempt failed.

    A failed row is terminal: startup only revives ``processing`` rows, so a
    document that failed while no usable embedding model was configured stayed
    failed forever, even after the user downloaded and enabled a model.  Model
    activation calls this so those documents heal without a manual rebuild.
    """
    repo = services.knowledge_repo
    bases = repo.list_all()
    if personal_only:
        bases = [
            base
            for base in bases
            if not base.shared
            and (personal_owner_id is None or int(base.owner_user_id) == int(personal_owner_id))
        ]
    enqueued = 0
    for base in bases:
        for document in repo.list_documents(base.id):
            if document.is_dir or document.status != "failed":
                continue
            repo.update_document(document.id, status="pending", error_message="", chunk_count=0)
            refreshed = repo.get_document(document.id)
            if refreshed is not None:
                enqueue_index_document(services, refreshed.kb_id, refreshed.id)
                enqueued += 1
    return enqueued
