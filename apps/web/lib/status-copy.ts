/**
 * 화면에 나가는 상태 문구를 한 곳에 모은다.
 *
 * 규칙 (07 요구사항명세서)
 *  - NFR-10 · 색은 판정에만 쓴다. 정보성 배지에 판정 색을 쓰지 않는다.
 *  - 영어 enum(SATISFIED / USER_ANSWER / PARTIAL …)은 사용자 화면에 그대로 나가지 않는다.
 *  - 문구를 바꿀 일이 생기면 컴포넌트가 아니라 이 파일을 고친다.
 */

import type {
  CompanySize,
  EvidenceLocation,
  QualificationAnalysisSummary,
  QualificationJudgment,
  QualificationJudgmentRun,
  RequirementChange,
} from '@/lib/qualification-api';

type JudgmentStatus = QualificationJudgment['status'];
type BasisType = QualificationJudgment['basis_type'];
type ReasonCode = QualificationJudgment['reason_code'];
type AnalysisStatus = QualificationAnalysisSummary['status'];
type OverallStatus = QualificationJudgmentRun['overall_status'];

/** 판정 3상태 + 아직 판정 안 된 행 */
export const JUDGMENT_STATUS_LABEL: Record<JudgmentStatus | 'UNJUDGED', string> = {
  SATISFIED: '충족',
  UNSATISFIED: '미달',
  UNKNOWN: '확인 필요',
  UNJUDGED: '미판정',
};

/** 무엇에 근거해 판정했는가 (NFR-5) */
export const BASIS_TYPE_LABEL: Record<BasisType, string> = {
  PROFILE: '회사 프로필 기준',
  USER_ANSWER: '귀사 답변 기준',
  NONE: '근거 없음',
};

/** 왜 그렇게 판정했는가 — 짧은 사유. 판정 근거 문장(진환님 API)이 나오면 그걸 우선한다. */
export const REASON_CODE_LABEL: Record<ReasonCode, string> = {
  RULE_MATCH: '요건을 충족했습니다',
  RULE_MISMATCH: '요건에 미치지 못했습니다',
  INSUFFICIENT_DATA: '회사 정보가 없어 판정하지 않았습니다',
  NEEDS_REVIEW: '자동으로 판정하기 어려워 확인이 필요합니다',
  UNSUPPORTED_REQUIREMENT: '아직 판정할 수 없는 형태의 요건입니다',
};

/**
 * 공고 첨부 분석이 어디까지 됐는가.
 * PARTIAL을 SUCCEEDED처럼 그리면 "못 읽은 조건"이 사용자에게 안 보인다 (S-9).
 *
 * label — 설명과 함께 놓이는 배너 자리. 문장형이어도 된다.
 * badge — 카드 구석의 작은 이름표. 셋이 나란히 서므로 명사형으로 통일한다.
 *         「전체 / 일부만 / 못」으로 갈려서 한눈에 읽힌다.
 */
export const ANALYSIS_STATUS_COPY: Record<
  AnalysisStatus,
  { label: string; badge: string; description: string }
> = {
  SUCCEEDED: {
    label: '분석 완료',
    badge: '첨부 전체 읽음',
    description: '공고 첨부를 읽고 참가자격을 추출했습니다.',
  },
  PARTIAL: {
    label: '일부만 읽었습니다',
    badge: '첨부 일부만 읽음',
    description: '첨부 일부를 읽지 못했습니다. 아래 판정에 빠진 조건이 있을 수 있으니 원문을 함께 확인해 주세요.',
  },
  FAILED: {
    label: '첨부를 읽지 못했습니다',
    badge: '첨부 못 읽음',
    description: '이 공고는 첨부를 읽지 못해 판정하지 않았습니다. 원문을 직접 확인해 주세요.',
  },
};

/** 공고 전체 결론 */
export const OVERALL_STATUS_COPY: Record<OverallStatus, { label: string; description: string }> = {
  eligible: {
    label: '참가 가능',
    description: '현재 판정된 필수 항목에서 미달이 없습니다.',
  },
  ineligible: {
    label: '참가 불가',
    description: '미달 항목이 있어 현재 상태로는 참가 자격을 충족하지 못합니다.',
  },
  insufficient_data: {
    label: '확인 필요',
    description: '회사 정보가 부족하거나 근거가 불충분한 항목을 확인해야 합니다.',
  },
};

