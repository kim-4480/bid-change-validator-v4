import type { CompanyProfile } from '@/lib/qualification-api';

export type ProductProfileArea = {
  key: string;
  label: string;
  filled: boolean;
};

export function productProfileAreas(company: CompanyProfile | null): ProductProfileArea[] {
  if (!company) {
    return [
      ['INDUSTRY', '업종 코드'],
      ['REGION', '소재지'],
      ['COMPANY_SIZE', '기업 구분'],
      ['STAFF', '상시 근로자 수'],
      ['PERFORMANCE_COUNT', '최근 수행 실적 건수'],
      ['PERFORMANCE_AMOUNT', '최근 수행 실적 금액'],
      ['REGISTRATION_CERTIFICATION', '인증 · 등록'],
    ].map(([key, label]) => ({ key, label, filled: false }));
  }

  const hasPerformance = company.performances.length > 0;
  return [
    { key: 'INDUSTRY', label: '업종 코드', filled: company.industries.length > 0 },
    { key: 'REGION', label: '소재지', filled: Boolean(company.region_name || company.region_code) },
    { key: 'COMPANY_SIZE', label: '기업 구분', filled: company.company_size !== 'NONE' },
    { key: 'STAFF', label: '상시 근로자 수', filled: Boolean(company.staff) },
    // 실적이 한 건도 없으면 건수도 금액도 「받은 적이 없다」는 뜻이지 「0건임을 확인했다」가 아니다.
    // 전에는 건수만 항상 채워진 것으로 셌는데, 그러면 같은 performances 배열이
    // 건수는 「0건」, 금액은 「비어 있음」으로 갈려 읽힌다.
    { key: 'PERFORMANCE_COUNT', label: '최근 수행 실적 건수', filled: hasPerformance },
    { key: 'PERFORMANCE_AMOUNT', label: '최근 수행 실적 금액', filled: hasPerformance },
    { key: 'REGISTRATION_CERTIFICATION', label: '인증 · 등록', filled: company.certifications.length > 0 },
  ];
}

export function productProfileCoverage(company: CompanyProfile | null) {
  const areas = productProfileAreas(company);
  return {
    filled: areas.filter((area) => area.filled).length,
    total: areas.length,
    missing: areas.filter((area) => !area.filled),
  };
}
