'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { BASIS_TYPE_LABEL, EXTRACTION_STATUS_LABEL, REASON_CODE_LABEL, judgmentBadgeLabel, labelOf } from '@/lib/status-copy';
import { Button, buttonVariants } from '@/components/ui/button';
import { CopilotNavigationLink } from '@/components/copilot/navigation-link';
import { absoluteApiUrl, getDocumentText, type NoticeDocumentText } from '@/lib/api';
import { currentVersion, useCaseWorkspace, workspaceHref, type CaseWorkspace } from '@/lib/case-workspace';

function displayLocation(location: Record<string, unknown>) {
  const display = location.display;
  if (typeof display === 'string' && display) return display;
  const page = location.page;
  const clause = location.clause_label;
  return [clause, typeof page === 'number' || typeof page === 'string' ? `p.${page}` : null].filter(Boolean).join(' ') || '위치 정보 없음';
}

function blockText(block: Record<string, unknown>) {
  for (const key of ['text', 'content', 'raw', 'paragraph_text']) {
    const value = block[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export default function EvidencePage() {
  const searchParams = useSearchParams();
  const caseId = searchParams.get('caseId');
  const evidenceParam = searchParams.get('evidence');
  const expectedAnalysis = searchParams.get('analysisRunId');
  const { workspace, error } = useCaseWorkspace(caseId);
  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{error || <LoaderCircle className="size-7 animate-spin" />}</main>;
  // A historical Copilot chip must not silently open a reused key in a new run.
  if (expectedAnalysis && expectedAnalysis !== workspace.currentAnalysisDetail?.id) {
    return <main className="app-shell-container py-12">
      <CaseHeader workspace={workspace} />
      <CaseTabs caseId={caseId} active="evidence" />
      <section role="alert" className="mt-5 rounded-xl border border-[var(--product-warn-line)] bg-[var(--product-warn-soft)] p-5">
        <h2 className="font-bold">이 근거는 이전 분석 기준입니다</h2>
        <p className="mt-2">현재 분석과 연결 기준이 달라 같은 근거 키로 자동 이동하지 않았습니다. 과거 인용문은 대화에서 확인할 수 있습니다.</p>
        <NavigationLink href={workspaceHref('/evidence', caseId)} className="mt-3 inline-block underline">현재 분석의 근거 선택하기</NavigationLink>
      </section>
    </main>;
  }
  return <EvidenceWorkspace key={`${caseId}:${workspace.currentAnalysis?.id}:${evidenceParam}`} workspace={workspace} evidenceParam={evidenceParam} />;
}

function EvidenceWorkspace({ workspace, evidenceParam }: { workspace: CaseWorkspace; evidenceParam: string | null }) {
  const version = currentVersion(workspace);
  const initialEvidence = evidenceParam
    ? workspace.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === evidenceParam)
    : workspace.currentAnalysisDetail?.evidence[0];
  const [documentId, setDocumentId] = useState(initialEvidence?.document_id ?? version.documents[0]?.id ?? '');
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState(initialEvidence?.evidence_key ?? '');
  const [loadedText, setLoadedText] = useState<{ documentId: string; text: NoticeDocumentText | null; error: string } | null>(null);
  const document = version.documents.find((item) => item.id === documentId) ?? null;
  const documentText = loadedText?.documentId === documentId ? loadedText.text : null;
  const textError = loadedText?.documentId === documentId ? loadedText.error : '';

  useEffect(() => {
    let cancelled = false;
    if (!document) return;
    getDocumentText(document.text_url).then((text) => {
      if (!cancelled) setLoadedText({ documentId: document.id, text, error: '' });
    }).catch(() => {
      if (!cancelled) setLoadedText({ documentId: document.id, text: null, error: '원문 텍스트를 불러오지 못했습니다. 원본 열기로 확인해 주세요.' });
    });
    return () => { cancelled = true; };
  }, [document]);

  const evidence = workspace?.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === selectedEvidenceKey) ?? null;
  const requirement = evidence
    ? workspace?.currentAnalysisDetail?.requirements.find((item) => item.evidence_keys.includes(evidence.evidence_key)) ?? null
    : null;
  const judgment = requirement
    ? workspace?.displayJudgment?.judgments.find((item) => item.requirement_key === requirement.requirement_key) ?? null
    : null;

  const nearbyEvidence = useMemo(() => {
    if (!workspace?.currentAnalysisDetail) return [];
    return workspace.currentAnalysisDetail.evidence.slice(0, 8);
  }, [workspace]);


  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="evidence" />

        <div className="mt-5 flex flex-wrap gap-2">
          {version?.documents.map((item) => (
            <button key={item.id} type="button" onClick={() => { setDocumentId(item.id); setSelectedEvidenceKey(workspace.currentAnalysisDetail?.evidence.find((entry) => entry.document_id === item.id)?.evidence_key ?? ''); }} className={`h-10 rounded-full px-5 text-[14px] font-semibold ${documentId === item.id ? 'bg-[var(--product-ink)] text-white' : 'border border-[var(--product-line)] bg-white'}`}>{item.name}</button>
          ))}
        </div>

        <section className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,862px)_minmax(360px,470px)]">
          <div className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
            <div className="flex flex-wrap items-center gap-3 border-b border-[var(--product-line)] pb-[14px]">
              <strong className="text-[14px]">{document?.name ?? '문서 없음'}</strong>
              <span className="text-[12.5px] text-[var(--product-muted)]">{labelOf(EXTRACTION_STATUS_LABEL, document?.extraction_status)}</span>
              {document && <Button variant="outline" size="sm" className="ml-auto" render={<a href={absoluteApiUrl(document.render_source_url)} target="_blank" rel="noreferrer" aria-label="원본 열기" />}>원본 열기</Button>}
            </div>

            <div className="mt-3 max-h-[620px] overflow-y-auto pr-2">
              {documentText?.blocks?.length ? documentText.blocks.map((block, index) => {
                const text = blockText(block);
                if (!text) return null;
                const start = evidence?.location.block_start;
                const end = evidence?.location.block_end;
                const blockIndex = typeof block.block_index === 'number' ? block.block_index : index;
                const active = evidence?.document_id === document?.id && typeof start === 'number' && typeof end === 'number' && blockIndex >= start && blockIndex <= end;
                return <div key={index} className={`flex gap-4 rounded-[20px] px-[18px] py-[14px] text-[14.5px] leading-[1.85] ${active ? 'bg-[#fbf0dc] font-semibold' : ''}`}><span className="w-10 shrink-0 text-[13px] font-semibold text-[var(--product-muted)]">{index + 1}</span><p>{text}</p></div>;
              }) : documentText?.text ? <pre className="whitespace-pre-wrap text-[14px] leading-7 text-[var(--product-body)]">{documentText.text}</pre> : <div className="grid min-h-[420px] place-items-center text-[14px] text-[var(--product-muted)]">{textError || '추출 텍스트가 없습니다. 원본 열기로 확인해 주세요.'}</div>}
            </div>
            <p className="mt-4 text-[12.5px] text-[var(--product-muted)]">원문을 그대로 표시하며, 이 화면에서 문장을 요약하거나 고쳐 쓰지 않습니다.</p>
          </div>

          <aside className="space-y-4">
            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
              {evidence ? <>
                <div className="flex items-center gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">{judgment?.status === 'SATISFIED' ? '충족' : judgment?.status === 'UNSATISFIED' ? '미달' : '확인 필요'}</span><span className="text-[12.5px] text-[var(--product-muted)]">{displayLocation(evidence.location)}</span></div>
                <h2 className="mt-4 text-[18px] font-bold">{requirement?.raw ?? '판정 근거'}</h2>
                <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>
                <div className="mt-4 divide-y divide-[var(--product-line-2)] text-[13px]"><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">판정</span><strong>{judgmentBadgeLabel(judgment?.status ?? 'UNJUDGED', judgment?.basis_type)}</strong></div><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">무엇을 보고 판정했나</span><span>{judgment ? BASIS_TYPE_LABEL[judgment.basis_type] : '아직 판정하지 않았습니다'}</span></div><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">판정 사유</span><span>{judgment ? (REASON_CODE_LABEL[judgment.reason_code as keyof typeof REASON_CODE_LABEL] ?? '사유가 기록되지 않았습니다') : '-'}</span></div></div>
              </> : <p className="text-[14px] text-[var(--product-muted)]">선택할 Evidence가 없습니다.</p>}
            </section>

            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
              <div className="flex items-baseline justify-between"><h2 className="text-[18px] font-bold">같은 화면에서 볼 수 있는 근거</h2><span className="text-[12px] text-[var(--product-muted)]">{nearbyEvidence.length}건</span></div>
              <div className="mt-3 divide-y divide-[var(--product-line)]">{nearbyEvidence.map((item) => <button key={item.evidence_key} type="button" onClick={() => { setSelectedEvidenceKey(item.evidence_key); setDocumentId(item.document_id); }} className="flex w-full items-center justify-between gap-3 py-3 text-left"><span className="truncate text-[13px]">{item.quote}</span><span className="shrink-0 text-[12px] font-semibold text-[var(--product-accent)]">{displayLocation(item.location)}</span></button>)}</div>
            </section>

            <CopilotNavigationLink caseId={workspace.caseItem.id} href={workspaceHref('/ask-back', workspace.caseItem.id)} className={buttonVariants({ variant: 'outline', className: 'w-full rounded-full' })}>확인 필요에 답하기</CopilotNavigationLink>
          </aside>
        </section>
      </div>
    </main>
  );
}
import { NavigationLink } from '@/components/navigation-link';
