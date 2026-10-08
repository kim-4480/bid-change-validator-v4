"""On-demand RAG freshness verification with zero embedding API calls."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.document_rag import service as rag


def _version():
    document = SimpleNamespace(
        id=uuid4(),
        document_order=0,
        name="source.pdf",
        source_field="stdNtceDocUrl",
        extraction_status="EXTRACTED",
        file_sha256="a" * 64,
        extracted_text_sha256="b" * 64,
        extracted_blocks=[{"block_index": 0, "page": 1, "location": "p.1", "text": "verified source"}],
    )
    return SimpleNamespace(id=uuid4(), notice_id=uuid4(), version_number=2, documents=[document])


def _cache_markers(root, version):
    path = root / str(version.id)
    path.mkdir()
    (path / "manifest.json").write_text("mock")
    (path / "index.faiss").write_bytes(b"mock")


class FakeIndex:
    def __init__(self, records, model="fake-model"):
        self.records = records
        self.embedding_model = model
        self.saved_paths = []
    def save(self, path):
        self.saved_paths.append(path)


def test_identical_version_and_sha_reuses_index_without_embeddings(tmp_path, monkeypatch):
    version = _version()
    records = rag.build_notice_version_records(version)
    _cache_markers(tmp_path, version)
    old_index = FakeIndex(records)
    monkeypatch.setattr(rag, "load_notice_version_for_rag", lambda db, id: version)
    monkeypatch.setattr(rag.VersionFaissIndex, "load", lambda *a, **kw: old_index)
    def unexpected_build(*a, **kw):
        raise AssertionError("unchanged index must not recompute embeddings")
    monkeypatch.setattr(rag.VersionFaissIndex, "build", unexpected_build)
    result = rag.load_or_build_version_index(None, notice_version_id=version.id,
                                             index_root=tmp_path, embeddings=object(),
                                             embedding_model="fake-model")
    assert result is old_index


@pytest.mark.parametrize("change", ["original_hash", "extracted_hash", "chunk_text", "document_status", "embedding_model"])
def test_updated_lineage_never_reuses_stale_cached_chunks(tmp_path, monkeypatch, change):
    version = _version()
    records_before = rag.build_notice_version_records(version)
    _cache_markers(tmp_path, version)
    old_index = FakeIndex(records_before)
    monkeypatch.setattr(rag, "load_notice_version_for_rag", lambda db, id: version)
    monkeypatch.setattr(rag.VersionFaissIndex, "load", lambda *a, **kw: old_index)
    builds = []
    def fake_build(records, *, embeddings, embedding_model):
        builds.append(records)
        return FakeIndex(records, model=embedding_model)
    monkeypatch.setattr(rag.VersionFaissIndex, "build", fake_build)
    doc = version.documents[0]
    model = "fake-model"
    if change == "original_hash":
        doc.file_sha256 = "c" * 64
    elif change == "extracted_hash":
        doc.extracted_text_sha256 = "d" * 64
    elif change == "chunk_text":
        doc.extracted_blocks = [{"block_index": 0, "page": 2, "text": "changed text"}]
    elif change == "document_status":
        doc.extraction_status = "FAILED"
    else:
        model = "different-model"
    if change == "document_status":
        with pytest.raises(rag.DocumentRagError, match="NO_EXTRACTED_DOCUMENTS"):
            rag.load_or_build_version_index(
                None, notice_version_id=version.id, index_root=tmp_path,
                embeddings=object(), embedding_model=model
            )
        assert builds == []
        return
    result = rag.load_or_build_version_index(
        None, notice_version_id=version.id, index_root=tmp_path,
        embeddings=object(), embedding_model=model
    )
    assert len(builds) == 1
    assert result is not old_index
    assert result.saved_paths == [tmp_path / str(version.id)]
    assert result.records == rag.build_notice_version_records(version)


def test_missing_index_builds_once_on_demand(tmp_path, monkeypatch):
    version = _version()
    monkeypatch.setattr(rag, "load_notice_version_for_rag", lambda db, id: version)
    built = []
    def fake_build(records, *, embeddings, embedding_model):
        built.append(records)
        return FakeIndex(records, model=embedding_model)
    monkeypatch.setattr(rag.VersionFaissIndex, "build", fake_build)
    rag.load_or_build_version_index(
        None, notice_version_id=version.id, index_root=tmp_path,
        embeddings=object(), embedding_model="fake-model"
    )
    assert len(built) == 1
