import type { EvidenceLocation } from '@/lib/qualification-api';
import { evidenceLocationText } from '@/lib/status-copy';

type EvidenceQuoteProps = {
  /** 이 인용이 무엇에 대한 근거인지. 내부 키(evidence_key)를 그대로 넘기지 않는다. */
  label?: string;
  quote: string;
  /** 백엔드가 준 근거 위치. display가 있으면 그대로 쓴다 (P0-3). */
  location?: EvidenceLocation | null;
  note?: string;
};

export function EvidenceQuote({ label = '공고 원문 근거', quote, location, note }: EvidenceQuoteProps) {
  const locationText = evidenceLocationText(location);

  return (
    <div className="rounded-[14px] border border-[var(--product-line)] bg-[#f8f9fc] px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[12px] font-semibold text-[var(--product-accent-deep)]">{label}</p>
        {locationText && (
          <p className="text-[12px] font-medium text-[var(--product-muted)]">{locationText}</p>
        )}
      </div>
      <p className="mt-1.5 text-[14px] leading-6 text-[var(--product-body)]">“{quote}”</p>
      {note && <p className="mt-1 text-[12px] leading-5 text-[var(--product-muted)]">{note}</p>}
    </div>
  );
}
