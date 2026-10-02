import { NavigationLink } from '@/components/navigation-link';
import { buttonVariants } from '@/components/ui/button';
import type { BidNoticeSummary, BidNoticeVersion, PreflightCase } from '@/lib/api';
import { BUSINESS_TYPE_LABEL, EXTRACTION_STATUS_LABEL, VIEWER_TYPE_LABEL, labelOf } from '@/lib/status-copy';

function money(value: number | null | undefined) {
  return value == null ? '-' : `${value.toLocaleString()}원`;
}

function dateTime(value: string | null | undefined) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

type Props = {
  caseItem: PreflightCase;
  notice: BidNoticeSummary | null;
  version: BidNoticeVersion | null;
};

export function QualificationSourceOverview({ caseItem, notice, version }: Props) {
  const summary = [
    ['입찰공고번호', caseItem.bid_notice_no],
    ['공고차수', `${caseItem.current_version_number}차`],
    ['공고기관', notice?.announcing_institution_name ?? '-'],
    ['사업유형', labelOf(BUSINESS_TYPE_LABEL, notice?.business_type)],
    ['계약방법', version?.contract_method ?? '-'],
    ['추정가격', money(version?.estimated_price)],
    ['배정예산', money(version?.allocated_budget)],
    ['입찰서 제출마감', dateTime(version?.bid_closed_at)],
    ['개찰일시', dateTime(version?.opened_at)],
  ];

  return (
    <>
      <section className="mt-7">
        <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">나라장터 공고 요약</h2><span className="text-[15px] text-[var(--product-muted)]">수집된 원본 필드만 표시합니다</span></div>
        <div className="mt-3 overflow-hidden rounded-[20px] border-t border-[var(--product-line)]">
          <div className="grid md:grid-cols-3">
            {summary.map(([label, value]) => <div key={label} className="grid min-h-[48px] grid-cols-[130px_minmax(0,1fr)] border-b border-[var(--product-line-2)] md:[&:not(:nth-child(3n))]:border-r"><span className="bg-[var(--product-tint)] px-4 py-3 text-[15px] text-[var(--product-muted)]">{label}</span><strong className="px-4 py-3 text-[15px] font-medium text-[var(--product-ink)]">{value}</strong></div>)}
          </div>
        </div>
      </section>

      <section className="mt-7">
        <div className="rounded-[20px] border border-[var(--product-line-2)] bg-white p-6">
          <div className="flex items-baseline justify-between gap-3"><div><h2 className="text-[21px] font-extrabold">제출·첨부 서류</h2><p className="mt-1 text-[13px] text-[var(--product-muted)]">현재 차수에서 실제 수집된 문서입니다.</p></div><span className="text-[13px] text-[var(--product-muted)]">{version?.documents.length ?? 0}종</span></div>
          <div className="mt-4 divide-y divide-[var(--product-line-2)]">
            {version?.documents.length ? version.documents.map((document) => <div key={document.id} className="flex items-center gap-3 py-3"><div className="min-w-0 flex-1"><strong className="block truncate text-[15px]">{document.name}</strong><span className="mt-1 block text-[12px] text-[var(--product-muted)]">{labelOf(VIEWER_TYPE_LABEL, document.viewer_type)} · {labelOf(EXTRACTION_STATUS_LABEL, document.extraction_status)}{document.extracted_char_count != null ? ` · ${document.extracted_char_count.toLocaleString()}자` : ''}</span></div><NavigationLink href={`/evidence?caseId=${caseItem.id}`} className={buttonVariants({ variant: 'outline', size: 'sm', className: 'rounded-full' })}>원문 대조</NavigationLink></div>) : <p className="py-6 text-center text-[15px] text-[var(--product-muted)]">현재 차수에 수집된 문서가 없습니다.</p>}
          </div>
        </div>
      </section>
    </>
  );
}
