/**
 * 05 평가 대응 — 제안서 위치 탐색용 키워드 사전 + 매칭 규칙.
 *
 * 위치: apps/web/lib/proposal-keywords.ts (수빈 영역)
 *
 * 원칙
 *  - LLM 아님. 백엔드 추출기가 주는 blocks(document_extraction.py)를 문자열 검색한다.
 *  - 결과는 「관련 문구 후보」다. 다뤘는지 판단은 사용자가 한다 (00 §7.2 DL-001).
 *  - 못 찾으면 빈 배열. 화면은 「찾지 못했습니다. 직접 확인해주세요」로 그린다 (08 §7).
 *  - 점수는 정렬용 내부값이다. 화면에 숫자로 내보내지 않는다 (DL-002).
 */

/** document_extraction.py `_finish()`가 붙이는 필드. PDF는 page, HWP/HWPX는 section/paragraph. */
export type ProposalBlock = {
  block_index: number;
  text: string;
  page?: number | null;
  section_index?: number | null;
  paragraph_index?: number | null;
  location?: string | null;
};

export type ProposalHit = {
  block: ProposalBlock;
  /** 화면 표기용 위치. "p.3" / "1구역 · 12문단" */
  location: string;
  /** 키워드 앞뒤 발췌. 앞 80자 · 뒤 120자 */
  excerpt: string;
  /** 어떤 키워드가 맞았는지 — 화면에서 「'수행실적' 포함」처럼 근거로 보여준다 */
  matched: string[];
};

/**
 * 요건 유형별 키워드. 제안서(용역 제안서·제출서류)에서 실제로 쓰는 표현 기준.
 * 앞쪽일수록 강한 신호. 붙여쓰기/띄어쓰기 둘 다 넣는다 — 추출 텍스트는 공백이 제각각이다.
 */
export const PROPOSAL_KEYWORDS: Record<string, string[]> = {
  PERFORMANCE_AMOUNT: ['수행실적', '수행 실적', '사업실적', '사업 실적', '용역실적', '실적증명', '실적 증명', '유사용역', '유사 용역', '계약금액', '계약 금액', '수행금액'],
  PERFORMANCE_COUNT: ['수행실적', '수행 실적', '사업실적', '사업 실적', '용역실적', '실적증명', '실적 증명', '유사용역', '유사 용역', '실적 건수', '수행 건수'],
  STAFF: ['투입인력', '투입 인력', '수행인력', '수행 인력', '인력구성', '인력 구성', '참여인력', '참여 인력', '수행조직', '수행 조직', '사업책임자', '사업 책임자', '조직도', '상시근로자', '상시 근로자', '직원 수'],
  REGISTRATION_CERTIFICATION: ['인증서', '등록증', '인증', '등록', '면허', '자격증', '지정서', '확인서'],
  EXPERIENCE_FIELD: ['수행경험', '수행 경험', '운영경험', '운영 경험', '유사사업', '유사 사업', '수행이력', '수행 이력', '전문성', '주요 사업', '주요사업'],
  COMPANY_SIZE: ['중소기업확인서', '중소기업 확인서', '중소기업', '소기업', '중견기업', '기업규모', '기업 규모', '기업 구분', '사업자등록증'],
  // 05 표에는 지금 안 나오지만(6종 필터) 어댑터가 8종 다 받을 수 있게 둔다
  INDUSTRY: ['업종', '업태', '종목', '사업자등록증', '업종코드'],
  REGION: ['소재지', '본사', '본점', '사업장', '주소', '사업자등록증'],
};

/** 블록 앞 40자에 이 제목이 있으면 가중. 제안서 목차에서 회사 정보가 모이는 섹션들. */
export const PROPOSAL_SECTION_HINTS = ['일반현황', '일반 현황', '회사소개', '회사 소개', '기업개요', '기업 개요', '업체현황', '업체 현황', '수행실적', '투입인력', '수행조직', '인력구성', '제출서류', '제출 서류', '첨부', '붙임'];

/** raw에서 명사만 뽑을 때 버리는 말. 요건 문장에 늘 나오는 기능어. */
const RAW_STOPWORDS = new Set(['이상', '이하', '최근', '이내', '합계', '억원', '만원', '경우', '또는', '관련', '보유', '기준', '해당', '대한', '있는', '위한', '것을', '하는', '으로', '에서', '까지', '부터', '이며', '이고', '자격', '요건', '조건', '업체', '기업', '참가', '입찰', '제출', '가능', '필요', '금액', '건수']);

