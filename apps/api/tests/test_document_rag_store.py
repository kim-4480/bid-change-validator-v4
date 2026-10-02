from types import SimpleNamespace
import json

import pytest

from apps.api.app.document_rag import (
    DocumentChunkMetadata,
    DocumentChunkRecord,
    VersionFaissIndex,
    build_notice_version_records,
)
from bidengine.rag.retrieval import navigation_like, retrieve


class FakeEmbeddings:
    @staticmethod
    def _vector(text: str) -> list[float]:
        if "실적" in text:
            return [1.0, 0.0, 0.0]
        if "지역" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _record(version_id: str, chunk_id: str, text: str) -> DocumentChunkRecord:
    return DocumentChunkRecord(
        text=text,
        metadata=DocumentChunkMetadata(
            notice_id="notice-1",
            notice_version_id=version_id,
            version_number=1,
            document_id="doc-1",
            document_name="공고문.pdf",
            document_role="standard_notice",
            chunk_id=chunk_id,
        ),
    )


def test_build_notice_version_records_preserves_document_scope_and_locator():
    document = SimpleNamespace(
        id="doc-1",
        document_order=0,
        name="공고문.pdf",
        source_field="standard_notice",
        extraction_status="EXTRACTED",
        file_sha256="file-sha",
        extracted_text_sha256="text-sha",
        extracted_blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "제3조 참가자격\n최근 3년간 1억원 이상의 수행실적을 보유한 업체",
            }
        ],
    )
    version = SimpleNamespace(
        id="version-1",
        notice_id="notice-1",
        version_number=1,
        documents=[document],
    )

    records = build_notice_version_records(version)

    assert len(records) == 1
    metadata = records[0].metadata
    assert metadata.notice_version_id == "version-1"
    assert metadata.document_id == "doc-1"
    assert metadata.chunk_id == "doc-1:CHUNK-0000"
    assert metadata.page == 3
    assert metadata.block_start == 0
    assert metadata.block_end == 0
    assert metadata.source_locations == ["p.3"]
    assert metadata.source_sha256 == "file-sha"
    assert metadata.extracted_text_sha256 == "text-sha"


def test_version_faiss_index_round_trip_and_search(tmp_path):
    embeddings = FakeEmbeddings()
    records = [
        _record("version-1", "chunk-performance", "수행실적 1억원 이상"),
        _record("version-1", "chunk-region", "서울특별시 소재 업체"),
    ]
    index = VersionFaissIndex.build(records, embeddings=embeddings, embedding_model="fake")
    target = tmp_path / "version-1"

    index.save(target)
    loaded = VersionFaissIndex.load(
        target,
        embeddings=embeddings,
        expected_notice_version_id="version-1",
    )
    hits = loaded.search("실적 조건 알려줘", k=2)

    assert hits[0].metadata.chunk_id == "chunk-performance"
    assert hits[0].score == pytest.approx(1.0)


def test_version_faiss_index_rejects_mixed_versions():
    with pytest.raises(ValueError, match="multiple notice versions"):
        VersionFaissIndex.build(
            [
                _record("version-1", "chunk-1", "실적"),
                _record("version-2", "chunk-2", "지역"),
            ],
            embeddings=FakeEmbeddings(),
        )


def test_loaded_index_rejects_wrong_expected_version(tmp_path):
    embeddings = FakeEmbeddings()
    index = VersionFaissIndex.build(
        [_record("version-1", "chunk-1", "실적")],
        embeddings=embeddings,
        embedding_model="fake",
    )
    target = tmp_path / "version-1"
    index.save(target)

    with pytest.raises(ValueError, match="expected notice version"):
        VersionFaissIndex.load(
            target,
            embeddings=embeddings,
            expected_notice_version_id="version-2",
        )


class RankedEmbeddings:
    """Predictable dense order without matching any query keywords."""

    def __init__(self):
        self.query_calls = 0

    def embed_documents(self, texts):
        return [[float(len(texts) - i), 1.0] for i in range(len(texts))]

    def embed_query(self, text):
        self.query_calls += 1
        return [1.0, 0.0]


def _ranked_index(texts):
    records = [_record("version-1", f"chunk-{i}", text) for i, text in enumerate(texts)]
    for i, record in enumerate(records):
        record.metadata.document_id = f"doc-{i}"
        record.metadata.page = i + 1
        record.metadata.source_locations = [f"p.{i + 1}"]
    return VersionFaissIndex.build(records, embeddings=RankedEmbeddings(), embedding_model="fake")


def test_navigation_detection_preserves_short_substantive_clauses():
    for text in (
        "1. 납품기한: 7일 이내",
        "2. 매출액 5천만원 이상",
        "3. 공동수급 불허",
        "4. 면허 보유 업체",
        "5. 기술자 2인 필수",
        "6. 지역 제한 없음",
        "소재지는 부산이어야 한다.",
        "제1조 등록 요건\n등록증을 제출하여야 한다.",
    ):
        assert not navigation_like(text), text
    assert navigation_like("1. 일반 사항 / 2. 계약 방법\nⅢ. 제출 서류")
    assert navigation_like("4. 상세 요구사항")


