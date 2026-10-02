'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Building2,
  Check,
  FileBadge2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';

import { ProfileRecordsManager } from '@/components/product/profile-records-manager';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { COMPANY_SIZE_LABEL, REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import {
  createCompany,
  listCompanies,
  searchIndustryCodes,
  updateCompany,
  type CompanyCreatePayload,
  type CompanyProfile,
  type CompanySize,
  type MasterCode,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'industry' | 'basics' | null;

type CompanyBasics = {
  region_code: string;
  region_name: string;
  company_size: CompanySize;
  staff_total: string;
};

function basicsOf(company: CompanyProfile): CompanyBasics {
  return {
    region_code: company.region_code ?? '',
    region_name: company.region_name ?? '',
    company_size: company.company_size,
    // 인력 정보가 아예 없는 회사와 0명인 회사는 다르다. 없으면 빈 칸으로 두고 저장할 때만 보낸다.
    staff_total: company.staff ? String(company.staff.total_count) : '',
  };
}

function companyRows(company: CompanyProfile) {
  const performanceTotal = company.performances.reduce((sum, item) => sum + item.amount, 0);
  return [
    {
      label: '업종 코드',
      form: '#industry-manager' as string | null,
      value: company.industries.length
        ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.industries.length ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'INDUSTRY',
    },
    {
      label: '소재지',
      form: '#company-basics' as string | null,
      value: company.region_name || company.region_code || '비어 있음 · 판정하지 않습니다',
      source: company.region_name || company.region_code ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'REGION',
    },
    {
      label: '기업 구분',
      form: '#company-basics' as string | null,
      value: COMPANY_SIZE_LABEL[company.company_size],
      source: '회사 입력',
      updated: company.updated_at,
      use: 'COMPANY_SIZE',
    },
    {
      label: '상시 근로자 수',
      form: '#company-basics' as string | null,
      value: company.staff ? `${company.staff.total_count.toLocaleString()}명` : '비어 있음 · 판정하지 않습니다',
      source: company.staff ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'STAFF',
    },
    {
      label: '최근 수행 실적 건수',
      form: '#profile-performance',
      // 「0건」은 회사가 신고한 사실이 아니라 우리가 아직 받지 못했다는 뜻이다.
      value: company.performances.length ? `${company.performances.length}건` : '비어 있음 · 판정하지 않습니다',
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_COUNT',
    },
    {
      label: '최근 수행 실적 금액',
      form: '#profile-performance',
      value: company.performances.length ? `합계 ${performanceTotal.toLocaleString()}원` : '비어 있음 · 판정하지 않습니다',
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_AMOUNT',
    },
    {
      label: '인증 · 등록',
      form: '#profile-certification',
      value: company.certifications.length
        ? company.certifications.map((item) => item.name).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.certifications.length ? '회사 입력' : '없음',
      updated: company.certifications[0]?.updated_at ?? company.updated_at,
      use: 'REGISTRATION_CERTIFICATION',
    },
  ];
}

export default function CompanyPage() {
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState<Busy>('load');
  const [error, setError] = useState('');
  const [industryQuery, setIndustryQuery] = useState('');
  const [industryOptions, setIndustryOptions] = useState<MasterCode[]>([]);
  const [selectedIndustry, setSelectedIndustry] = useState('');
  // 저장 전 업종 목록. null이면 「서버 값 그대로」라는 뜻이고, 배열이면 편집 중이다.
  const [industryDraft, setIndustryDraft] = useState<Array<{ code: string; name: string }> | null>(null);
  // 소재지·기업 구분·상시 근로자. 업종과 같은 규칙 — null이면 「서버 값 그대로」다.
  const [basicsDraft, setBasicsDraft] = useState<CompanyBasics | null>(null);
  const [form, setForm] = useState({
    name: '',
    business_registration_number: '',
    region_code: '11',
    region_name: '서울특별시',
    company_size: 'SMALL' as CompanySize,
    staff_total: '8',
    developer_count: '5',
  });

  const company = useMemo(
    () => companies.find((item) => item.id === selectedId) ?? companies[0] ?? null,
    [companies, selectedId],
  );

  const rows = company ? companyRows(company) : [];
  const filledRows = rows.filter((row) => !row.value.startsWith('비어 있음')).length;
  const missingRows = rows.filter((row) => row.value.startsWith('비어 있음'));

  const savedIndustries = company?.industries.map(({ code, name }) => ({ code, name })) ?? [];
  const industryList = industryDraft ?? savedIndustries;
  // 백엔드가 코드 오름차순으로 돌려주므로, 넣은 순서가 달라도 같은 집합이면 변경이 아니다.
  const industryDirty =
    industryDraft !== null &&
    industryList.map((item) => item.code).sort().join('|') !==
      savedIndustries.map((item) => item.code).sort().join('|');

  function addIndustry(item: MasterCode) {
    setIndustryDraft((draft) => {
      const base = draft ?? savedIndustries;
      if (base.some((row) => row.code === item.code)) return base;
      return [...base, { code: item.code, name: item.name }];
    });
  }

  function removeIndustry(code: string) {
    setIndustryDraft((draft) => (draft ?? savedIndustries).filter((row) => row.code !== code));
  }

  const savedBasics = company ? basicsOf(company) : null;
  const basics = basicsDraft ?? savedBasics;
  const basicsDirty =
    basicsDraft !== null && savedBasics !== null &&
    JSON.stringify(basicsDraft) !== JSON.stringify(savedBasics);

  function editBasics(patch: Partial<CompanyBasics>) {
    // savedBasics 가 없으면 아직 회사를 못 불러온 상태다. 그때는 편집 UI 자체가 안 뜬다.
    if (!savedBasics) return;
    setBasicsDraft((draft) => ({ ...(draft ?? savedBasics), ...patch }));
  }

  /*
    백엔드 PATCH /companies/{id} 가 받아주지 않는 상태를 저장 전에 막는다.
    누르고 나서 422를 보여주는 것보다, 누르기 전에 왜 안 되는지 말하는 편이 낫다.

    - industry_codes: []        → 스키마가 거부한다 (at least one code)
    - region_code: ''           → 스키마가 거부한다 (must not be blank)
    - 이미 저장된 staff·region_name 을 비우면  → 그 키가 payload 에서 빠져 기존 값이 그대로 남는다.
      즉 화면에서는 지운 것처럼 보이지만 실제로는 안 지워진다. 「지울 수 있다」고 보이게 두면 거짓말이 된다.
      값을 실제로 비우려면 백엔드에 「삭제」 의미가 따로 필요해서 이번 범위 밖이다.
  */
  const industryBlock =
    industryList.length === 0 ? '업종은 최소 1개가 필요합니다. 하나는 남겨 주세요.' : null;

  const basicsBlock = (() => {
    if (!basics || !savedBasics) return null;
    if (!basics.region_code.trim()) return '지역 코드는 비울 수 없습니다. 값을 바꾸려면 새 코드를 입력해 주세요.';
    if (savedBasics.region_name.trim() && !basics.region_name.trim()) {
      return '이미 저장된 소재지는 화면에서 지울 수 없습니다. 다른 지역명으로 바꾸는 것은 됩니다.';
    }
    if (savedBasics.staff_total.trim() && !basics.staff_total.trim()) {
      return '이미 저장된 상시 근로자 수는 화면에서 지울 수 없습니다. 다른 인원으로 바꾸는 것은 됩니다.';
    }
    return null;
  })();

  async function saveBasics() {
    if (!company || !basics || basicsBlock) return;
    setBusy('basics');
    setError('');
    try {
      const payload: Partial<CompanyCreatePayload> = {
        region_code: basics.region_code.trim(),
        region_name: basics.region_name.trim() || undefined,
        company_size: basics.company_size,
      };
      // 빈 칸이면 인력 정보를 건드리지 않는다. 0으로 덮으면 「0명임을 확인했다」가 되어 판정이 달라진다.
      if (basics.staff_total.trim()) {
        payload.staff = {
          total_count: Number(basics.staff_total),
          verified: company.staff?.verified ?? false,
          roles: company.staff?.roles ?? [],
        };
      }
      await updateCompany(company.id, payload);
      const refreshed = await listCompanies();
      setCompanies(refreshed);
      setBasicsDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 정보 저장에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function saveIndustries() {
    if (!company || industryBlock) return;
    setBusy('industry');
    setError('');
    try {
      await updateCompany(company.id, { industry_codes: industryList.map((item) => item.code) });
      const refreshed = await listCompanies();
      setCompanies(refreshed);
      setIndustryDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '업종 저장에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function initialize() {
    setBusy('load');
    setError('');
    try {
      const [companyItems, industryResult] = await Promise.all([
        listCompanies(),
        searchIndustryCodes(),
      ]);
      setCompanies(companyItems);
      if (companyItems[0]) setSelectedId((value) => value || companyItems[0].id);
      setIndustryOptions(industryResult.items);
      setSelectedIndustry((value) => value || industryResult.items[0]?.code || '');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필을 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  // 다른 회사로 바꾸면 저장 안 한 편집은 버린다. 다른 회사에 잘못 저장되는 것보다 낫다.
  // react-compiler는 effect 안의 setState를 경고하지만, 여기서는 매 렌더가 아니라
  // company.id가 바뀔 때만 한 번 돈다. 초안을 회사 id로 들고 다니게 바꾸면 규칙을
  // 끄지 않아도 되는데, 그건 저장 경로 전체를 건드려야 해서 발표 뒤로 미룬다.
  useEffect(() => {
    // eslint-disable-next-line react/react-compiler
    setIndustryDraft(null);
    setBasicsDraft(null);
  }, [company?.id]);

  async function searchIndustries() {
    try {
      const result = await searchIndustryCodes(industryQuery);
      setIndustryOptions(result.items);
      if (result.items[0]) setSelectedIndustry(result.items[0].code);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '업종 검색에 실패했습니다.');
    }
  }

  async function submitCompany() {
    if (!selectedIndustry) {
      setError('업종 코드를 선택해주세요.');
      return;
    }
    setBusy('create');
    setError('');
    try {
      const payload: CompanyCreatePayload = {
        name: form.name,
        business_registration_number: form.business_registration_number || undefined,
        region_code: form.region_code,
        region_name: form.region_name || undefined,
        company_size: form.company_size,
        industry_codes: [selectedIndustry],
        staff: {
          total_count: Number(form.staff_total || 0),
          verified: false,
          roles: [
            {
              role_name: '개발자',
              headcount: Number(form.developer_count || 0),
              verified: false,
            },
          ],
        },
      };
      const created = await createCompany(payload);
      const refreshed = await listCompanies();
      setCompanies(refreshed);
      setSelectedId(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10 md:py-12">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!company ? (
          <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
            <div className="rounded-[24px] border border-[var(--product-line)] bg-white p-8 shadow-[0_12px_35px_rgba(35,50,90,0.06)]">
              <Badge className="bg-[#eef1ff] text-[var(--product-accent-deep)]">회사 프로필 생성</Badge>
              <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em] text-[var(--product-ink)]">판정을 시작하려면 회사 프로필이 필요합니다</h1>
              <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--product-muted)]">
                업종, 지역, 기업 규모, 인력 정보를 먼저 저장하면 공고 참가자격 판정에서 실제 비교값으로 사용합니다.
              </p>

              <div className="mt-8 grid gap-5 sm:grid-cols-2">
                <label className="text-sm font-medium" htmlFor="company-name">회사명<Input id="company-name" className="mt-2" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="예: 그린브릿지 글로벌 주식회사" /></label>
                <label className="text-sm font-medium" htmlFor="company-brn">사업자등록번호<Input id="company-brn" className="mt-2" value={form.business_registration_number} onChange={(event) => setForm({ ...form, business_registration_number: event.target.value })} placeholder="10자리 숫자" /></label>
                <label className="text-sm font-medium" htmlFor="company-region-code">지역 코드<Input id="company-region-code" className="mt-2" value={form.region_code} onChange={(event) => setForm({ ...form, region_code: event.target.value })} /></label>
                <label className="text-sm font-medium" htmlFor="company-region-name">소재지<Input id="company-region-name" className="mt-2" value={form.region_name} onChange={(event) => setForm({ ...form, region_name: event.target.value })} /></label>
                <label className="text-sm font-medium" htmlFor="company-staff-total">전체 인원<Input id="company-staff-total" className="mt-2" type="number" min="0" value={form.staff_total} onChange={(event) => setForm({ ...form, staff_total: event.target.value })} /></label>
                <label className="text-sm font-medium" htmlFor="company-developer-count">개발자 인원<Input id="company-developer-count" className="mt-2" type="number" min="0" value={form.developer_count} onChange={(event) => setForm({ ...form, developer_count: event.target.value })} /></label>
              </div>

              <div className="mt-6">
                <span className="text-sm font-medium">업종</span>
                <div className="mt-2 flex gap-2">
                  <Input value={industryQuery} onChange={(event) => setIndustryQuery(event.target.value)} placeholder="업종명 또는 코드 검색" />
                  <Button variant="outline" onClick={() => void searchIndustries()}><Search />검색</Button>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {industryOptions.slice(0, 6).map((item) => (
                    <button key={item.code} type="button" onClick={() => setSelectedIndustry(item.code)} className={`rounded-xl border px-4 py-3 text-left text-sm ${selectedIndustry === item.code ? 'border-[var(--product-accent)] bg-[#f3f5ff]' : 'border-[var(--product-line)]'}`}>
                      <strong>{item.code}</strong><span className="ml-2 text-[var(--product-muted)]">{item.name}</span>
                    </button>
                  ))}
                </div>
              </div>

              <Button className="mt-8 rounded-full px-6" onClick={() => void submitCompany()} disabled={!form.name.trim() || busy !== null}>
                {busy === 'create' ? <LoaderCircle className="animate-spin" /> : <Plus />}
                회사 프로필 만들기
              </Button>
            </div>

            <aside className="rounded-[24px] bg-[var(--product-accent-deep)] p-8 text-white">
              <Building2 className="size-9 text-white/80" />
              <h2 className="mt-6 text-[28px] font-extrabold">프로필 값이 판정 근거가 됩니다</h2>
              <div className="mt-7 space-y-4 text-sm text-white/78">
                <p>업종 → 공고의 업종 제한과 대조합니다</p>
                <p>지역 → 참가 가능 지역과 대조합니다</p>
                <p>기업 규모 → 기업 구분 제한과 대조합니다</p>
                <p>인력 → 상시 인력·전담 인력 요건과 대조합니다</p>
                <p>수행 실적 → 실적 건수·금액 요건과 대조합니다</p>
                <p>인증·등록 → 요구하는 면허·인증 보유 여부와 대조합니다</p>
              </div>
            </aside>
          </section>
        ) : (
          <>
            <section className="rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
              <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
                <div>
                  <h1 className="text-[28px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">{rows.length}개 영역 중 {filledRows}개를 채웠습니다</h1>
                  <p className="mt-2 text-[14px] text-[var(--product-muted)]">비어 있는 값은 미달로 만들지 않고 확인 필요로 남깁니다.</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{company.name}</Badge>
                  <Button variant="outline" size="sm" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw className={busy === 'load' ? 'animate-spin' : ''} />새로고침</Button>
                </div>
              </div>
            </section>

            {missingRows.length > 0 && (
              <section className="mt-5 rounded-[22px] border border-[#e2d9a9] bg-[#fffaf0] p-6">
                <div className="flex items-center gap-2"><FileBadge2 className="size-5 text-amber-700" /><h2 className="text-[20px] font-bold">비어 있는 항목 {missingRows.length}건</h2></div>
                <div className="mt-4 divide-y divide-[#eee3bd]">
                  {missingRows.map((row) => <div key={row.label} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"><div><strong>{row.label}</strong><p className="mt-1 text-sm text-[var(--product-muted)]">이 값을 요구하는 공고는 확인 필요로 남습니다.</p></div><div className="flex shrink-0 items-center gap-2"><Badge className="bg-amber-100 text-amber-800">확인 필요</Badge>{/* 경고만 하고 끝내지 않는다. 이 화면 안에 입력 폼이 있는 항목은 거기로 바로 보낸다. */}
                    {row.form && <a href={row.form} className="rounded-full border border-amber-300 bg-white px-3 py-1.5 text-[13px] font-semibold text-amber-800 hover:bg-amber-50">입력하러 가기 →</a>}</div></div>)}
                </div>
              </section>
            )}

            <section id="industry-manager" className="mt-7 rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[22px] font-extrabold tracking-[-0.03em]">업종 코드</h2>
                  <p className="mt-1 text-[13px] text-[var(--product-muted)]">공고의 업종 제한과 대조하는 값입니다. 여러 개를 등록할 수 있습니다.</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {industryDirty && (
                    <Button variant="outline" size="sm" className="rounded-full" onClick={() => setIndustryDraft(null)} disabled={busy !== null}>되돌리기</Button>
                  )}
                  <Button size="sm" className="rounded-full" onClick={() => void saveIndustries()} disabled={!industryDirty || industryBlock !== null || busy !== null}>
                    {busy === 'industry' ? <LoaderCircle className="animate-spin" /> : <Check />}
                    업종 저장
                  </Button>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-2">
                {industryList.length ? (
                  industryList.map((item) => (
                    <span key={item.code} className="inline-flex items-center gap-2 rounded-full border border-[var(--product-line)] bg-[#f3f5ff] py-1.5 pl-3 pr-1.5 text-[13px]">
                      <strong>{item.code}</strong>
                      <span className="text-[var(--product-muted)]">{item.name}</span>
                      <button type="button" aria-label={`${item.name} 제거`} onClick={() => removeIndustry(item.code)} disabled={industryList.length <= 1} title={industryList.length <= 1 ? '업종은 최소 1개가 필요합니다' : undefined} className="rounded-full p-1 text-[var(--product-muted)] transition-colors hover:bg-white hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent disabled:hover:text-[var(--product-muted)]">
                        <X className="size-3.5" />
                      </button>
                    </span>
                  ))
                ) : (
                  <p className="text-[13px] text-amber-700">등록된 업종이 없습니다. 업종을 요구하는 공고는 「확인 필요」로 남습니다. 저장하려면 업종을 하나 이상 추가해 주세요.</p>
                )}
              </div>

              <div className="mt-5 flex gap-2">
                <Input
                  value={industryQuery}
                  onChange={(event) => setIndustryQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void searchIndustries();
                  }}
                  placeholder="업종명 또는 코드 검색"
                />
                <Button variant="outline" onClick={() => void searchIndustries()}><Search />검색</Button>
              </div>

              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {industryOptions.slice(0, 6).map((item) => {
                  const added = industryList.some((row) => row.code === item.code);
                  return (
                    <button
                      key={item.code}
                      type="button"
                      disabled={added}
                      onClick={() => addIndustry(item)}
                      className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors ${added ? 'cursor-default border-[var(--product-line-2)] bg-[var(--product-tint)] text-[var(--product-muted)]' : 'border-[var(--product-line)] hover:border-[var(--product-accent)]'}`}
                    >
                      <span className="min-w-0"><strong>{item.code}</strong><span className="ml-2 text-[var(--product-muted)]">{item.name}</span></span>
                      {added ? <span className="shrink-0 text-[12px] font-semibold">등록됨</span> : <Plus className="size-4 shrink-0" />}
                    </button>
                  );
                })}
              </div>

              {industryBlock ? (
                <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[13px] leading-[1.7] text-rose-800">{industryBlock}</p>
              ) : industryDirty ? (
                <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-[13px] leading-[1.7] text-amber-800">
                  저장하지 않은 변경이 있습니다. 「업종 저장」을 눌러야 판정에 반영됩니다.
                </p>
              ) : null}
            </section>

            {basics && (
              <section id="company-basics" className="mt-7 scroll-mt-24 rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[22px] font-extrabold tracking-[-0.03em]">회사 기본 정보</h2>
                    <p className="mt-1 text-[13px] text-[var(--product-muted)]">소재지 제한 · 기업 구분 제한 · 인력 요건 판정에 쓰는 값입니다.</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {basicsDirty && (
                      <Button variant="outline" size="sm" className="rounded-full" onClick={() => setBasicsDraft(null)} disabled={busy !== null}>되돌리기</Button>
                    )}
                    <Button size="sm" className="rounded-full" onClick={() => void saveBasics()} disabled={!basicsDirty || basicsBlock !== null || busy !== null}>
                      {busy === 'basics' ? <LoaderCircle className="animate-spin" /> : <Check />}
                      정보 저장
                    </Button>
                  </div>
                </div>

                <div className="mt-5 grid gap-5 sm:grid-cols-2">
                  <label className="text-sm font-medium" htmlFor="basics-region-name">
                    소재지
                    <Input id="basics-region-name" className="mt-2" value={basics.region_name} onChange={(event) => editBasics({ region_name: event.target.value })} placeholder="예: 전북특별자치도" />
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-region-code">
                    지역 코드
                    <Input id="basics-region-code" className="mt-2" value={basics.region_code} onChange={(event) => editBasics({ region_code: event.target.value })} placeholder="예: 52" />
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-company-size">
                    기업 구분
                    <select
                      id="basics-company-size"
                      className="mt-2 h-9 w-full rounded-md border border-[var(--product-line)] bg-white px-3 text-sm"
                      value={basics.company_size}
                      onChange={(event) => editBasics({ company_size: event.target.value as CompanySize })}
                    >
                      {(Object.keys(COMPANY_SIZE_LABEL) as CompanySize[]).map((size) => (
                        <option key={size} value={size}>{COMPANY_SIZE_LABEL[size]}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-staff-total">
                    상시 근로자 수
                    <Input id="basics-staff-total" className="mt-2" type="number" min="0" value={basics.staff_total} onChange={(event) => editBasics({ staff_total: event.target.value })} placeholder="입력하지 않으면 「확인 필요」로 남습니다" />
                  </label>
                </div>

                {company.staff?.roles.length ? (
                  <p className="mt-4 text-[13px] text-[var(--product-muted)]">
                    역할별 인원 — {company.staff.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(' · ')}
                    <span className="ml-2 text-[12px]">(역할 편집은 아직 지원하지 않습니다)</span>
                  </p>
                ) : null}

                {basicsBlock ? (
                  <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[13px] leading-[1.7] text-rose-800">{basicsBlock}</p>
                ) : basicsDirty ? (
                  <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-[13px] leading-[1.7] text-amber-800">
                    저장하지 않은 변경이 있습니다. 「정보 저장」을 눌러야 판정에 반영됩니다.
                  </p>
                ) : null}
              </section>
            )}

            <ProfileRecordsManager company={company} onChanged={() => void initialize()} />

            <section className="mt-7">
              <div className="flex items-center gap-3"><h2 className="text-[27px] font-extrabold tracking-[-0.035em]">프로필 항목</h2><span className="text-[14px] text-[var(--product-muted)]">판정에 실제로 들어가는 값입니다</span></div>
              <div className="mt-4 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
                <div className="grid grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] bg-[var(--product-tint)] px-4 py-3 text-[12px] font-bold text-[var(--product-muted)]"><span>항목</span><span>값</span><span>출처</span><span>갱신일</span><span>이 값을 쓰는 곳</span></div>
                {rows.map((row) => (
                  <div key={row.label} className="grid grid-cols-1 gap-2 border-t border-[var(--product-line-2)] px-4 py-4 text-sm md:grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] md:items-center">
                    <strong>{row.label}</strong>
                    <span className={row.value.startsWith('비어 있음') ? 'text-amber-700' : ''}>{row.value}</span>
                    <span><Badge variant="outline">{row.source}</Badge></span>
                    <span>{new Date(row.updated).toLocaleDateString('ko-KR')}</span>
                    <span className="text-[12px] font-semibold text-[var(--product-accent-deep)]">{labelOf(REQUIREMENT_TYPE_LABEL, row.use)}</span>
                  </div>
                ))}
              </div>
            </section>

          </>
        )}
      </div>
    </main>
  );
}
