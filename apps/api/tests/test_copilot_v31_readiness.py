from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from bidengine.rag.readiness import snapshot_sources, inspect_index, publish_index, read_passages


class Embeddings:
    def __init__(self): self.document_calls = 0
    def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, float(len(t) % 7 + 1)] for t in texts]
    def embed_query(self, text): return [1.0, 1.0]


def version():
    vid = UUID('00000000-0000-4000-8000-000000000010')
    return SimpleNamespace(id=vid, notice_id=UUID('00000000-0000-4000-8000-000000000011'), version_number=1,
        documents=[SimpleNamespace(id=UUID('00000000-0000-4000-8000-000000000012'), notice_version_id=vid,
            name='fixture', document_order=0, extraction_status='EXTRACTED', text_extractor='fixture-v1',
            file_sha256='a' * 64, extracted_text_sha256='b' * 64,
            extracted_blocks=[{'text': '참가자격: 2년 내 2곳, 평균 800식, 1년 운영. 병원은 제외.', 'block_index': 0, 'section_index': 1, 'location': 'section 1'}])])


def test_missing_legacy_and_current_direct_read_never_build(tmp_path):
    v = version()
    s = snapshot_sources(v, dimensions=2)
    embed = Embeddings()
    ready = inspect_index(s, tmp_path, embed)
    assert ready.index_status == 'MISSING' and s.source_status == 'AVAILABLE'
    passages, details = read_passages(ready, '전체 참가자격', broad=True)
    assert passages and '800식' in passages[0].text and '병원' in passages[0].text
    assert embed.document_calls == 0 and not list(tmp_path.iterdir())
    directory = tmp_path / str(v.id)
    directory.mkdir()
    (directory / 'manifest.json').write_text('{}')
    assert inspect_index(s, tmp_path, embed).index_status == 'UNVERIFIED'


@pytest.mark.parametrize('change', ['source', 'extracted', 'blocks', 'add', 'remove', 'model', 'dimensions', 'extractor'])
def test_same_version_changes_invalidate_fingerprint(tmp_path, change):
    v, embed = version(), Embeddings()
    old = snapshot_sources(v, dimensions=2)
    generation = publish_index(old, tmp_path, embed, expected_fingerprint=old.fingerprint, max_embedding_tokens=10000)
    assert inspect_index(old, tmp_path, embed).index_status == 'READY'
    model, dimensions = 'text-embedding-3-small', 2
    if change == 'source': v.documents[0].file_sha256 = 'c' * 64
    if change == 'extracted': v.documents[0].extracted_text_sha256 = 'c' * 64
    if change == 'blocks': v.documents[0].extracted_blocks[0]['text'] = '다른 조건'
    if change == 'add':
        doc = deepcopy(v.documents[0]); doc.id = UUID('00000000-0000-4000-8000-000000000013'); v.documents.append(doc)
    if change == 'remove': v.documents = []
    if change == 'model': model = 'other'
    if change == 'dimensions': dimensions = 3
    if change == 'extractor': v.documents[0].text_extractor = 'v2'
    current = snapshot_sources(v, model=model, dimensions=dimensions)
    assert current.fingerprint != old.fingerprint
    assert inspect_index(current, tmp_path, embed).index_status == 'STALE'
    assert (tmp_path / str(v.id) / 'generations' / generation / 'index.faiss').is_file()


def test_partial_source_can_have_ready_index(tmp_path):
    v = version()
    other = deepcopy(v.documents[0]); other.id = UUID('00000000-0000-4000-8000-000000000014'); other.extraction_status = 'FAILED'
    v.documents.append(other)
    source = snapshot_sources(v, dimensions=2)
    assert source.source_status == 'PARTIAL'
    embed = Embeddings()
    publish_index(source, tmp_path, embed, expected_fingerprint=source.fingerprint, max_embedding_tokens=10000)
    assert inspect_index(source, tmp_path, embed).index_status == 'READY'


def test_missing_hash_never_counts_as_verified_source(tmp_path):
    v = version(); v.documents[0].file_sha256 = None
    source = snapshot_sources(v, dimensions=2)
    assert source.source_status == 'UNVERIFIED' and not source.records


def test_build_failure_lock_dedup_and_atomic_generation(tmp_path):
    v, embed = version(), Embeddings()
    source = snapshot_sources(v, dimensions=2)
    generation = publish_index(source, tmp_path, embed, expected_fingerprint=source.fingerprint, max_embedding_tokens=10000)
    pinned = inspect_index(source, tmp_path, embed)
    assert publish_index(source, tmp_path, embed, expected_fingerprint=source.fingerprint, max_embedding_tokens=10000) == generation
    assert embed.document_calls == 1
    pointer = tmp_path / str(v.id) / 'active.json'
    original = pointer.read_bytes()
    lock = pointer.parent / 'build.lock'; lock.write_text('another process')
    with pytest.raises(FileExistsError):
        publish_index(source, tmp_path, embed, expected_fingerprint=source.fingerprint, max_embedding_tokens=10000)
    lock.unlink()
    v.documents[0].extracted_blocks[0]['text'] += ' 새 조건'
    changed = snapshot_sources(v, dimensions=2)
    bad = Embeddings(); bad.embed_documents = lambda _: (_ for _ in ()).throw(RuntimeError('injected failure'))
    with pytest.raises(RuntimeError):
        publish_index(changed, tmp_path, bad, expected_fingerprint=changed.fingerprint, max_embedding_tokens=10000)
    assert pointer.read_bytes() == original and pinned.index.records == source.records
    new_generation = publish_index(changed, tmp_path, embed, expected_fingerprint=changed.fingerprint, max_embedding_tokens=10000)
    assert new_generation != generation
    assert pinned.index.records == source.records
    assert inspect_index(changed, tmp_path, embed).index_status == 'READY'
    path = pointer.parent / 'generations' / new_generation / 'index.faiss'
    path.write_bytes(b'corrupt')
    assert inspect_index(changed, tmp_path, embed).index_status == 'CORRUPT'


def test_point_search_expands_current_parent_section_and_bounded_exceptions(tmp_path):
    from apps.api.tests.test_document_rag_store import _record
    from bidengine.rag.readiness import Readiness
    source = snapshot_sources(version(), dimensions=2)
    source.records = [_record(source.version_id, str(i), text) for i, text in enumerate([
        '급식 실적 800식', '같은 부모 섹션 본문', '같은 섹션 두 번째 단락', '같은 섹션 세 번째 단락',
        '별도 기관 예외: 병원 실적은 제외', '무관한 운송 조건'])]
    for i, record in enumerate(source.records):
        record.metadata.section_index = 1 if i < 4 else i
    result, details = read_passages(Readiness(source, 'MISSING'), '800식 실적', query_limit=1)
    assert '같은 섹션 세 번째 단락' in [r.text for r in result]
    assert any('병원' in r.text for r in result)
    assert details['supplements'] == 1


def test_building_without_ready_generation_reads_current_source(tmp_path):
    source = snapshot_sources(version(), dimensions=2)
    directory = tmp_path / source.version_id
    directory.mkdir()
    (directory / 'build.lock').write_text('in progress')
    ready = inspect_index(source, tmp_path, Embeddings())
    assert ready.index_status == 'BUILDING'
    result, _ = read_passages(ready, '전체', broad=True)
    assert result == source.records
