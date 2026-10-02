'use client';

import { CopilotNavigationLink } from '@/components/copilot/navigation-link';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import type { CaseWorkspace } from '@/lib/case-workspace';
import { workspaceHref } from '@/lib/case-workspace';

export function CaseHeader({ workspace }: { workspace: CaseWorkspace }) {
  const { caseItem, notice, displayJudgment } = workspace;
  const unknown = displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;

  return (
    <section className="flex flex-col justify-between gap-5 border-b border-[var(--product-line)] pb-[26px] lg:flex-row lg:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary">{notice.latest.contract_method ?? '계약방법 미상'}</Badge>
          <Badge variant="outline">{caseItem.current_version_number}차 공고</Badge>
          {unknown > 0 && <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">확인 필요 {unknown}</span>}
        </div>
        <h2 className="mt-4 text-[24px] font-bold leading-9 tracking-[-0.035em] text-[var(--product-ink)]">{notice.title}</h2>
        <p className="mt-2 text-[13px] text-[var(--product-muted)]">공고번호 {notice.bid_notice_no} · {notice.announcing_institution_name ?? notice.demanding_institution_name ?? '기관 미상'}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {notice.latest.detail_url && <Button variant="outline" size="sm" render={<a href={notice.latest.detail_url} target="_blank" rel="noreferrer" aria-label="공고문 원본" />}>공고문 원본</Button>}
        <CopilotNavigationLink caseId={caseItem.id} href={workspaceHref('/qualification', caseItem.id)} className={buttonVariants({ variant: 'outline', size: 'sm' })}>검토로 돌아가기</CopilotNavigationLink>
      </div>
    </section>
  );
}

export function CaseTabs({ caseId, active }: { caseId: string; active: 'qualification' | 'questions' | 'evidence' | 'evaluation' | 'changes' }) {
  const items = [
    ['qualification', '/qualification', '참가자격'],
    ['questions', '/ask-back', '확인 필요'],
    ['evidence', '/evidence', '근거 원문'],
    ['evaluation', '/evaluation', '평가 대응'],
    ['changes', '/changes', '변경 이력'],
  ] as const;

  return (
    <nav className="mt-5 flex flex-wrap gap-2 border-b border-[var(--product-line)] pb-3" aria-label="입찰 검토 화면">
      {items.map(([key, href, label]) => (
        <CopilotNavigationLink caseId={caseId} key={key} href={workspaceHref(href, caseId)} className={`rounded-full px-5 py-2 text-[13px] font-semibold ${active === key ? 'bg-[var(--product-ink)] text-white' : 'border border-[var(--product-line)] bg-white text-[var(--product-body)]'}`}>{label}</CopilotNavigationLink>
      ))}
    </nav>
  );
}
