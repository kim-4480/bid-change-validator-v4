'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { CopilotProvider } from '@/components/copilot/provider';
import { CopilotPanel } from '@/components/copilot/panel';

import { AppFooter } from '@/components/product/app-footer';
import { AppHeader } from '@/components/product/app-header';
import { TitleBand, type TitleBandProps } from '@/components/product/title-band';
import { ApiError, NETWORK_ERROR_MESSAGE } from '@/lib/api';
import { getCurrentUser, logout, type AuthUser } from '@/lib/auth';
import { replaceWith } from '@/lib/navigation';

type PageInfo = TitleBandProps & {
  showTitleBand?: boolean;
};

const LEGACY_ACTIVE_CASE_KEY = 'bidcheck:active-case-id';

const PAGE_INFO: Array<{ match: (pathname: string) => boolean; page: PageInfo }> = [
  {
    match: (pathname) => pathname.startsWith('/notices'),
    page: {
      title: '공고 찾기',
      description: '회사 프로필과 공고 원문 근거를 기준으로 검토할 공고를 찾습니다.',
      breadcrumb: '홈 › 공고 찾기',
      showTitleBand: false,
    },
  },
  {
    match: (pathname) => pathname.startsWith('/workbench'),
    page: {
      title: '검토 워크벤치',
      description: '공고 원문과 제출 문서를 나란히 두고 검토 건을 만드는 작업 화면입니다.',
      breadcrumb: '홈 › 검토 워크벤치',
    },
  },
  {
    match: (pathname) =>
      (pathname.startsWith('/cases/') && pathname.endsWith('/qualification')) ||
      pathname === '/qualification',
    page: {
      title: '참가자격 검토',
      description: '판정한 모든 항목에 공고 원문 근거를 함께 표시합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토',
      variant: 'tall',
    },
  },
  {
    match: (pathname) =>
      (pathname.startsWith('/cases/') && pathname.endsWith('/questions')) || pathname === '/ask-back',
    page: {
      title: '확인 필요에 답하기',
      description: '이유가 셋이고, 이유마다 하실 일이 다릅니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토 › 확인 필요',
    },
  },
  {
    match: (pathname) =>
      (pathname.startsWith('/cases/') && pathname.endsWith('/evidence')) || pathname === '/evidence',
    page: {
      title: '근거 원문 대조',
      description: '왼쪽은 공고 원문, 오른쪽은 그 원문으로 내린 판정입니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토 › 근거 대조',
    },
  },
  {
    match: (pathname) =>
      (pathname.startsWith('/cases/') && pathname.endsWith('/evaluation')) ||
      pathname === '/evaluation',
    page: {
      title: '평가 대응',
      description: '배점 원문과 회사 프로필의 대응값을 나란히 확인합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토 › 평가 대응',
    },
  },
  {
    match: (pathname) =>
      (pathname.startsWith('/cases/') && pathname.endsWith('/changes')) || pathname === '/changes',
    page: {
      title: '변경 이력',
      description: '공고가 바뀐 곳과, 그 때문에 다시 판정한 항목을 보여줍니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토 › 변경 이력',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/company') || pathname.startsWith('/company-profile'),
    page: {
      title: '회사 프로필',
      description: '공고 판정에 사용하는 회사 값을 출처와 함께 관리합니다.',
      breadcrumb: '홈 › 회사 프로필',
    },
  },
];

function pageInfoFor(pathname: string): PageInfo {
  return PAGE_INFO.find(({ match }) => match(pathname))?.page ?? {
    title: '비드체크',
    description: '입찰 공고의 참가자격과 변경 영향을 근거와 함께 검토합니다.',
    breadcrumb: '홈 › 비드체크',
  };
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const page = pageInfoFor(pathname);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(pathname !== '/login');
  const [authFailure, setAuthFailure] = useState<string | null>(null);
  const [logoutFailure, setLogoutFailure] = useState<string | null>(null);
  const [authAttempt, setAuthAttempt] = useState(0);

  useEffect(() => {
    if (pathname === '/login') return;
    let active = true;
    void getCurrentUser()
      .then((current) => {
        if (active) setUser(current);
      })
      .catch((cause) => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) {
          window.sessionStorage.removeItem(LEGACY_ACTIVE_CASE_KEY);
          setUser(null);
          replaceWith('/login');
          return;
        }
        setAuthFailure(cause instanceof ApiError ? cause.message : NETWORK_ERROR_MESSAGE);
      })
      .finally(() => {
        if (active) setCheckingAuth(false);
      });
    return () => {
      active = false;
    };
  }, [authAttempt, pathname]);

  if (pathname === '/login') return children;

  if (checkingAuth) {
    return (
      <main className="grid min-h-screen place-items-center bg-[var(--product-tint)] text-sm text-[var(--product-muted)]">
        로그인 상태를 확인하고 있습니다.
      </main>
    );
  }

  if (authFailure) {
    return (
      <main className="grid min-h-screen place-items-center bg-[var(--product-tint)] px-5 text-center text-[var(--product-body)]">
        <div className="max-w-md rounded-2xl border border-red-200 bg-white p-7 shadow-sm">
          <h1 className="text-lg font-bold">로그인 상태를 확인하지 못했습니다.</h1>
          <p className="mt-3 text-sm leading-6 text-[var(--product-muted)]">{authFailure}</p>
          <button
            type="button"
            className="mt-5 rounded-lg bg-[var(--product-accent)] px-4 py-2 text-sm font-semibold text-white"
            onClick={() => {
              setAuthFailure(null);
              setCheckingAuth(true);
              setAuthAttempt((attempt) => attempt + 1);
            }}
          >
            다시 시도
          </button>
        </div>
      </main>
    );
  }

  async function handleLogout() {
    setLogoutFailure(null);
    try {
      await logout();
      window.sessionStorage.removeItem(LEGACY_ACTIVE_CASE_KEY);
      setUser(null);
      replaceWith('/login');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        window.sessionStorage.removeItem(LEGACY_ACTIVE_CASE_KEY);
        setUser(null);
        replaceWith('/login');
        return;
      }
      setLogoutFailure(cause instanceof ApiError ? cause.message : NETWORK_ERROR_MESSAGE);
    }
  }

  // 화면이 자체 <header>를 그리는 라우트. 셸 헤더와 겹쳐서 product.css가 숨긴다.
  const legacyRouteClass =
    pathname === '/workbench'
      ? 'app-shell-route-workbench'
      : pathname === '/qualification'
        ? 'app-shell-route-qualification'
        : '';

  return (
    <CopilotProvider>
      <div className="app-shell min-h-screen bg-[var(--product-tint)] text-[var(--product-body)]">
        <AppHeader pathname={pathname} user={user} onLogout={() => void handleLogout()} />
        {logoutFailure && (
          <div role="alert" className="border-b border-red-200 bg-red-50 px-5 py-3 text-center text-sm text-red-700">
            로그아웃을 완료하지 못했습니다. {logoutFailure}
          </div>
        )}
        {page.showTitleBand !== false && (
          <TitleBand
            title={page.title}
            description={page.description}
            breadcrumb={page.breadcrumb}
            variant={page.variant}
          />
        )}
        <div className={`app-shell-content ${legacyRouteClass}`}>{children}</div>
        <AppFooter />
        <CopilotPanel />
      </div>
    </CopilotProvider>
  );
}
