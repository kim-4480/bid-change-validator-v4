/**
 * 이용안내 `/guide`
 *
 * 세로 리듬을 한 벌로 고정한다. 이전 버전은 같은 15px 본문인데 어떤 줄은 leading-6,
 * 어떤 줄은 기본값(1.5)이라 카드마다 줄간격이 달라 보였다.
 *
 *   28px / leading-[1.35]   페이지 제목
 *   21px / leading-[1.4]    섹션 제목
 *   18px / leading-[1.45]   항목 제목
 *   15px / leading-[1.75]   본문      ← 한글은 26px는 줘야 두 줄 이상이 안 붙는다
 *   13px / leading-[1.7]    보조
 *
 * 섹션 간격 mt-14, 제목에서 내용 mt-5, 제목에서 본문 mt-2로 통일한다.
 * 모서리는 카드 20px, 강조 블록 24px, 버튼 pill 하나로 고정.
 * 상호작용이 없으므로 클라이언트 컴포넌트로 만들지 않는다.
 */

import { ArrowRight, CheckCircle2, CircleHelp, FileCheck2, XCircle } from 'lucide-react';

import { NavigationLink } from '@/components/navigation-link';
import { buttonVariants } from '@/components/ui/button';
import { OVERALL_STATUS_BADGE } from '@/lib/status-copy';

const STEPS = [
  {
    n: '1',
    title: '공고를 찾습니다',
    body: '공고번호나 공고명으로 검색합니다. 회사 프로필 기준으로 판정이 끝난 공고는 따로 모아 보여줍니다.',
  },
  {
    n: '2',
    title: '참가 자격을 판정합니다',
    body: '공고 원문에서 자격조건을 뽑아 회사 프로필과 대조합니다. 판정마다 근거가 된 공고 문장을 함께 봅니다.',
  },
  {
    n: '3',
    title: '변경공고를 다시 검증합니다',
    body: '공고가 바뀌면 무엇이 달라졌는지 원문끼리 비교합니다. 영향받는 자격조건만 다시 판정합니다.',
  },
];

/*
  화면을 한 줄씩 나열하면 여덟 줄짜리 표가 된다. 표는 훑어도 어디부터 봐야 할지 안 보인다.
  「언제 쓰는가」로 묶으면 묶음 제목이 그 답을 대신한다.
*/
const SCREEN_GROUPS = [
  {
    when: '공고를 고를 때',
    items: [
      { name: '공고 찾기', href: '/notices', body: '공고를 검색하고 판정 상태로 거릅니다', note: null },
    ],
  },
  {
    when: '자격을 확인할 때',
    items: [
      { name: '참가자격 검토', href: '/qualification', body: '요건별 판정과 근거 문장을 봅니다', note: null },
      { name: '확인 필요', href: null, body: '판정하지 못한 항목에 답하면 그 줄만 다시 판정합니다', note: '검토 건에서 이동' },
      { name: '근거 원문', href: null, body: '판정과 공고 원문을 나란히 놓고 봅니다', note: '검토 건에서 이동' },
    ],
  },
  {
    when: '제출을 준비할 때',
    items: [
      { name: '평가 대응', href: null, body: '공고가 요구한 항목이 제안서 어디에 있는지 찾아줍니다', note: '검토 건에서 이동' },
      { name: '변경 이력', href: null, body: '차수별 변경과 자격에 미친 영향을 봅니다', note: '검토 건에서 이동' },
      { name: '회사 프로필', href: '/company', body: '판정에 쓰는 회사 정보를 관리합니다', note: null },
      { name: '서류함', href: null, body: '준비 중입니다', note: '준비 중' },
    ],
  },
];

/* 라벨과 색은 공통 맵에서 가져온다. 여기에 문구를 또 적으면 화면마다 다른 이름이 된다 (#138 리뷰). */
const BADGES = [
  { key: 'eligible', icon: CheckCircle2, body: '판정한 필수 항목에서 미달이 없습니다.' },
  { key: 'insufficient_data', icon: CircleHelp, body: '회사 정보가 없거나 근거를 찾지 못해 판정하지 않았습니다.' },
  { key: 'ineligible', icon: XCircle, body: '미달 항목이 있어 지금 상태로는 참가할 수 없습니다.' },
  { key: 'unreviewed', icon: FileCheck2, body: '아직 검토를 시작하지 않은 공고입니다.' },
] as const;

