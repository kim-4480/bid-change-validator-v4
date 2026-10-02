import type { ReactNode } from 'react';

/*
  「회사 기준으로 판정 가능한 공고」는 이 레이아웃에서 children 뒤에 붙어 있었다.
  그래서 화면 맨 아래, 목록·공지사항·프로필 유도까지 다 지나야 닿았다.
  이 제품이 나라장터와 다른 점이 바로 그 섹션이라 page.tsx 위쪽으로 옮겼다.
*/
export default function NoticesLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
