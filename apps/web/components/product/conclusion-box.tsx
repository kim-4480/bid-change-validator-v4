import type { ReactNode } from 'react';

type ConclusionBoxProps = {
  title: string;
  description: string;
  satisfied: number;
  unknown: number;
  unsatisfied: number;
  action?: ReactNode;
};

export function ConclusionBox({
  title,
  description,
  satisfied,
  unknown,
  unsatisfied,
  action,
}: ConclusionBoxProps) {
  return (
    <section className="rounded-[20px] border border-[#d9def7] bg-[#f5f6ff] px-6 py-5">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-[var(--product-accent-deep)]">판정 요약</p>
          <h2 className="mt-1 text-[28px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">{title}</h2>
          <p className="mt-2 max-w-4xl text-[15px] leading-6 text-[var(--product-muted)]">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-[88px] rounded-2xl bg-white px-4 py-3 text-center shadow-sm">
            <span className="block text-[12px] text-[var(--product-muted)]">충족</span>
            <strong className="mt-1 block text-[28px] text-emerald-700">{satisfied}</strong>
          </div>
          <div className="min-w-[88px] rounded-2xl bg-white px-4 py-3 text-center shadow-sm">
            <span className="block text-[12px] text-[var(--product-muted)]">확인 필요</span>
            <strong className="mt-1 block text-[28px] text-amber-700">{unknown}</strong>
          </div>
          <div className="min-w-[88px] rounded-2xl bg-white px-4 py-3 text-center shadow-sm">
            <span className="block text-[12px] text-[var(--product-muted)]">미달</span>
            <strong className="mt-1 block text-[28px] text-rose-700">{unsatisfied}</strong>
          </div>
          {action}
        </div>
      </div>
    </section>
  );
}
