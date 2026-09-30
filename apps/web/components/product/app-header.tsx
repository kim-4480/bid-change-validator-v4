'use client';

import { NavigationLink } from '@/components/navigation-link';
import { PageContainer } from '@/components/product/page-container';
import type { AuthUser } from '@/lib/auth';

/*
  메뉴는 실제로 동작하는 것만 둔다.
  「서류함」은 /documents 라우트 자체가 없고, 「알림」·「전체메뉴」는 누를 수 있는 동작이 없었다.
  회색으로 막아두면 「미완성 제품」으로 읽히고, 로드맵은 화면이 아니라 발표에서 말하면 된다.
*/
const PRIMARY_NAV = [
  { label: '공고 찾기', href: '/notices' },
  { label: '내 입찰 건', href: '/qualification' },
  { label: '회사 프로필', href: '/company' },
  { label: '이용안내', href: '/guide' },
] as const;

function isActive(pathname: string, href: string) {
  if (href === '/notices') return pathname.startsWith('/notices');
  if (href === '/qualification') {
    return (
      pathname.startsWith('/cases') ||
      ['/qualification', '/ask-back', '/evidence', '/evaluation', '/changes'].some((route) =>
        pathname.startsWith(route),
      )
    );
  }
  if (href === '/company') return pathname.startsWith('/company') || pathname.startsWith('/company-profile');
  return pathname.startsWith(href);
}

export function AppHeader({
  pathname,
  user,
  onLogout,
}: {
  pathname: string;
  user: AuthUser | null;
  onLogout: () => void;
}) {
  return (
    <header className="app-header">
      <div className="app-utility-bar">
        <PageContainer className="flex h-full items-center justify-between text-[13px] leading-[19px]">
          {/* 우리가 쓰는 공고 데이터의 출처. 링크처럼 보이므로 실제 출처로 연결한다. */}
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <a href="https://www.g2b.go.kr" target="_blank" rel="noreferrer noopener" className="app-utility-action" aria-label="나라장터 (새 창으로 열림)">나라장터</a>
            <a href="https://www.pps.go.kr" target="_blank" rel="noreferrer noopener" className="app-utility-action" aria-label="조달청 (새 창으로 열림)">조달청</a>
          </div>
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            {user ? (
              <>
                <span>{user.company_name ?? user.username}</span>
                <button type="button" className="app-utility-action" onClick={onLogout}>로그아웃</button>
              </>
            ) : (
              <NavigationLink href="/login" className="app-utility-action">로그인</NavigationLink>
            )}
          </div>
        </PageContainer>
      </div>

      <div className="app-gnb">
        <PageContainer className="flex h-full items-center gap-5">
          <NavigationLink href="/notices" className="app-brand" aria-label="비드체크 공고 찾기">
            {/*
              마크. 이름의 「체크」를 그대로 그린다.
              30px 안에서는 요소 하나가 가장 잘 읽힌다 — 줄·문서를 같이 넣으면 뭉개진다.
            */}
            <span className="app-brand-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="30" height="30" focusable="false">
                <rect width="32" height="32" rx="10" fill="currentColor" />
                <path d="M9.5 16.8l4.4 4.4L22.5 12" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              </svg>
            </span>
            <span className="app-brand-copy">
              <strong className="app-brand-name">비드체크</strong>
              <span className="app-brand-subtitle">입찰 참가자격 확인</span>
            </span>
          </NavigationLink>

          <nav className="app-primary-nav" aria-label="주요 메뉴">
            {PRIMARY_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="app-nav-link"
                aria-current={isActive(pathname, item.href) ? 'page' : undefined}
              >
                {item.label}
              </a>
            ))}
          </nav>
        </PageContainer>
      </div>
    </header>
  );
}
