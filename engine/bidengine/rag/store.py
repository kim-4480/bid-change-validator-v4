"""Version-scoped document RAG index backed by FAISS.

The index is intentionally a document-retrieval layer, not a qualification
decision engine. Qualification truth remains in the deterministic product
judgment service. This module only retrieves source text for grounded answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from bidengine.providers.embeddings import OpenAIEmbedder
from bidengine.document.chunking import chunk_source_blocks


INDEX_SCHEMA_VERSION = "document-rag-manifest-v0.1"
DEFAULT_INDEX_VERSION = "document-rag-chunk-v0.1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_MAX_CHARS = 1800


class EmbeddingsLike(Protocol):
    """Small subset shared by production embeddings and deterministic test doubles."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class ExistingOpenAIEmbeddings:
    """Adapt the project's OpenAI 3.x embedding provider to the RAG store contract.

    We intentionally reuse ``app.ai.providers.embeddings.OpenAIEmbedder`` instead
    of adding ``langchain-openai`` because the project already pins OpenAI SDK 3.x.
    LangChain is used by the grounded prompt/orchestration layer while the shared
    provider remains the single OpenAI embedding boundary.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or DEFAULT_EMBEDDING_MODEL
        self._embedder = OpenAIEmbedder(api_key=api_key, model=self.model)

    @property
    def available(self) -> bool:
        return self._embedder.available

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder([text])[0]


def create_openai_embeddings(
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> ExistingOpenAIEmbeddings:
    return ExistingOpenAIEmbeddings(api_key=api_key, model=model)


class DocumentChunkMetadata(BaseModel):
    index_version: str = DEFAULT_INDEX_VERSION
    notice_id: str
    notice_version_id: str
    version_number: int
    document_id: str
    document_name: str
    document_role: str | None = None
    chunk_id: str
    clause_label: str | None = None
    block_start: int | None = None
    block_end: int | None = None
    page: int | None = None
    section_index: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    source_line_start: int | None = None
    source_line_end: int | None = None
    source_locations: list[str] = Field(default_factory=list)
    source_sha256: str | None = None
    extracted_text_sha256: str | None = None


class DocumentChunkRecord(BaseModel):
    text: str
    metadata: DocumentChunkMetadata


class DocumentChunkHit(BaseModel):
    text: str
    score: float
    metadata: DocumentChunkMetadata


def _int_values(source_blocks: list[dict[str, Any]], key: str) -> list[int]:
    values: list[int] = []
    for block in source_blocks:
        value = block.get(key)
        if isinstance(value, int):
            values.append(value)
    return values


def _single_value(values: list[int]) -> int | None:
    unique = sorted(set(values))
    return unique[0] if len(unique) == 1 else None


def _range(values: list[int]) -> tuple[int | None, int | None]:
    return (min(values), max(values)) if values else (None, None)


def build_notice_version_records(
    version: Any,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    index_version: str = DEFAULT_INDEX_VERSION,
) -> list[DocumentChunkRecord]:
    """Convert one notice version's extracted documents into stable index records.

    ``version`` is typed structurally so this conversion stays easy to unit-test.
    Production callers pass a BidNoticeVersion with its documents loaded.
    """

    records: list[DocumentChunkRecord] = []
    documents = sorted(
        list(getattr(version, "documents", []) or []),
        key=lambda item: (
            getattr(item, "document_order", 0),
            str(getattr(item, "id", "")),
        ),
    )

    for document in documents:
        if getattr(document, "extraction_status", None) != "EXTRACTED":
            continue
        extracted_blocks = list(getattr(document, "extracted_blocks", None) or [])
        if not extracted_blocks:
            continue

        chunks = chunk_source_blocks(extracted_blocks, max_chars=max_chars)
        for chunk in chunks:
            source_blocks = list(chunk.get("source_blocks") or [])
            block_start, block_end = _range(_int_values(source_blocks, "block_index"))
            paragraph_start, paragraph_end = _range(
                _int_values(source_blocks, "paragraph_index")
            )
            source_line_start, _ = _range(
                _int_values(source_blocks, "source_line_start")
            )
            _, source_line_end = _range(_int_values(source_blocks, "source_line_end"))

            source_locations = [
                str(block["location"])
                for block in source_blocks
                if block.get("location")
            ]

            local_chunk_id = str(chunk["chunk_id"])
            records.append(
                DocumentChunkRecord(
                    text=str(chunk["text"]),
                    metadata=DocumentChunkMetadata(
                        index_version=index_version,
                        notice_id=str(version.notice_id),
                        notice_version_id=str(version.id),
                        version_number=int(version.version_number),
                        document_id=str(document.id),
                        document_name=str(document.name),
                        document_role=getattr(document, "source_field", None),
                        chunk_id=f"{document.id}:{local_chunk_id}",
                        clause_label=chunk.get("clause_label"),
                        block_start=block_start,
                        block_end=block_end,
                        page=_single_value(_int_values(source_blocks, "page")),
                        section_index=_single_value(
                            _int_values(source_blocks, "section_index")
                        ),
                        paragraph_start=paragraph_start,
                        paragraph_end=paragraph_end,
                        source_line_start=source_line_start,
                        source_line_end=source_line_end,
                        source_locations=source_locations,
                        source_sha256=getattr(document, "file_sha256", None),
                        extracted_text_sha256=getattr(
                            document, "extracted_text_sha256", None
                        ),
                    ),
                )
            )

    return records


class VersionFaissIndex:
    """FAISS cosine-similarity index bound to exactly one notice version."""

    def __init__(
        self,
        *,
        index: Any,
        records: list[DocumentChunkRecord],
        embeddings: EmbeddingsLike,
        embedding_model: str,
    ) -> None:
        self._index = index
        self.records = records
        self.embeddings = embeddings
        self.embedding_model = embedding_model
        version_ids = {item.metadata.notice_version_id for item in records}
        if len(version_ids) != 1:
            raise ValueError(
                "a VersionFaissIndex must contain exactly one notice_version_id"
            )
        self.notice_version_id = next(iter(version_ids))

    @staticmethod
    def _dependencies() -> tuple[Any, Any]:
        try:
            import faiss
            import numpy as np
        except ImportError as error:  # pragma: no cover - runtime dependency guard
            raise RuntimeError(
                "Document RAG requires `faiss-cpu` and `numpy`"
            ) from error
        return faiss, np

    @staticmethod
    def _normalized_matrix(vectors: list[list[float]], np: Any) -> Any:
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
            raise ValueError("embedding provider returned an invalid document matrix")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if bool((norms == 0).any()):
            raise ValueError("embedding provider returned a zero-length vector")
        return matrix / norms

    @staticmethod
    def _normalized_query(vector: list[float], np: Any) -> Any:
        query = np.asarray([vector], dtype="float32")
        if query.ndim != 2 or query.shape[1] == 0:
            raise ValueError("embedding provider returned an invalid query vector")
        norm = np.linalg.norm(query, axis=1, keepdims=True)
        if bool((norm == 0).any()):
            raise ValueError("embedding provider returned a zero-length query vector")
        return query / norm

    @classmethod
    def build(
        cls,
        records: list[DocumentChunkRecord],
        *,
        embeddings: EmbeddingsLike,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> "VersionFaissIndex":
        if not records:
            raise ValueError("at least one document chunk is required")
        version_ids = {item.metadata.notice_version_id for item in records}
        if len(version_ids) != 1:
            raise ValueError(
                "records from multiple notice versions cannot share one index"
            )

        faiss, np = cls._dependencies()
        vectors = embeddings.embed_documents([item.text for item in records])
        if len(vectors) != len(records):
            raise ValueError("embedding count does not match document chunk count")
        matrix = cls._normalized_matrix(vectors, np)
        index = faiss.IndexFlatIP(int(matrix.shape[1]))
        index.add(matrix)
        return cls(
            index=index,
            records=records,
            embeddings=embeddings,
            embedding_model=embedding_model,
        )

    def save(self, directory: str | Path) -> None:
        faiss, _ = self._dependencies()
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(target / "index.faiss"))
        manifest = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "notice_version_id": self.notice_version_id,
            "embedding_model": self.embedding_model,
            "index_version": self.records[0].metadata.index_version,
            "records": [item.model_dump(mode="json") for item in self.records],
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(
        cls,
        directory: str | Path,
        *,
        embeddings: EmbeddingsLike,
        expected_notice_version_id: str | None = None,
    ) -> "VersionFaissIndex":
        faiss, _ = cls._dependencies()
        target = Path(directory)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != INDEX_SCHEMA_VERSION:
            raise ValueError("unsupported document RAG manifest schema")

        records = [
            DocumentChunkRecord.model_validate(item)
            for item in list(manifest.get("records") or [])
        ]
        if not records:
            raise ValueError("document RAG manifest contains no records")

        notice_version_id = str(manifest.get("notice_version_id") or "")
        if expected_notice_version_id and notice_version_id != expected_notice_version_id:
            raise ValueError("loaded index does not match the expected notice version")
        if {item.metadata.notice_version_id for item in records} != {notice_version_id}:
            raise ValueError(
                "manifest records contain mixed or mismatched notice versions"
            )

        index = faiss.read_index(str(target / "index.faiss"))
        if int(index.ntotal) != len(records):
            raise ValueError("FAISS index size does not match manifest records")

        return cls(
            index=index,
            records=records,
            embeddings=embeddings,
            embedding_model=str(
                manifest.get("embedding_model") or DEFAULT_EMBEDDING_MODEL
            ),
        )

    def search(self, query: str, *, k: int = 4) -> list[DocumentChunkHit]:
        if not query.strip():
            raise ValueError("query must not be blank")
        if k < 1:
            raise ValueError("k must be at least 1")

        _, np = self._dependencies()
        query_vector = self._normalized_query(
            self.embeddings.embed_query(query),
            np,
        )
        top_k = min(k, len(self.records))
        scores, indices = self._index.search(query_vector, top_k)

        hits: list[DocumentChunkHit] = []
        for score, record_index in zip(scores[0], indices[0]):
            index_value = int(record_index)
            if index_value < 0:
                continue
            record = self.records[index_value]
            hits.append(
                DocumentChunkHit(
                    text=record.text,
                    score=float(score),
                    metadata=record.metadata,
                )
            )
        return hits


def version_index_directory(root: str | Path, notice_version_id: str) -> Path:
    """Resolve a version namespace without allowing path traversal."""

    normalized = notice_version_id.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError("notice_version_id is not a safe path segment")
    return Path(root) / normalized
