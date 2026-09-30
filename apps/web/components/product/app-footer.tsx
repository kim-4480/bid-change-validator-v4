import { PageContainer } from '@/components/product/page-container';

/*
  전에는 「개인정보처리방침 · 이용약관 · 공개 API 이용안내 · 고객지원」 넷을 회색 글자로 두고
  옆에 「준비 중」 알약을 붙여뒀다. 연결할 화면이 없는 항목을 메뉴처럼 보이게 둘 이유가 없어 걷어낸다.
  「검토 워크벤치」도 뺀다 — /workbench는 9/6 구 화면이라 눌러서 들어가면 다른 제품처럼 보인다.
  라우트는 그대로 살아 있으니 주소로는 계속 들어갈 수 있다.
*/
export function AppFooter() {
  return (
    <footer className="app-footer">
      <PageContainer className="flex flex-col items-start gap-5 pt-9 pb-10 md:flex-row md:items-center md:gap-8">
        <div className="flex shrink-0 items-center gap-2.5">
          {/* 헤더와 같은 마크를 쓴다. 전에는 회색 사각형 자리표시자가 그대로 남아 있었다. */}
          <span className="text-[var(--product-accent)]" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="24" height="24" focusable="false">
              <rect width="32" height="32" rx="10" fill="currentColor" />
              <path d="M9.5 16.8l4.4 4.4L22.5 12" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </span>
          <strong className="text-[15px] font-bold leading-[1.5] tracking-[-0.025em] text-[var(--product-muted)]">비드체크</strong>
        </div>
        <p className="max-w-[76ch] text-[13px] leading-[1.7] text-[var(--product-muted)]">
          실제 나라장터 공고 원문과 회사 프로필을 기반으로 참가자격과 변경 영향을 검토합니다.
          판정 결과는 근거 원문과 함께 확인하고, 최종 제출 전 담당자가 다시 검토해야 합니다.
          <span className="mt-1 block text-[var(--product-faint)]">© 2026 BIDCHECK. All rights reserved.</span>
        </p>
      </PageContainer>
    </footer>
  );
}
