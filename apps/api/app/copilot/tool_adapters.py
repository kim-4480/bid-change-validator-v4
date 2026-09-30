"""Adapt existing domain reads; no alternate judgment engine and no writes."""
import json
import os
import re

from bidengine.rag.readiness import digest, inspect_index, read_passages, snapshot_sources
from ..document_rag.service import load_notice_version_for_rag
from bidengine.rag.store import create_openai_embeddings
from ..qualification.judgment import QualificationJudgmentError
from . import product_tools
from .actions import get_changed_notice
from .narration import _profile_for_ai, STATUS_CONCLUSION
from .v31_contracts import EvidenceBundle, Fact, Scope, Source, StatusCard


def _looks_like_extraction_noise(line: str) -> bool:
    compact = ''.join(line.split())
    if not compact:
        return False
    hangul = len(re.findall(r'[가-힣]', compact))
    cjk = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', compact))
    return hangul == 0 and cjk >= 2 and cjk / len(compact) >= 0.6


def _document_excerpt(text: str, question: str, limit: int = 1600) -> str:
    """Return a query-focused exact excerpt while dropping obvious extractor noise."""
    lines, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _looks_like_extraction_noise(line) or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    if not lines:
        return ''
    cleaned = '\n'.join(lines)
    if len(cleaned) <= limit:
        return cleaned

    terms = [
        token for token in re.findall(r'\d{3,}|[가-힣A-Za-z]{2,}', question)
        if token not in {'무슨', '어떤', '차이야', '알려줘', '보여줘', '설명해줘'}
    ]
    scores = [sum(term in line for term in terms) for line in lines]
    center = max(range(len(lines)), key=lambda index: scores[index]) if any(scores) else 0
    if len(lines[center]) >= limit:
        positions = [lines[center].find(term) for term in terms if term in lines[center]]
        focus = min((position for position in positions if position >= 0), default=0)
        start = max(0, focus - limit // 3)
        return lines[center][start:start + limit].strip()

    selected = {center}
    total = len(lines[center])
    distance = 1
    while total < limit and (center - distance >= 0 or center + distance < len(lines)):
        for index in (center - distance, center + distance):
            if index < 0 or index >= len(lines):
                continue
            addition = len(lines[index]) + 1
            if total + addition <= limit:
                selected.add(index)
                total += addition
        distance += 1
    return '\n'.join(lines[index] for index in sorted(selected)).strip()


class ProductTools:
    def __init__(self, db, case, *, allow_documents=False, gateway=None):
        self.db, self.case = db, case
        self.allow_documents, self.gateway = allow_documents, gateway
        self.scope = Scope(case_id=case.id, company_id=case.company_id, notice_id=case.notice_id,
                           notice_version_id=case.current_version_id)
        self.bundle = EvidenceBundle(scope=self.scope)
        self.summary = None
        self.checks = None
        self.card = None
        self.trace = []

    def _source(self, kind, quote, *, scope=None, evidence=None, location=None):
        scope = scope or self.scope
        location = location or (evidence.location if evidence else {})
        if hasattr(location, 'model_dump'):
            location = location.model_dump(mode='json', exclude_none=True)
        if evidence and getattr(evidence, 'notice_version_id', str(scope.notice_version_id)) != str(scope.notice_version_id):
            raise ValueError('EVIDENCE_SCOPE_MISMATCH')
        source_id = 's-' + digest([kind, quote, scope.model_dump(mode='json'), str(getattr(evidence, 'document_id', '')), location])[:20]
        source = Source(source_id=source_id, kind=kind, quote=quote, scope=scope,
                        document_id=str(evidence.document_id) if evidence and evidence.document_id else None,
                        location=location,
                        source_sha256=evidence.source_sha256 if evidence else None,
                        extracted_sha256=evidence.extracted_text_sha256 if evidence else None)
        if source_id not in {s.source_id for s in self.bundle.sources}:
            self.bundle.sources.append(source)
        return source_id

    def _fact(self, kind, text, ids, *, target='DOCUMENT', key=None, scope=None):
        scope = scope or self.scope
        fact_id = 'f-' + digest([kind, text, ids, scope.model_dump(mode='json')])[:20]
        if fact_id not in {f.fact_id for f in self.bundle.facts}:
            self.bundle.facts.append(Fact(fact_id=fact_id, kind=kind, text=text, source_ids=ids,
                                          target_kind=target, requirement_key=key, scope=scope))
        return fact_id

    def _summary(self):
        if self.summary is not None:
            return self.summary
        summary = product_tools.get_qualification_summary(self.db, self.case.id)
        p = summary.provenance
        if p.case_id != self.scope.case_id or p.company_id != self.scope.company_id or p.notice_version_id != self.scope.notice_version_id:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        self.scope = self.scope.model_copy(update={'analysis_run_id': p.analysis_run_id, 'judgment_run_id': p.judgment_run_id})
        self.bundle.scope = self.scope
        self.summary = summary
        self.bundle.server_context = {'overall_status': summary.overall_status,
                                      'judgment_counts': summary.judgment_counts,
                                      'provenance': p.model_dump(mode='json')}
        self.bundle.fingerprints['product'] = digest(summary.model_dump(mode='json'))
        return summary

    def judgment(self):
        summary = self._summary()
        self.card = StatusCard(status=summary.overall_status, text=STATUS_CONCLUSION[summary.overall_status], provenance=summary.provenance)
        evidence = product_tools.get_explanation_evidence(self.db, self.case.id, [r.requirement_key for r in summary.judgments])
        if any(e.provenance != summary.provenance for e in evidence):
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        by_key = {e.requirement.requirement_key: e.evidence for e in evidence}
        for item in summary.judgments:
            text = f'저장된 요건 상태: {item.status}. 요건: {item.raw}. 사유 코드: {item.reason_code}.'
            ids = [self._source('PRODUCT', text)]
            ids += [self._source('DOCUMENT', e.quote, evidence=e) for e in by_key[item.requirement_key] if e.quote.strip()]
            self._fact('SERVER_RESULT', text, ids, target='REQUIREMENT', key=item.requirement_key)
        if summary.analysis_status == 'PARTIAL':
            self.bundle.limitations.append('현재 분석은 부분 완료 상태이며 자동 판정 범위가 완전하지 않습니다.')

    def profile(self):
        summary = self._summary()
        profile = product_tools.get_judgment_profile_snapshot(self.db, self.case.id)
        if profile.provenance != summary.provenance:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        text = '판정 당시 회사정보: ' + json.dumps(_profile_for_ai(profile.profile_snapshot), ensure_ascii=False)
        self._fact('PROFILE_FACT', text, [self._source('PRODUCT', text)])

    def required_checks(self):
        summary = self._summary()
        checks = product_tools.get_required_checks(self.db, self.case.id)
        if checks.provenance != summary.provenance:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        self.checks = checks
        scope = summary.analysis_scope
        self.bundle.capabilities.update(answerable_count=sum(q.askable for q in checks.questions),
                                        unanswerable_count=sum(not q.askable for q in checks.questions),
                                        manual_review_count=(len(scope.notice_facts) + len(scope.dropped_requirements)) if scope else 0)
        for q in checks.questions:
            reason = (
                '현재 저장 판정에 이 회사 사실을 확정할 자료가 없다.'
                if q.askable else
                '현재 저장 회사정보만으로 판정할 수 없어 원문과 외부 증빙을 직접 대조해야 한다.'
            )
            action = (
                '회사 보유 증빙과 실제 상태를 확인한다.'
                if q.askable else
                '공고 원문을 기준으로 관계 기관 시스템, 허가·등록증 또는 제출 기록을 확인한다.'
            )
            text = (
                ('회사 확인 필요: ' if q.askable else '외부 확인 필요: ')
                + q.question + ' 이유: ' + reason + ' 다음 행동: ' + action
            )
            self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], target='REQUIREMENT', key=q.requirement_key)
        if scope:
            for item in scope.notice_facts:
                for e in item.evidence:
                    if e.quote.strip():
                        self._fact('NOTICE_FACT', e.quote, [self._source('DOCUMENT', e.quote, evidence=e)], target='MANUAL')
            for item in scope.dropped_requirements:
                # Raw dropped requirement alone has no original locator; never invent a citation.
                self.bundle.limitations.append('구조화에서 제외된 항목은 참가자격 화면에서 원문을 확인해 주세요: ' + item.raw)

    def documents(self, question):
        if not self.allow_documents:
            self.bundle.coverage['READ_DOCUMENT'] = 'UNAVAILABLE'
            self.bundle.limitations.append('공고문 근거 답변을 켜면 현재 공개 문서를 함께 확인할 수 있습니다.')
            return
        snapshot = snapshot_sources(load_notice_version_for_rag(self.db, self.case.current_version_id))
        self.bundle.fingerprints['document'] = snapshot.fingerprint
        embeddings = self.gateway or create_openai_embeddings()
        readiness = inspect_index(snapshot, os.getenv('DOCUMENT_RAG_INDEX_ROOT', 'data/document-rag'), embeddings)
        # When no model key exists, lexical current-section reads require no query embedding.
        if not embeddings.available:
            readiness.index = None
        broad = any(s in question for s in ('전체', '참가자격', '준비', '확인할', '모든'))
        from bidengine.rag.langchain_pipeline import retrieve_current
        try:
            passages, details = retrieve_current(readiness, question, broad=broad)
        except Exception:
            readiness.index = None
            passages, details = retrieve_current(readiness, question, broad=broad)
            details['query_embedding_failed'] = True
        self.trace.append({'tool': 'READ_DOCUMENT', 'source_status': snapshot.source_status,
                           'index_status': readiness.index_status, 'generation': readiness.generation,
                           'fingerprint': snapshot.fingerprint, 'verification': snapshot.verification, **details})
        self.bundle.limitations.extend(snapshot.limitations)
        if snapshot.source_status != 'AVAILABLE':
            self.bundle.limitations.append('확인 가능한 문서 범위가 제한되어 전체 조건을 확인했다고 볼 수 없습니다.')
        from types import SimpleNamespace
        found = False
        for passage in passages:
            m = passage.metadata
            if m.notice_version_id != str(self.scope.notice_version_id):
                raise ValueError('DOCUMENT_SCOPE_MISMATCH')
            quote = _document_excerpt(passage.text, question)
            if not quote:
                continue
            evidence = SimpleNamespace(document_id=m.document_id, source_sha256=m.source_sha256,
                                       extracted_text_sha256=m.extracted_text_sha256,
                                       location={'chunk_id': m.chunk_id, 'page': m.page, 'locations': m.source_locations})
            sid = self._source('DOCUMENT', quote, evidence=evidence)
            location = ', '.join(m.source_locations) or (f'p.{m.page}' if m.page is not None else m.chunk_id)
            self._fact('NOTICE_FACT', f'현재 공고문 근거: {m.document_name} · {location}', [sid])
            found = True
        self.bundle.coverage['READ_DOCUMENT'] = 'FOUND' if found else 'NOT_FOUND'
        if passages and not found:
            self.bundle.limitations.append('추출 원문에서 읽을 수 있는 관련 문장을 확인하지 못했습니다. 원본 문서를 직접 확인해 주세요.')

    def changes(self, *, compare_document_sources=False):
        result = get_changed_notice(self.db, self.case.id)
        p = result.provenance
        if (p.case_id != self.scope.case_id or p.company_id != self.scope.company_id
                or p.notice_id != self.scope.notice_id or p.current.notice_version_id != self.scope.notice_version_id):
            raise ValueError('CHANGE_SCOPE_MISMATCH')
        self.bundle.fingerprints['changes'] = digest(result.model_dump(mode='json'))
        from .change_impact import impact_text, read_change_impact
        impact = (read_change_impact(self.db, result)
                  if all(hasattr(self.db, name) for name in ('no_autoflush', 'scalar', 'get'))
                  else {'available': False, 'reason': '저장된 재검증 실행 기록을 이 조회 환경에서 확인하지 못했습니다.'})
        self.bundle.server_context['change_impact'] = impact
        impact_summary = impact_text(impact)
        self._fact('SERVER_RESULT', impact_summary,
                   [self._source('PRODUCT', impact_summary)], target='CHANGE')
        for change in result.changes:
            for label, version, requirement in [('이전', result.provenance.baseline, change.baseline), ('현재', result.provenance.current, change.current)]:
                if requirement is None:
                    continue
                scope = self.scope.model_copy(update={'notice_version_id': version.notice_version_id,
                                                      'analysis_run_id': version.analysis_run_id, 'judgment_run_id': version.judgment_run_id})
                text = f'{label} 버전 {version.version_number}: {requirement.raw} ({change.change_type})'
                self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text, scope=scope)], target='CHANGE', scope=scope)
        if self.allow_documents and compare_document_sources:
            from .source_changes import compare_sources
            before = load_notice_version_for_rag(self.db, self.case.baseline_version_id)
            after = load_notice_version_for_rag(self.db, self.case.current_version_id)
            if before.notice_id != self.scope.notice_id or after.notice_id != self.scope.notice_id:
                raise ValueError('CHANGE_DOCUMENT_SCOPE_MISMATCH')
            fingerprint, observations, limitations = compare_sources(before, after)
            self.bundle.fingerprints['change_sources'] = fingerprint
            self.bundle.limitations.extend(limitations)
            for text in observations:
                self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], target='CHANGE')

    def execute(self, task):
        if task.kind == 'READ_JUDGMENT': self.judgment()
        elif task.kind == 'READ_PROFILE': self.profile()
        elif task.kind == 'READ_CHECKS': self.required_checks()
        elif task.kind == 'READ_DOCUMENT': self.documents(task.question)
        elif task.kind == 'READ_CHANGES': self.changes(
            compare_document_sources='원문 표현 차이' in task.question
        )
        self.bundle.coverage.setdefault(task.kind, 'FOUND')

    def assert_fresh(self):
        self.db.refresh(self.case)
        if self.case.current_version_id != self.scope.notice_version_id or self.case.company_id != self.scope.company_id:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        if self.summary is not None:
            current = product_tools.get_qualification_summary(self.db, self.case.id)
            if digest(current.model_dump(mode='json')) != self.bundle.fingerprints['product']:
                raise ValueError('PRODUCT_SCOPE_CHANGED')
        if 'document' in self.bundle.fingerprints:
            current = snapshot_sources(load_notice_version_for_rag(self.db, self.case.current_version_id))
            if current.fingerprint != self.bundle.fingerprints['document']:
                raise ValueError('DOCUMENT_SCOPE_CHANGED')
        if 'changes' in self.bundle.fingerprints:
            current = get_changed_notice(self.db, self.case.id)
            if digest(current.model_dump(mode='json')) != self.bundle.fingerprints['changes']:
                raise ValueError('CHANGE_SCOPE_CHANGED')
        if 'change_sources' in self.bundle.fingerprints:
            from .source_changes import compare_sources
            fingerprint, _, _ = compare_sources(
                load_notice_version_for_rag(self.db, self.case.baseline_version_id),
                load_notice_version_for_rag(self.db, self.case.current_version_id),
            )
            if fingerprint != self.bundle.fingerprints['change_sources']:
                raise ValueError('CHANGE_DOCUMENT_SCOPE_CHANGED')
