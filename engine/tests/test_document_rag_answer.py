from types import SimpleNamespace

import pytest

from bidengine.rag.answer import build_grounded_prompt, generate_grounded_answer
from bidengine.rag.store import DocumentChunkHit, DocumentChunkMetadata


def _hit() -> DocumentChunkHit:
    return DocumentChunkHit(
        text="최근 3년간 1억원 이상의 수행실적을 보유한 업체",
        score=0.95,
        metadata=DocumentChunkMetadata(
            notice_id="notice-1",
            notice_version_id="version-1",
            version_number=1,
            document_id="doc-1",
            document_name="공고문.pdf",
            document_role="standard_notice",
            chunk_id="doc-1:CHUNK-0000",
            clause_label="제3조",
            page=3,
            source_locations=["p.3"],
        ),
    )


def test_build_grounded_prompt_contains_source_and_safety_instruction():
    messages = build_grounded_prompt("실적 조건이 뭐야?", [_hit()])

    assert messages[0]["role"] == "system"
    assert "참가 가능/불가를 독자적으로 판정하지 마세요" in messages[0]["content"]
    assert "실제로 사용한 SOURCE만" in messages[0]["content"]
    assert "임의로 누락값을 추정·보정·복원하지 마세요" in messages[0]["content"]
    assert "빠진 숫자나 문자를 채워 달라고 요청해도" in messages[0]["content"]
    assert "[S1] [S2]" in messages[0]["content"]
    assert "제공되지 않은 Source ID" in messages[0]["content"]
    assert "억지로 인용을 생성하지 마세요" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "[S1]" in messages[1]["content"]
    assert "최근 3년간 1억원" in messages[1]["content"]


def test_generate_grounded_answer_returns_stable_citation_metadata():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="실적 조건은 1억원 이상입니다. [S1]"))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: response)
        )
    )

    result = generate_grounded_answer(
        "실적 조건이 뭐야?",
        [_hit()],
        client=client,
        model="fake-model",
    )

    assert result.answer.endswith("[S1]")
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.ref == "S1"
    assert citation.document_id == "doc-1"
    assert citation.notice_version_id == "version-1"
    assert citation.page == 3
    assert citation.clause_label == "제3조"
    assert result.sources == result.citations


def _client(content):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def _two_hits():
    first, second = _hit(), _hit()
    second.text = "공동수급은 허용하지 않습니다."
    second.metadata.document_id = "doc-2"
    second.metadata.document_name = "첨부문서.pdf"
    second.metadata.chunk_id = "doc-2:CHUNK-0001"
    second.metadata.clause_label = "2"
    second.metadata.page = None
    second.metadata.source_locations = ["p.2", "p.3"]
    return [first, second]


@pytest.mark.parametrize("answer,refs", [
    ("실적 조건을 확인했습니다. [S1]", ["S1"]),
    ("공동수급 [S2], 실적 [S1], 다시 공동수급 [S2]", ["S2", "S1"]),
    ("검색된 근거만으로 확인할 수 없습니다.", []),
])
def test_sources_keep_rank_while_citations_follow_first_appearance(answer, refs):
    hits = _two_hits()
    client, calls = _client(answer)
    result = generate_grounded_answer("근거가 어디야?", hits, client=client)

    assert len(calls) == 1
    assert result.answer == answer
    assert [source.ref for source in result.sources] == ["S1", "S2"]
    assert [citation.ref for citation in result.citations] == refs
    for source, hit in zip(result.sources, hits):
        assert source.document_id == hit.metadata.document_id
        assert source.document_name == hit.metadata.document_name
        assert source.notice_version_id == hit.metadata.notice_version_id
        assert source.chunk_id == hit.metadata.chunk_id
        assert source.clause_label == hit.metadata.clause_label
        assert source.page == hit.metadata.page
        assert source.source_locations == hit.metadata.source_locations
        assert source.quote == hit.text
    by_ref = {source.ref: source for source in result.sources}
    assert result.citations == [by_ref[ref] for ref in refs]
    assert [source["ref"] for source in result.model_dump()["sources"]] == ["S1", "S2"]


@pytest.mark.parametrize("ref", ["S3", "S0", "S01", "S999"])
def test_unknown_citation_fails_closed_without_renumbering(ref):
    client, calls = _client(f"근거를 확인했습니다. [S1] [{ref}]")
    with pytest.raises(ValueError, match="unknown source refs"):
        generate_grounded_answer("근거가 어디야?", _two_hits(), client=client)
    assert len(calls) == 1


def test_prompt_preserves_clause_and_multi_page_locations():
    hit = _two_hits()[1]
    prompt = build_grounded_prompt("근거가 어디야?", [hit])[1]["content"]
    assert "[S1]" in prompt
    assert "clause=2; location=p.2, p.3" in prompt


def test_prompt_uses_only_existing_page_or_section_locations():
    hit = _hit()
    hit.metadata.source_locations = []
    assert "location=p.3" in build_grounded_prompt("근거", [hit])[1]["content"]
    hit.metadata.page = None
    hit.metadata.source_locations = ["section 2 · paragraph 4"]
    prompt = build_grounded_prompt("근거", [hit])[1]["content"]
    assert "clause=제3조; location=section 2 · paragraph 4" in prompt
    assert "p.3" not in prompt
    hit.metadata.source_locations = []
    assert "location=위치 정보 없음" in build_grounded_prompt("근거", [hit])[1]["content"]


def test_mixed_versions_are_rejected_before_client_call():
    hits = _two_hits()
    hits[1].metadata.notice_version_id = "version-2"
    client, calls = _client("근거입니다. [S1]")
    with pytest.raises(ValueError, match="mix notice versions"):
        generate_grounded_answer("근거가 어디야?", hits, client=client)
    assert calls == []
    with pytest.raises(ValueError, match="mix notice versions"):
        build_grounded_prompt("근거가 어디야?", hits)


def test_empty_sources_allow_abstention_but_reject_any_citation():
    client, _ = _client("검색된 근거가 없어 확인할 수 없습니다.")
    result = generate_grounded_answer("근거가 어디야?", [], client=client)
    assert result.sources == result.citations == []
    client, _ = _client("근거입니다. [S1]")
    with pytest.raises(ValueError, match="unknown source refs"):
        generate_grounded_answer("근거가 어디야?", [], client=client)
