import { Eye } from 'lucide-react';

import { Button } from '@/components/ui/button';

export type QualificationRowStatus = 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN' | 'UNJUDGED';
export type QualificationRowBasis = 'PROFILE' | 'USER_ANSWER' | 'NONE';

type QualificationRowProps = {
  status: QualificationRowStatus;
  /** 판정이 무엇에 근거했는지. USER_ANSWER면 NFR-5에 따라 문서 근거와 구분해서 표시한다. */
  basisType?: QualificationRowBasis;
  condition: string;
  companyValue: string;
  evidenceLabel: string;
  /**
   * 「조치」 열에 쓸 말. 할 일이 없는 행(판정이 끝난 행)은 null을 준다.
   * 예전에는 판정이 끝나면 「판정 완료」를 넣었는데, 조치 열은 무엇을 하라는 자리라
   * 미달 행 아래에 「판정 완료」가 붙으면 뭘 하라는 건지 알 수 없었다. 판정 배지는 이미 왼쪽에 있다.
   */
  actionLabel?: string | null;
  onEvidence?: () => void;
  onAction?: () => void;
};

const STATUS_STYLE: Record<QualificationRowStatus, { label: string; className: string }> = {
  SATISFIED: {
    label: '충족',
    className: 'border-[var(--product-ok-line)] bg-[var(--product-ok-soft)] text-[var(--product-ok)]',
  },
  UNSATISFIED: {
    label: '미달',
    className: 'border-[var(--product-bad-line)] bg-[var(--product-bad-soft)] text-[var(--product-bad)]',
  },
  UNKNOWN: {
    label: '확인 필요',
    className: 'border-[var(--product-warn-line)] bg-[var(--product-warn-soft)] text-[var(--product-warn)]',
  },
  UNJUDGED: {
    label: '미판정',
    className: 'border-[var(--product-neutral-line)] bg-[var(--product-neutral-soft)] text-[var(--product-neutral)]',
  },
};

export function QualificationRow({
  status,
  basisType = 'PROFILE',
  condition,
  companyValue,
  evidenceLabel,
  actionLabel,
  onEvidence,
  onAction,
}: QualificationRowProps) {
  const statusMeta = STATUS_STYLE[status];

  // NFR-5 · 사용자 답변에 근거한 판정은 문서 근거 판정과 같은 모양으로 보이면 안 된다.
  // 색은 판정 그대로 두고(NFR-10), 테두리를 점선으로 바꾸고 근거를 라벨에 붙인다.
  const isUserAnswer = basisType === 'USER_ANSWER' && (status === 'SATISFIED' || status === 'UNSATISFIED');
  const statusLabel = isUserAnswer ? `${statusMeta.label} · 귀사 답변 기준` : statusMeta.label;
  const borderStyle = isUserAnswer ? 'border-dashed' : 'border-solid';

  return (
    <div className="grid min-h-[64px] grid-cols-1 border-t border-[var(--product-line-2)] lg:grid-cols-[152px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px]">
      <div className="flex items-center px-3 py-3">
        <span
          className={`rounded-full border ${borderStyle} px-2.5 py-1 text-[12px] font-semibold ${statusMeta.className}`}
        >
          {statusLabel}
        </span>
      </div>
      <div className="flex items-center px-3 py-3 text-[14px] font-medium leading-6 text-[var(--product-body)]">{condition}</div>
      <div className="flex items-center px-3 py-3 text-[13px] leading-5 text-[var(--product-muted)]">
        {isUserAnswer ? (
          <div>
            <p className="font-medium text-[var(--product-body)]">귀사가 답한 값으로 판정했습니다</p>
            <p className="text-[11.5px]">회사 프로필에는 저장하지 않았습니다</p>
          </div>
        ) : (
          companyValue
        )}
      </div>
      <div className="flex items-center px-3 py-3">
        <button
          type="button"
          onClick={onEvidence}
          disabled={!onEvidence}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--product-accent-deep)] disabled:cursor-default disabled:text-[var(--product-faint)]"
        >
          <Eye className="size-4" /> {evidenceLabel}
        </button>
      </div>
      <div className="flex items-center px-3 py-3">
        {onAction ? (
          <Button size="sm" variant={status === 'UNKNOWN' ? 'default' : 'outline'} onClick={onAction} className="rounded-full">
            {actionLabel}
          </Button>
        ) : actionLabel ? (
          <span className="text-[12px] text-[var(--product-faint)]">{actionLabel}</span>
        ) : null}
      </div>
    </div>
  );
}
