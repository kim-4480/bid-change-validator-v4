import { PageContainer } from '@/components/product/page-container';

export type TitleBandProps = {
  title: string;
  description: string;
  breadcrumb: string;
  variant?: 'default' | 'tall';
};

export function TitleBand({ title, description, breadcrumb, variant = 'default' }: TitleBandProps) {
  return (
    <section className={`app-title-band ${variant === 'tall' ? 'app-title-band-tall' : ''}`}>
      <PageContainer className="flex h-full items-end justify-between gap-8 pb-[34px]">
        <div className="flex min-w-0 flex-1 flex-col items-start gap-[9px]">
          <h1 className="text-[29px] font-extrabold leading-[44px] tracking-[-0.04em] text-[var(--product-ink)]">
            {title}
          </h1>
          <p className="text-[14px] leading-[21px] text-[var(--product-muted)]">{description}</p>
        </div>
        <p className="hidden shrink-0 pb-[2px] text-[12.5px] leading-[19px] text-[var(--product-muted)] md:block">
          {breadcrumb}
        </p>
      </PageContainer>
    </section>
  );
}
