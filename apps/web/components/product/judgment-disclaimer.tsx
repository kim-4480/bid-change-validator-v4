import { Info } from 'lucide-react';

/**
 * 판정이 나오는 모든 화면에 붙이는 안내(2026-10-08 사용자 요청). 문구는 한 곳에서만 바꾼다.
 * compact: 코파일럿 패널처럼 좁은 자리에서 한 줄로.
 */
export const JUDGMENT_DISCLAIMER = '비드체크의 판정은 AI 기반이며 실수할 수 있습니다. 사람의 판단을 대신할 수 없습니다.';

export function JudgmentDisclaimer({ compact = false, className = '' }: { compact?: boolean; className?: string }) {
  if (compact) {
    return <p role="note" className={`text-[12px] leading-5 text-[var(--product-muted)] ${className}`}>{JUDGMENT_DISCLAIMER}</p>;
  }
  return (
    <p role="note" className={`flex items-start gap-2 rounded-[12px] border border-[var(--product-line)] bg-[var(--product-tint)] px-4 py-2.5 text-[13px] leading-5 text-[var(--product-muted)] ${className}`}>
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{JUDGMENT_DISCLAIMER}</span>
    </p>
  );
}