def test_dense_post_deduplicates_across_documents_without_losing_different_conditions():
    index = _ranked_index([
        "1. 일반 사항",
        "기술자 2인 이상",
        "기술자\n  2인 이상",
        "기술자 3인 이상",
        "기술자 2인 이하",
        "기술자 2인 미만",
    ])
    before = [record.model_dump() for record in index.records]
    hits = retrieve(index, "인력 기준", fetch_k=6)
    assert [hit.text for hit in hits] == [
        "기술자 2인 이상", "기술자 3인 이상", "기술자 2인 이하", "기술자 2인 미만"
    ]
    assert index.embeddings.query_calls == 1
    for hit in hits:
        original = next(r for r in index.records if r.metadata.chunk_id == hit.metadata.chunk_id)
        assert hit.metadata.model_dump() == original.metadata.model_dump()
    assert [record.model_dump() for record in index.records] == before


def test_navigation_is_deferred_not_deleted_and_unique_results_can_be_short():
    index = _ranked_index(["1. 일반 사항", "공동수급 불허", "공동수급 불허"])
    hits = retrieve(index, "공동수급", k=3, fetch_k=3)
    assert [hit.text for hit in hits] == ["공동수급 불허", "1. 일반 사항"]
    assert index._index.ntotal == 3


def test_hybrid_finds_evidence_outside_dense_window_and_preserves_citation():
    from bidengine.rag.answer import generate_grounded_answer

    index = _ranked_index([
        "1. 개요", "2. 일정", "냉각장치를 설치하여야 한다.", "부품을 안전하게 보관한다."
    ])
    assert "chunk-2" not in [h.metadata.chunk_id for h in index.search("냉각장치", k=2)]
    hits = retrieve(index, "냉각장치", method="hybrid", k=2, fetch_k=2)
    assert hits[0].metadata.chunk_id == "chunk-2"
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="냉각장치 설치가 필요합니다. [S1]")
        )])
    )))
    answer = generate_grounded_answer("냉각장치", hits, client=client)
    assert answer.citations[0].quote == index.records[2].text
    assert answer.citations[0].page == 3
    assert answer.citations[0].source_locations == ["p.3"]
    assert answer.citations[0].notice_version_id == "version-1"


def test_reranker_receives_only_scoped_candidates_and_keeps_original_metadata():
    index = _ranked_index(["냉각장치 설치 의무", "냉각장치 보증 기간", "무관한 배송 안내"])
    captured = []

    def create(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        captured.append(payload)
        assert len(payload["passages"]) == 2
        assert all(set(passage) == {"id", "text"} for passage in payload["passages"])
        order = [passage["id"] for passage in reversed(payload["passages"])]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"ranked_passage_ids": order})
        ))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    hits = retrieve(index, "냉각장치", method="hybrid_rerank", k=2, fetch_k=2, rerank_client=client)
    assert len(captured) == 1
    assert [hit.text for hit in hits] == [
        passage["text"] for passage in reversed(captured[0]["passages"])
    ]
    for hit in hits:
        original = next(r for r in index.records if r.metadata.chunk_id == hit.metadata.chunk_id)
        assert hit.text == original.text
        assert hit.metadata.model_dump() == original.metadata.model_dump()


@pytest.mark.parametrize("content", [
    '{"ranked_passage_ids": ["P01", "other-version:chunk"]}',
    '{"ranked_passage_ids": ["P01", "P01"]}',
    '{"ranked_passage_ids": ["P01"]}',
    '{"ranked_passage_ids": ["P01", {}]}',
    '[]',
    'not JSON',
])
def test_reranker_malformed_ids_fall_back_without_inventing_sources(content):
    index = _ranked_index(["냉각장치 설치 의무", "냉각장치 보증 기간"])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])
    )))
    hits = retrieve(index, "냉각장치", method="hybrid_rerank", k=2, fetch_k=2, rerank_client=client)
    original_ids = {record.metadata.chunk_id for record in index.records}
    result_ids = [hit.metadata.chunk_id for hit in hits]
    assert len(result_ids) == len(set(result_ids)) == 2
    assert set(result_ids) <= original_ids


@pytest.mark.parametrize("method", ["dense_post", "hybrid", "hybrid_rerank"])
def test_retrieval_rejects_mutated_version_before_embedding_or_reranking(method):
    index = _ranked_index(["냉각장치 설치 의무"])
    index.records[0].metadata.notice_version_id = "version-2"
    with pytest.raises(ValueError, match="notice version"):
        retrieve(index, "냉각장치", method=method, rerank_client=object())
    assert index.embeddings.query_calls == 0


def test_retrieval_validates_options_before_embedding():
    index = _ranked_index(["냉각장치 설치 의무"])
    for query, options in [
        (" ", {}), ("질문", {"k": 0}), ("질문", {"k": 4, "fetch_k": 2}),
        ("질문", {"method": "unknown"}), ("질문", {"method": "hybrid_rerank"}),
    ]:
        with pytest.raises(ValueError):
            retrieve(index, query, **options)
    index.records.append(index.records[0])
    with pytest.raises(ValueError, match="unique"):
        retrieve(index, "냉각장치")
    assert index.embeddings.query_calls == 0
