'use client';

import { ChevronDown } from 'lucide-react';
import { useId, useState } from 'react';
import type { CopilotEnvelope } from '@/lib/copilot-v31';
import { CopilotNavigationLink } from './navigation-link';

type EnvelopeSource = CopilotEnvelope['sources'][number];

function EvidenceGroup({ label, sources }: { label: string; sources: EnvelopeSource[] }) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  if (!sources.length) return null;
  return <div className={`copilot-evidence-group${open ? ' is-open' : ''}`}>
    <button type="button" className="copilot-evidence-toggle" aria-expanded={open} aria-controls={contentId}
      onClick={() => setOpen(value => !value)}>
      <span><ChevronDown size={15} aria-hidden="true" />{label} {sources.length}건</span>
      <span>{open ? '접기' : '보기'}</span>
    </button>
    {open && <div id={contentId} className="copilot-evidence-list">
      {sources.map((source, index) => <article className="copilot-evidence-item" key={source.source_id}>
        <strong>근거 {index + 1}</strong>
        <blockquote>{source.quote || '인용문을 표시하지 못했습니다.'}</blockquote>
        <small>버전 {source.scope.notice_version_id.slice(0, 8)} {typeof source.location.page === 'number' ? `· p.${source.location.page}` : ''}</small>
        {source.kind === 'DOCUMENT' && <CopilotNavigationLink caseId={source.scope.case_id}
          href={`/evidence?caseId=${encodeURIComponent(source.scope.case_id)}`}>원문 화면 열기</CopilotNavigationLink>}
      </article>)}
    </div>}
  </div>;
}

function LimitationGroup({ limitations }: { limitations: string[] }) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  if (!limitations.length) return null;
  return <div className={`copilot-evidence-group copilot-check-group${open ? ' is-open' : ''}`}>
    <button type="button" className="copilot-evidence-toggle" aria-expanded={open} aria-controls={contentId}
      onClick={() => setOpen(value => !value)}>
      <span><ChevronDown size={15} aria-hidden="true" />추가 확인 필요 {limitations.length}건</span>
      <span>{open ? '접기' : '보기'}</span>
    </button>
    {open && <div id={contentId} className="copilot-evidence-list">
      {limitations.map((text, index) => <p className="copilot-limitation" key={index}>{text}</p>)}
    </div>}
  </div>;
}

export function EnvelopeAnswer({ envelope }: { envelope: CopilotEnvelope }) {
  const uniqueSources = [...new Map(envelope.sources.map(source => [source.source_id, source])).values()];
  const productSources = uniqueSources.filter(source => source.kind === 'PRODUCT');
  const documentSources = uniqueSources.filter(source => source.kind === 'DOCUMENT');
  const conversationSources = uniqueSources.filter(source => source.kind === 'TURN');
  const hasPrimaryAnswer = Boolean(envelope.status_card || envelope.clarification || envelope.claims.length);
  return <section aria-label="근거 기반 검토 답변" data-copilot-version="3.1">
    {envelope.status_card && <output className="copilot-status-card">
      <strong>{envelope.status_card.text}</strong>
      <small>공고 v{envelope.status_card.provenance.version_number} · 저장된 판정 기준</small>
    </output>}
    {envelope.clarification && <p>{envelope.clarification}</p>}
    {!hasPrimaryAnswer && <p className="copilot-limitation">
      {envelope.limitations[0] ?? '현재 자료로는 이 질문의 답변을 확인하지 못했습니다.'}
    </p>}
    <div className="copilot-claims">
      {envelope.claims.map((claim, index) => <p className={index === 0 ? 'copilot-conclusion' : undefined}
        key={claim.claim_id}>{claim.text}</p>)}
    </div>
    <div className="copilot-evidence-groups" aria-label="답변 근거와 추가 확인사항">
      <EvidenceGroup label="저장된 판정 근거" sources={productSources} />
      <EvidenceGroup label="공고문 원문 근거" sources={documentSources} />
      <EvidenceGroup label="대화에서 확인한 내용" sources={conversationSources} />
      <LimitationGroup limitations={envelope.limitations} />
    </div>
  </section>;
}
