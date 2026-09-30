"""Shared document retrieval primitives for grounded product experiences."""

from bidengine.rag.answer import (
    GroundedCitation,
    GroundedDocumentAnswer,
    build_grounded_prompt,
    generate_grounded_answer,
)
from .service import (
    DocumentRagError,
    build_version_index,
    load_notice_version_for_rag,
    load_or_build_version_index,
    search_document_chunks,
)
from bidengine.rag.store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_VERSION,
    DocumentChunkHit,
    DocumentChunkMetadata,
    DocumentChunkRecord,
    ExistingOpenAIEmbeddings,
    VersionFaissIndex,
    build_notice_version_records,
    create_openai_embeddings,
    version_index_directory,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_INDEX_VERSION",
    "DocumentChunkHit",
    "DocumentChunkMetadata",
    "DocumentChunkRecord",
    "DocumentRagError",
    "ExistingOpenAIEmbeddings",
    "GroundedCitation",
    "GroundedDocumentAnswer",
    "VersionFaissIndex",
    "build_grounded_prompt",
    "build_notice_version_records",
    "build_version_index",
    "create_openai_embeddings",
    "generate_grounded_answer",
    "load_notice_version_for_rag",
    "load_or_build_version_index",
    "search_document_chunks",
    "version_index_directory",
]
