"""Service boundary for version-scoped document retrieval."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import BidNoticeVersion
from bidengine.rag.store import (
    DEFAULT_EMBEDDING_MODEL,
    DocumentChunkHit,
    EmbeddingsLike,
    VersionFaissIndex,
    build_notice_version_records,
    version_index_directory,
)


class DocumentRagError(ValueError):
    pass


def load_notice_version_for_rag(db: Session, notice_version_id: UUID) -> BidNoticeVersion:
    version = db.scalar(
        select(BidNoticeVersion)
        .where(BidNoticeVersion.id == notice_version_id)
        .options(selectinload(BidNoticeVersion.documents))
    )
    if version is None:
        raise DocumentRagError("NOTICE_VERSION_NOT_FOUND")
    return version


def build_version_index(
    db: Session,
    *,
    notice_version_id: UUID,
    index_root: str | Path,
    embeddings: EmbeddingsLike,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> VersionFaissIndex:
    version = load_notice_version_for_rag(db, notice_version_id)
    records = build_notice_version_records(version)
    if not records:
        raise DocumentRagError("NO_EXTRACTED_DOCUMENTS")

    index = VersionFaissIndex.build(
        records,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )
    index.save(version_index_directory(index_root, str(notice_version_id)))
    return index


def load_or_build_version_index(
    db: Session,
    *,
    notice_version_id: UUID,
    index_root: str | Path,
    embeddings: EmbeddingsLike,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> VersionFaissIndex:
    directory = version_index_directory(index_root, str(notice_version_id))
    manifest_path = directory / "manifest.json"
    index_path = directory / "index.faiss"

    if manifest_path.is_file() and index_path.is_file():
        try:
            return VersionFaissIndex.load(
                directory,
                embeddings=embeddings,
                expected_notice_version_id=str(notice_version_id),
            )
        except (OSError, ValueError):
            pass

    return build_version_index(
        db,
        notice_version_id=notice_version_id,
        index_root=index_root,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )


def search_document_chunks(
    db: Session,
    *,
    notice_version_id: UUID,
    query: str,
    index_root: str | Path,
    embeddings: EmbeddingsLike,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    k: int = 4,
) -> list[DocumentChunkHit]:
    index = load_or_build_version_index(
        db,
        notice_version_id=notice_version_id,
        index_root=index_root,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )
    return index.search(query, k=k)
