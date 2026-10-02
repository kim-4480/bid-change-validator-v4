# 03. Screen ↔ System Map

이 문서는 화면 요구사항을 실제 Backend / DB / AI 연결점에 매핑합니다.

기준: PR #74 코드 `87b9a5f`, 2026-09-08. Figma 7개 화면이 Product IA Source of Truth다. 화면 연결 완료와 전체 실공고 E2E 완료는 구분한다.

## 1. 구현된 01~07 screen map

| 화면 | Route | 실제 연결 / 완료 범위 | 검증 한계 |
| --- | --- | --- | --- |
| 01 공고 찾기 | `/notices` | 공고 검색·버전 조회, 분석된 현재 공고의 회사별 Matching, 회사/현재 차수가 같은 Case 재사용 | 미분석 공고는 매칭 완료가 아님 |
| 02 참가자격 검토 | `/qualification` | Case 분석→판정 API, 공고 요약·첨부·위험/미매핑 조건·회사값·근거 | 추출 완전성은 PARTIAL/FAILED로 별도 표시 |
| 03 확인 필요에 답하기 | `/ask-back` | ASKABLE UNKNOWN 답변, Policy A 부분 재판정 | 실공고 safe-answer 성공은 미검증; G0/API 회귀로 확인 |
| 04 근거 원문 대조 | `/evidence` | 문서별 extracted text/blocks, Evidence deep link, HWPX/PDF 전환 | 표/주변 예외 의미 완전성은 별도 검증 |
| 05 평가 대응 | `/evaluation` | 자격요건 기반 회사 참고자료, 전용 추출 미지원 안내 | Evaluation 전용 extraction 미완료, 점수 예측 없음 |
| 06 변경 이력 | `/changes` | 버전 비교·Canonical Diff·재검증 API, 최초 차수 빈 상태 | meaningful 실제 G2 미확보 |
| 07 회사 프로필 | `/company` | 회사정보 조회, 실적/인증 CRUD UI | 전체 프로필 편집/변경 후 역사판정 UX의 완전한 E2E는 미검증 |

02~06은 같은 `caseId`의 5개 탭이다. current version/company/analysis/rule이 일치하는 판정과 질문만 연결하며, 없는 Case는 오류로 표시한다. 브라우저 7개 화면 navigation smoke를 확인했으나 Figma 직접 대조는 도구 quota로 미완료다.
API별 정확한 경로와 persistence는 [팀 Handoff](08-team-handoff-current-state.md), 상태는 [Contract Map](04-contract-and-status-map.md)을 따른다.

## 2. Product UX principle

핵심 화면 흐름은 다음 순서를 유지합니다.

```text
판정
↓
근거
↓
해결
```

사용자는 먼저 무엇이 충족/미달/확인 필요인지 보고, 그다음 왜 그런 판정인지 원문 근거를 확인하고, 마지막으로 해결 가능한 행동을 수행합니다.

## 3. Qualification screen target

### Summary layer

화면 상단은 최종 판정을 단일 색상으로 단순화하기보다 Requirement 분포를 보여줄 수 있어야 합니다.

```text
충족: N
미달: N
확인 필요: N
분석 경고: N
```

`분석 경고`는 AI Analysis의 `PARTIAL`/diagnostic이고, `확인 필요`는 Judgment `UNKNOWN`입니다. 서로 합치지 않습니다.

### Requirement rows

각 Requirement row가 최소한 다음 정보를 표시할 수 있어야 합니다.

- Requirement label / normalized condition
- Judgment status
- reason
- Company Profile basis
- Evidence link
- 해결 액션 여부
- 변경공고 영향 여부

### Evidence drawer / panel

근거 클릭 시 다음 연결이 유지되어야 합니다.

```text
requirement_key
→ evidence_key
→ document_id
→ source location
→ original preview/source
```

HWP/HWPX는 존재하지 않는 PDF page를 임의 생성하지 않고 Backend extracted block locator를 사용합니다.

## 4. Company Profile screen target

현재 Backend Company Profile은 단순 회사명 수준이 아니라 다음 판정 정보를 포함할 수 있습니다.

- 업종
- 지역
- 기업규모
- 인력 및 역할
- 수행실적 / 경험분야
- 인증/등록 정보

Baseline에서는 이 정보를 Canonical Requirement와 직접 대응시킬 수 있어야 합니다.

```text
INDUSTRY                    ↔ industries
REGION                      ↔ region
STAFF                       ↔ staff / roles
PERFORMANCE_AMOUNT          ↔ performances.amount
PERFORMANCE_COUNT           ↔ performances
EXPERIENCE_FIELD            ↔ performance fields
REGISTRATION_CERTIFICATION  ↔ certifications
COMPANY_SIZE                ↔ company_size
```

현재 필드와 비교 규칙은 deterministic Rule `qualification-rules-v0.2`에 연결되어 있습니다. 정보 부재/불완전성은 UNKNOWN으로 보류합니다.

## 5. Change history screen target

변경공고 화면은 단순 문서 diff보다 **사용자에게 미치는 판정 영향**을 우선합니다.

권장 표현:

```text
변경된 공고 조건
→ 영향을 받은 Requirement
→ 이전 판정
→ 현재 판정
→ 이전 Evidence / 현재 Evidence
→ 필요한 조치
```

전체 문서 변경 내역은 보조 정보로 두고, 실제 제출 가능성에 영향을 주는 변경을 우선 표시합니다.

## 6. API / 검증 기준

Analysis, Judgment, Ask-back, Revalidation API와 저장 모델은 구현되어 있다. 새 endpoint를 가정하지 않고 [실제 API surface](08-team-handoff-current-state.md)를 사용한다. [G0/G1/G2](05-e2e-golden-path.md)의 검증 범위를 넘겨 완료로 표시하지 않는다.
