import type { ReactNode } from 'react';

// 수행 실적·인증 관리는 회사 프로필 페이지가 직접 원하는 자리에 렌더한다.
// 예전에는 이 레이아웃이 children 뒤에 붙였는데, 그러면 화면 순서를 페이지에서 정할 수 없고
// 레이아웃이 회사 목록을 한 번 더 조회해 페이지가 고른 회사와 어긋날 수 있었다.
export default function CompanyLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