/**
 * 목록·카드의 판정 배지. 라벨은 위 OVERALL_STATUS_COPY와 같은 말을 쓴다.
 * 화면마다 자기 맵을 두면 같은 값이 화면마다 다른 이름으로 불린다 — 공고 목록은
 * 「응찰 가능·자격 미달」, 검토 결론은 「참가 가능·참가 불가」로 갈려 있었다 (#138 리뷰).
 * 목록에는 아직 판정이 없는 행이 있어 'unreviewed'를 하나 더 둔다.
 */
export const OVERALL_STATUS_BADGE: Record<OverallStatus | 'unreviewed', { label: string; className: string }> = {
  eligible: { label: '참가 가능', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  insufficient_data: { label: '확인 필요', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  ineligible: { label: '참가 불가', className: 'border-rose-200 bg-rose-50 text-rose-700' },
  unreviewed: { label: '미검토', className: 'border-slate-200 bg-slate-50 text-slate-600' },
};

/**
 * 되묻기 이유 3종 (03 확인 필요 화면).
 * 이유마다 사용자가 할 수 있는 일이 다르므로 화면도 달라야 한다.
 *  - answerable  : 답하면 그 항목만 다시 판정된다
 *  - read_failed : 공고 문구를 못 읽어서 묻지 않는다
 *  - no_evidence : 값은 있으나 근거 조항을 못 찾아 판정하지 않았다
 *
 * TODO 재현님 확인 — 이 3종을 API의 어떤 필드로 가르는지 확정되면 매핑 함수를 여기에 붙인다.
 */
export const ASK_BACK_REASON_COPY = {
  answerable: {
    label: '답하시면 이 줄만 다시 판정합니다',
    description: '회사 프로필에 이 값이 없어서 판정하지 못했습니다.',
    canAnswer: true,
  },
  read_failed: {
    label: '정확히 읽지 못해 묻지 않습니다',
    description: '공고 문구를 정확히 읽지 못했습니다. 원문을 직접 확인해 주세요.',
    canAnswer: false,
  },
  no_evidence: {
    label: '근거를 찾지 못해 판정하지 않았습니다',
    description: '값은 있으나 공고에서 근거 조항을 찾지 못했습니다.',
    canAnswer: false,
  },
} as const;

export type AskBackReason = keyof typeof ASK_BACK_REASON_COPY;

/** 자격요건 유형. app/qualification/page.tsx의 TYPE_LABELS를 옮겨온 것. */
export const REQUIREMENT_TYPE_LABEL: Record<string, string> = {
  INDUSTRY: '업종',
  REGION: '소재지',
  COMPANY_SIZE: '기업 구분',
  STAFF: '인력',
  PERFORMANCE_COUNT: '수행실적 건수',
  PERFORMANCE_AMOUNT: '수행실적 금액',
  REGISTRATION_CERTIFICATION: '인증 · 등록',
  EXPERIENCE_FIELD: '경험 분야',
};

/** 기업 구분. app/company/page.tsx의 SIZE_LABEL을 옮겨온 것. */
export const COMPANY_SIZE_LABEL: Record<CompanySize, string> = {
  MICRO: '소기업',
  SMALL: '중소기업',
  MEDIUM: '중기업',
  MID_SIZED: '중견기업',
  LARGE: '대기업',
  NONE: '미분류',
};

/** 변경공고 재검증 결과의 변경 유형. app/changes/page.tsx의 CHANGE_TYPE_LABEL을 옮겨온 것. */
export const CHANGE_TYPE_LABEL: Record<RequirementChange['change_type'], string> = {
  UNCHANGED: '변경 없음',
  MODIFIED: '수정됨',
  ADDED: '신설됨',
  REMOVED: '삭제됨',
};

/** 나라장터 사업유형. SERVICE 외에는 실제 값 확인 필요. */
export const BUSINESS_TYPE_LABEL: Record<string, string> = {
  SERVICE: '용역',
  GOODS: '물품',
  CONSTRUCTION: '공사',
  FOREIGN: '외자',
};

/** 첨부 뷰어 타입. PDF · RHWP만 실제로 확인된 값. */
export const VIEWER_TYPE_LABEL: Record<string, string> = {
  PDF: 'PDF',
  RHWP: '한글',
  HWP: '한글',
  HWPX: '한글',
  TEXT: '텍스트',
};

/**
 * 구조화 검증에서 제외된 요건의 사유 (P0-5).
 * 재현님 docs/llm-rag/08-frontend-integration-guide.md의 권장 문구를 그대로 쓴다.
 */
export const DROPPED_REASON_LABEL: Record<string, string> = {
  MISSING_RAW: '추출 결과에 원문이 없습니다.',
  RAW_NOT_FOUND_IN_SOURCE: '추출된 문장이 공고 원문에서 확인되지 않습니다.',
  DETAIL_NOT_FOUND_IN_SOURCE: '세부 조건이 해당 공고 원문에서 확인되지 않습니다.',
  SOURCE_VALIDATION_FAILED: '공고 원문 대조를 통과하지 못했습니다.',
};

/** 첨부 텍스트 추출 상태. */
export const EXTRACTION_STATUS_LABEL: Record<string, string> = {
  PENDING: '추출 대기',
  EXTRACTED: '텍스트 추출됨',
  EMPTY: '텍스트 없음',
  UNSUPPORTED: '추출 미지원',
  FAILED: '추출 실패',
};

/**
 * 코드값을 한글 라벨로. 목록에 없는 코드는 코드값을 그대로 돌려준다.
 * 화면이 빈칸이 되는 것보다 낫고, 못 넣은 값이 있으면 눈에 띄어서 잡을 수 있다.
 */
export function labelOf(map: Record<string, string>, code: string | null | undefined): string {
  if (!code) return '-';
  return map[code] ?? code;
}

/**
 * 분석 상태 코드를 카드 배지 문구로 바꾼다.
 * 목록 API의 analysis_status는 string이라 세 코드 밖의 값이 올 수 있다.
 * 그때는 코드값을 그대로 돌려 화면이 빈칸이 되지 않게 한다 (labelOf와 같은 방침).
 */
export function analysisBadgeLabel(status: string): string {
  const copy = (ANALYSIS_STATUS_COPY as Record<string, { badge: string }>)[status];
  return copy?.badge ?? status;
}

/**
 * 분석 상태 코드를 문장 안에서 쓸 문구로 바꾼다.
 * 배지용 짧은 문구(「첨부 전체 읽음」)는 analysisBadgeLabel, 이쪽은 상태 자체(「분석 완료」)다.
 */
export function analysisStatusLabel(status: string): string {
  const copy = (ANALYSIS_STATUS_COPY as Record<string, { label: string }>)[status];
  return copy?.label ?? status;
}

/** 판정 배지에 쓸 문구. 답변 기준 판정은 근거를 라벨에 붙인다 (NFR-5). */
export function judgmentBadgeLabel(
  status: JudgmentStatus | 'UNJUDGED',
  basisType: BasisType = 'PROFILE',
): string {
  const base = JUDGMENT_STATUS_LABEL[status];
  if (basisType === 'USER_ANSWER' && (status === 'SATISFIED' || status === 'UNSATISFIED')) {
    return `${base} · ${BASIS_TYPE_LABEL.USER_ANSWER}`;
  }
  return base;
}

/**
 * 근거 위치 문구 (P0-3).
 *
 * 백엔드가 display를 주면 **그대로** 쓴다. 화면이 "3.2항 p.4"를 조립하면
 * 페이지가 없는 HWP/HWPX 첨부에서 "3.2항 p.null" 같은 문구가 나간다.
 * display가 없을 때만 있는 값으로 최소한만 만들고, 그것도 없으면 null을 돌려
 * 호출한 쪽이 아예 표시하지 않도록 한다.
 */
export function evidenceLocationText(location?: EvidenceLocation | null): string | null {
  if (!location) return null;
  if (location.display && location.display.trim()) return location.display.trim();

  const parts: string[] = [];
  if (location.clause_label && location.clause_label.trim()) parts.push(location.clause_label.trim());
  if (typeof location.page === 'number') parts.push(`p.${location.page}`);
  return parts.length ? parts.join(' · ') : null;
}

/**
 * 분석 파이프라인 진단 코드. 화면에는 코드(EXTRACTION_PARTIAL 등)가 아니라 이 문장이 나간다.
 * 파일 맨 위 규칙 — 영어 enum은 사용자 화면에 그대로 나가지 않는다 — 을 진단에도 적용한다.
 *
 * 백엔드도 코드마다 message를 같이 보내지만 그 문장은 개발자용이다. 실제로
 * 「ANY_OF 묶음으로 담았습니다」 같은 내부 이름이 화면에 그대로 나갔다. 그래서
 * 폴백하지 않고, 목록에 없는 코드는 아예 표시하지 않는다(diagnosticText 참고).
 * 백엔드에 코드가 추가되면 여기에 사용자 문구를 같이 넣어야 화면에 보인다.
 */
export const DIAGNOSTIC_CODE_LABEL: Record<string, string> = {
  EXTRACTION_PARTIAL: '공고 원문에서 자격요건을 일부만 구조화했습니다.',
  CANONICALIZATION_WARNING: '자격요건을 정리하는 과정에서 확인이 필요한 부분이 있었습니다.',

  // 판정 대상이 아니라고 판단한 것들 — 「판정 대상이 아닌 확인사항」에 나간다.
  UNMAPPED_REQUIREMENT: '공고에 적혀 있지만 회사 프로필과 대조할 항목이 아니라, 판정하지 않고 원문만 남겼습니다.',
  UNKNOWN_LEGACY_TYPE: '지금 판정기가 다루지 않는 종류의 조건이라, 판정하지 않고 원문만 남겼습니다.',

  // 조건은 찾았지만 비교 기준을 못 만든 것들 — 사용자가 원문으로 직접 확인해야 한다.
  UNMAPPED_PERFORMANCE: '실적 조건을 판정할 수 있는 형태로 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_EXPERIENCE_FIELD: '경험 분야 조건의 비교 기준을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_INDUSTRY: '업종 조건의 비교 기준을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_REGION: '소재지 조건의 비교 기준을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_STAFF: '인력 조건의 인원이나 역할을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_REGISTRATION_CERTIFICATION: '등록·면허·인증 조건의 이름을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',
  UNMAPPED_COMPANY_SIZE: '기업 규모 조건의 비교 기준을 정리하지 못했습니다. 원문에서 직접 확인해 주세요.',

  // 조건을 살리거나 정리한 기록 — 왜 이 판정이 나왔는지 설명한다.
  DUPLICATE_REQUIREMENT: '같은 내용의 조건이 여러 번 나와 하나만 남겼습니다.',
  MERGED_INDUSTRY_REGISTRATION: '한 조항이 업종과 등록·인증 두 가지로 나뉘어 읽혀서, 업종 조건 하나로 합쳤습니다.',
  INDUSTRY_CODE_SALVAGED_FROM_SOURCE: '공고 원문에 있는 업종코드 조항을 찾아 조건에 직접 채워 넣었습니다.',
  INDUSTRY_ALTERNATION: '이 업종 조항은 여러 코드 중 하나만 있어도 되는 조건이라, 묶어서 함께 판정했습니다.',
  SALVAGED_CLOSED_IDENTIFIER: '기타 조건으로 분류됐지만 원문에 업종코드·품명번호가 있어 해당 종류로 되살렸습니다.',
  INDUSTRY_CODE_EXCEPTION_UNRESOLVED: '업종 조항 아래에 예외·대체 단서가 붙어 있어, 코드가 없다고 바로 미달로 보지 않았습니다.',
  COMPANY_SIZE_FROM_CERTIFICATE: '중소기업·소기업·소상공인 확인서는 인증이 아니라 회사 규모를 증명하는 서류라, 기업 규모 조건으로 담았습니다.',
};

/**
 * 진단 코드를 화면 문구로 바꾼다. 목록에 없으면 null — 백엔드 message로 폴백하지 않는다.
 * 호출하는 쪽은 null이면 그 줄을 그리지 않는다.
 */
export function diagnosticText(code: string | null | undefined): string | null {
  if (!code) return null;
  return DIAGNOSTIC_CODE_LABEL[code] ?? null;
}