/**
 * 요건 raw 문장에서 검색어로 쓸 한글 토큰(2자 이상)을 뽑는다.
 * 예) "최근 3년 이내 창업기획자 등록 업체" → ["창업기획자", "등록"]
 */
export function rawKeywords(raw: string): string[] {
  const tokens = raw.match(/[가-힣A-Za-z]{2,}/g) ?? [];
  return [...new Set(tokens)].filter((token) => !RAW_STOPWORDS.has(token));
}

export function formatBlockLocation(block: ProposalBlock): string {
  if (block.page != null) return `p.${block.page}`;
  if (block.section_index != null && block.paragraph_index != null) return `${block.section_index + 1}구역 · ${block.paragraph_index + 1}문단`;
  if (block.location) return block.location;
  return `${block.block_index + 1}번째 문단`;
}

/** 긴 키워드에 포함된 짧은 키워드를 뺀다. ['중소기업확인서','중소기업','소기업'] → ['중소기업확인서'] */
function dropNested(hits: string[]): string[] {
  const unique = [...new Set(hits)];
  return unique.filter((hit) => !unique.some((other) => other !== hit && other.includes(hit)));
}

function excerptAround(text: string, keyword: string): string {
  const index = text.indexOf(keyword);
  if (index < 0) return text.slice(0, 200);
  const start = Math.max(0, index - 80);
  const end = Math.min(text.length, index + keyword.length + 120);
  return `${start > 0 ? '…' : ''}${text.slice(start, end).replace(/\s+/g, ' ').trim()}${end < text.length ? '…' : ''}`;
}

/**
 * 요건 하나에 대해 제안서 blocks에서 후보 위치를 찾는다.
 *
 * 규칙
 *  1. 유형 키워드가 1개 이상 맞거나, raw 토큰이 2개 이상 맞아야 후보. raw 토큰 하나만 맞는 건 너무 약하다.
 *  2. 점수 = 유형 키워드 종류 수 × 2 + raw 토큰 종류 수 × 1 + 섹션 제목 힌트 1
 *     ('중소기업'이 맞으면 '소기업'은 따로 세지 않는다 — 긴 키워드에 포함된 짧은 키워드는 제외)
 *  3. 점수 내림차순, 같으면 문서 앞쪽 우선. 최대 3개.
 *  4. PDF는 블록 = 페이지 하나라 텍스트가 길다. 발췌가 위치 역할을 한다.
 */
export function findProposalHits(requirementType: string, raw: string, blocks: ProposalBlock[], limit = 3): ProposalHit[] {
  const typeKeywords = PROPOSAL_KEYWORDS[requirementType] ?? [];
  const extraKeywords = rawKeywords(raw);

  const scored = blocks.flatMap((block) => {
    const text = block.text ?? '';
    if (!text.trim()) return [];
    const typeHits = dropNested(typeKeywords.filter((keyword) => text.includes(keyword)));
    const rawHits = dropNested(extraKeywords.filter((keyword) => text.includes(keyword) && !typeHits.some((hit) => hit.includes(keyword))));
    if (!typeHits.length && rawHits.length < 2) return [];
    const head = text.slice(0, 40);
    const sectionBonus = PROPOSAL_SECTION_HINTS.some((hint) => head.includes(hint)) ? 1 : 0;
    const score = typeHits.length * 2 + rawHits.length + sectionBonus;
    return [{ block, score, matched: [...typeHits, ...rawHits] }];
  });

  return scored
    .sort((a, b) => b.score - a.score || a.block.block_index - b.block.block_index)
    .slice(0, limit)
    .map(({ block, matched }) => ({
      block,
      location: formatBlockLocation(block),
      excerpt: excerptAround(block.text, matched[0]),
      matched,
    }));
}

/** 사용자 판단 3상태 — 00 §7.2 DL-001. 저장은 localStorage, 키는 caseId + 제안서 문서 id. */
export type ProposalCheckState = 'CHECKED' | 'PENDING' | 'NOT_APPLICABLE';

export const PROPOSAL_CHECK_COPY: Record<ProposalCheckState, string> = {
  CHECKED: '확인함',
  PENDING: '아직',
  NOT_APPLICABLE: '해당없음',
};

export function proposalCheckStorageKey(caseId: string, proposalDocumentId: string) {
  return `bidcheck:proposal-check:${caseId}:${proposalDocumentId}`;
}