const LIMITS = [
  { title: '근거가 없으면 판정하지 않습니다', body: '억지로 결론을 내지 않고 「확인 필요」로 남깁니다.' },
  { title: '평가 점수를 예측하지 않습니다', body: '제안서에서 관련 위치만 찾아주고, 다뤘는지는 직접 판단하십시오.' },
  { title: '표준값이 없는 계약조항은 표시하지 않습니다', body: '확실하지 않은 값을 「표준」이라고 부르지 않습니다.' },
  { title: '최종 판단은 사용자 몫입니다', body: '제출 전에 공고 원문을 다시 확인해 주세요.' },
];

export default function GuidePage() {
  return (
    <main className="bg-white text-[var(--product-body)]">
      <section className="border-b border-[var(--product-line)] bg-[linear-gradient(120deg,#e6eeff_0%,#f0ebff_48%,#e8f4ff_100%)]">
        <div className="app-shell-container py-12">
          <h1 className="text-[28px] font-extrabold leading-[1.35] tracking-[-0.04em] text-[var(--product-ink)]">이용안내</h1>
          <p className="mt-2 max-w-[52ch] text-[15px] leading-[1.75] text-[var(--product-muted)]">공고를 찾아 참가 자격을 확인하고, 공고가 바뀌면 다시 검증합니다.</p>
        </div>
      </section>

      <div className="app-shell-container pb-24 pt-12">
        {/*
          세 단계. 가로 카드 셋으로 늘어놓으면 읽는 순서가 안 보인다.
          번호를 왼쪽 기둥으로 세우고 세로로 쌓으면 눈이 1에서 3으로 자연히 내려간다.
        */}
        <section>
          <h2 className="text-[21px] font-extrabold leading-[1.4] tracking-[-0.03em] text-[var(--product-ink)]">처음이라면 이 순서로</h2>

          <ol className="mt-5 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
            {STEPS.map(({ n, title, body }) => (
              <li key={n} className="grid grid-cols-[52px_minmax(0,1fr)] gap-x-5 border-t border-[var(--product-line-2)] px-6 py-6 first:border-t-0 sm:grid-cols-[72px_minmax(0,1fr)] sm:px-8">
                <span className="text-[32px] font-extrabold leading-[1.2] tracking-[-0.04em] text-[var(--product-accent)] sm:text-[40px]">{n}</span>
                <div className="min-w-0">
                  <h3 className="text-[18px] font-extrabold leading-[1.45] text-[var(--product-ink)]">{title}</h3>
                  <p className="mt-2 max-w-[60ch] text-[15px] leading-[1.75] text-[var(--product-body)]">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* 실제로 사람이 막히는 지점은 기능을 몰라서가 아니라 프로필이 비어서다. 그래서 흐름 바로 뒤에 둔다. */}
        <section className="mt-14 rounded-[24px] border border-[#d9ddf8] bg-[#f2f4ff] px-7 py-7 sm:px-9">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <h2 className="text-[21px] font-extrabold leading-[1.4] tracking-[-0.03em] text-[var(--product-ink)]">판정이 비어 있다면 프로필부터 보세요</h2>
              <p className="mt-2 max-w-[58ch] text-[15px] leading-[1.75] text-[var(--product-muted)]">대조할 회사 정보가 없으면 판정 결과가 나오지 않습니다. 채워진 정도는 공고 찾기 화면 맨 위에 표시됩니다.</p>
              <p className="mt-2 max-w-[58ch] text-[15px] leading-[1.75] text-[var(--product-muted)]">실적이나 인증처럼 공고마다 달라지는 값은 미리 받지 않고, 판정 중에 필요해지면 그때 묻습니다.</p>
            </div>
            <NavigationLink href="/company" className={buttonVariants({ variant: 'outline', className: 'shrink-0 rounded-full border-[var(--product-accent)] bg-white px-5 text-[var(--product-accent-deep)]' })}>회사 프로필 열기 <ArrowRight /></NavigationLink>
          </div>
        </section>

        {/* 묶음 사이에만 선을 긋는다. 줄마다 선을 그으면 여덟 줄짜리 표가 되고, 표는 훑을 수가 없다. */}
        <section className="mt-14">
          <h2 className="text-[21px] font-extrabold leading-[1.4] tracking-[-0.03em] text-[var(--product-ink)]">화면별로 하는 일</h2>

          <div className="mt-5 space-y-8">
            {SCREEN_GROUPS.map(({ when, items }) => (
              <div key={when} className="border-t border-[var(--product-line)] pt-6">
                <h3 className="text-[13px] font-bold leading-[1.7] text-[var(--product-muted)]">{when}</h3>
                <dl className="mt-3 space-y-3">
                  {items.map(({ name, href, body, note }) => (
                    <div key={name} className="grid gap-x-5 gap-y-0.5 sm:grid-cols-[168px_minmax(0,1fr)]">
                      <dt className="text-[15px] font-bold leading-[1.75]">
                        {href
                          ? <NavigationLink href={href} className="text-[var(--product-accent-deep)] hover:underline">{name}</NavigationLink>
                          : <span className="text-[var(--product-ink)]">{name}</span>}
                      </dt>
                      <dd className="max-w-[58ch] text-[15px] leading-[1.75] text-[var(--product-body)]">
                        {body}
                        {/* 검토 건이 있어야 열리는 화면은 링크를 걸지 않는다. 주소로 바로 들어가면 「caseId가 필요합니다」가 뜬다. */}
                        {note && <span className="ml-2 whitespace-nowrap rounded-full bg-[var(--product-tint)] px-2.5 py-0.5 text-[13px] text-[var(--product-muted)]">{note}</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </section>

        {/* 배지는 색과 모양이 곧 정보라 실제 배지를 그대로 보여준다. 이름만 적으면 화면에서 못 알아본다. */}
        <section className="mt-14">
          <h2 className="text-[21px] font-extrabold leading-[1.4] tracking-[-0.03em] text-[var(--product-ink)]">공고 목록의 판정 표시</h2>

          <dl className="mt-5 space-y-4">
            {BADGES.map(({ key, icon: Icon, body }) => (
              <div key={key} className="grid gap-x-5 gap-y-1.5 sm:grid-cols-[136px_minmax(0,1fr)] sm:items-baseline">
                <dt>
                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-bold leading-[1.7] ${OVERALL_STATUS_BADGE[key].className}`}><Icon className="size-4" />{OVERALL_STATUS_BADGE[key].label}</span>
                </dt>
                <dd className="max-w-[58ch] text-[15px] leading-[1.75] text-[var(--product-muted)]">{body}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* 안 하는 것을 적는 게 하는 것을 적는 것만큼 중요하다. 기대를 잘못 세우면 판정을 못 믿는다. */}
        <section className="mt-14 rounded-[24px] bg-[var(--product-accent-deep)] px-7 py-8 text-white sm:px-9">
          <h2 className="text-[21px] font-extrabold leading-[1.4] tracking-[-0.03em]">이 서비스가 하지 않는 것</h2>

          <dl className="mt-6 grid gap-x-10 gap-y-6 md:grid-cols-2">
            {LIMITS.map(({ title, body }) => (
              <div key={title}>
                <dt className="text-[15px] font-bold leading-[1.6]">{title}</dt>
                <dd className="mt-1.5 max-w-[46ch] text-[15px] leading-[1.75] text-white/75">{body}</dd>
              </div>
            ))}
          </dl>
        </section>

        <div className="mt-12 flex justify-center">
          <NavigationLink href="/notices" className={buttonVariants({ className: 'rounded-full px-6' })}>공고 찾기로 가기 <ArrowRight /></NavigationLink>
        </div>
      </div>
    </main>
  );
}
