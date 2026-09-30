import { redirect } from 'next/navigation';

/**
 * 루트는 홈(공고 찾기)으로 보낸다.
 *
 * 여기에는 9/6까지 쓰던 3분할 점검 화면이 있었다. 헤더 로고는 /notices로 가는데
 * 주소창에 루트를 직접 치면 그 옛 화면이 떠서, 처음 들어온 사람이 현재 제품과
 * 다른 화면을 보게 됐다. 옛 화면은 지우지 않고 /workbench로 옮겼다.
 */
export default function RootPage() {
  redirect('/notices');
}
