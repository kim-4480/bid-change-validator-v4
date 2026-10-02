"""Read-only source snapshots and immutable index generations for Copilot 3.1."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from bidengine.rag.store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_VERSION,
    DEFAULT_MAX_CHARS,
    VersionFaissIndex,
    build_notice_version_records,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class SourceSnapshot:
    version_id: str
    fingerprint: str
    source_status: str
    records: list
    identity: dict
    limitations: list[str] = field(default_factory=list)
    verification: str = 'DB extraction metadata and current block digest; original bytes not rehashed'


def snapshot_sources(version, *, model=DEFAULT_EMBEDDING_MODEL, dimensions=1536):
    documents, accepted, limitations = [], [], []
    for doc in sorted(version.documents, key=lambda d: str(d.id)):
        blocks = getattr(doc, 'extracted_blocks', None) or []
        source_hash = getattr(doc, 'file_sha256', None)
        extracted_hash = getattr(doc, 'extracted_text_sha256', None)
        correct_version = str(getattr(doc, 'notice_version_id', version.id)) == str(version.id)
        valid = correct_version and getattr(doc, 'extraction_status', None) == 'EXTRACTED' and bool(blocks)
        verified = valid and all(isinstance(h, str) and re.fullmatch(r'[a-fA-F0-9]{64}', h) for h in (source_hash, extracted_hash))
        documents.append({'id': str(doc.id), 'version': str(getattr(doc, 'notice_version_id', version.id)),
                          'status': getattr(doc, 'extraction_status', None), 'source_sha256': source_hash,
                          'extracted_sha256': extracted_hash, 'blocks_sha256': digest(blocks),
                          'extractor': getattr(doc, 'text_extractor', None)})
        if verified:
            accepted.append(doc)
        else:
            limitations.append(f'문서 {doc.name}: 현재 추출 출처 또는 hash를 확인하지 못했습니다.')
    from types import SimpleNamespace
    filtered = SimpleNamespace(id=version.id, notice_id=version.notice_id, version_number=version.version_number, documents=accepted)
    records = build_notice_version_records(filtered)
    identity = {'notice_id': str(version.notice_id), 'version_id': str(version.id), 'documents': documents,
                'chunk_version': DEFAULT_INDEX_VERSION, 'max_chars': DEFAULT_MAX_CHARS,
                'provider': 'openai', 'model': model, 'dimensions': dimensions, 'normalization': 'l2', 'format': 'faiss-flat-ip-v1'}
    status = 'AVAILABLE' if documents and len(accepted) == len(documents) and records else 'PARTIAL' if records else 'UNVERIFIED' if documents else 'UNAVAILABLE'
    return SourceSnapshot(str(version.id), digest(identity), status, records, identity, limitations)


@dataclass
class Readiness:
    source: SourceSnapshot
    index_status: str
    generation: str | None = None
    index: VersionFaissIndex | None = None


def inspect_index(snapshot, root, embeddings):
    directory = Path(root) / snapshot.version_id
    pointer = directory / 'active.json'
    if not pointer.exists():
        status = 'BUILDING' if (directory / 'build.lock').exists() else 'UNVERIFIED' if (directory / 'manifest.json').exists() else 'MISSING'
        return Readiness(snapshot, status)
    try:
        active = json.loads(pointer.read_text(encoding='utf-8'))
        generation = active['generation']
        if not re.fullmatch(r'[a-f0-9]{32}', generation):
            raise ValueError('invalid generation')
        path = directory / 'generations' / generation
        stamp = json.loads((path / 'identity.json').read_text(encoding='utf-8'))
        if stamp['fingerprint'] != snapshot.fingerprint:
            return Readiness(snapshot, 'STALE', generation)
        if snapshot.source_status not in {'AVAILABLE', 'PARTIAL'}:
            return Readiness(snapshot, 'UNVERIFIED', generation)
        if any(file_digest(path / name) != stamp['artifacts'][name] for name in ('manifest.json', 'index.faiss')):
            raise ValueError('artifact mismatch')
        index = VersionFaissIndex.load(path, embeddings=embeddings, expected_notice_version_id=snapshot.version_id)
        if digest([r.model_dump(mode='json') for r in index.records]) != digest([r.model_dump(mode='json') for r in snapshot.records]):
            raise ValueError('record mismatch')
        if index.embedding_model != snapshot.identity['model'] or int(index._index.d) != snapshot.identity['dimensions']:
            return Readiness(snapshot, 'STALE', generation)
        return Readiness(snapshot, 'READY', generation, index)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        return Readiness(snapshot, 'CORRUPT')


def build_plan(snapshot, root):
    return {'source': snapshot.source_status, 'version_id': snapshot.version_id, 'fingerprint': snapshot.fingerprint,
            'documents': len(snapshot.identity['documents']), 'chunks': len(snapshot.records),
            'embedding_token_upper_bound': sum(len(r.text.encode('utf-8')) for r in snapshot.records),
            'output': str(Path(root) / snapshot.version_id / 'generations')}


def publish_index(snapshot, root, embeddings, *, expected_fingerprint, max_embedding_tokens):
    """Explicit operation only. O_EXCL lock spans processes; a crash leaves a visible lock."""
    plan = build_plan(snapshot, root)
    if snapshot.fingerprint != expected_fingerprint or not snapshot.records:
        raise ValueError('SOURCE_OR_FINGERPRINT_UNVERIFIED')
    if plan['embedding_token_upper_bound'] > max_embedding_tokens:
        raise ValueError('EMBEDDING_BUDGET')
    directory = Path(root) / snapshot.version_id
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'build.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        ready = inspect_index(snapshot, root, embeddings)
        if ready.index_status == 'READY':
            return ready.generation
        generation = uuid4().hex
        path = directory / 'generations' / generation
        index = VersionFaissIndex.build(snapshot.records, embeddings=embeddings, embedding_model=snapshot.identity['model'])
        if int(index._index.d) != snapshot.identity['dimensions']:
            raise ValueError('EMBEDDING_DIMENSION_MISMATCH')
        index.save(path)
        VersionFaissIndex.load(path, embeddings=embeddings, expected_notice_version_id=snapshot.version_id)
        stamp = {'fingerprint': snapshot.fingerprint, 'identity': snapshot.identity,
                 'artifacts': {n: file_digest(path / n) for n in ('manifest.json', 'index.faiss')}}
        (path / 'identity.json').write_text(json.dumps(stamp, ensure_ascii=False), encoding='utf-8')
        temp = directory / f'active-{generation}.json'
        temp.write_text(json.dumps({'generation': generation}), encoding='utf-8')
        os.replace(temp, directory / 'active.json')
        return generation
    finally:
        lock.unlink()


def read_passages(readiness, question, *, broad=False, query_limit=2):
    """Current verified source records only; never builds or embeds documents."""
    records = readiness.source.records
    if readiness.index is not None and not broad:
        from bidengine.rag.retrieval import retrieve
        hits = retrieve(readiness.index, question, method='hybrid', k=4, fetch_k=12)
        hit_ids = {h.metadata.chunk_id for h in hits}
        positive = [i for i, r in enumerate(records) if r.metadata.chunk_id in hit_ids]
        strategy = 'hybrid_with_current_sections'
    elif broad:
        # Read all verified current sections. Input budget handling occurs before model generation;
        # no three-point truncation or false assertion of complete source coverage.
        return records, {'strategy': 'current_sections', 'supplements': 0}
    else:
        tokens = set(re.findall(r'[가-힣A-Za-z0-9]{2,}', question))
        ranked = sorted(enumerate(records), key=lambda pair: sum(t in pair[1].text for t in tokens), reverse=True)
        positive = [i for i, r in ranked if any(t in r.text for t in tokens)][:4]
        strategy = 'current_sections_lexical'
    # Parent sections are drawn from the pinned current source snapshot, including
    # chunks beyond top-k. Adjacent passages cover formats lacking section metadata.
    selected = set(positive)
    for i in positive:
        section = records[i].metadata.section_index
        if section is not None:
            selected.update(j for j, r in enumerate(records)
                            if r.metadata.document_id == records[i].metadata.document_id and r.metadata.section_index == section)
        for j in (i - 1, i + 1):
            if 0 <= j < len(records) and records[j].metadata.document_id == records[i].metadata.document_id:
                selected.add(j)
    # At most two local supplemental scans for topical restrictions/footnotes.
    # These are retrieval aids, not proof of semantic coverage or extra model calls.
    supplements = 0
    groups = [('실적', '급식', '병원', '기관', '800'), ('공동', '하도급', '컨소시엄')]
    for group in groups:
        if supplements >= min(2, max(0, query_limit)):
            break
        if any(t in question for t in group):
            supplements += 1
            selected.update(i for i, r in enumerate(records) if any(t in r.text for t in group)
                            and any(t in r.text for t in ('제외', '예외', '불가', '금지', '한함', '허용', '단,')))
    return [records[i] for i in sorted(selected)], {'strategy': strategy, 'supplements': supplements,
                                                  'returned_chunks': len(selected), 'source_chunks': len(records)}
