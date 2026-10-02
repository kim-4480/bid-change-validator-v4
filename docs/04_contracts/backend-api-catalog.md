# Backend API Catalog · Current develop

> **상태: Current**  
> 기준: `develop`의 실제 FastAPI Router

이 문서는 제품 기능과 실제 Endpoint를 빠르게 연결하기 위한 Catalog입니다. 정확한 Request/Response 필드는 Pydantic schema와 Swagger가 최종 Source of Truth입니다.

## Notice / Document

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/v1/notices/sync` | 나라장터 공고 수집 |
| GET | `/api/v1/notices` | 공고 검색/목록 |
| GET | `/api/v1/notices/{notice_id}` | 현재 공고 상세 |
| GET | `/api/v1/notices/{notice_id}/versions` | 공고 버전 목록 |
| POST | `/api/v1/notices/documents/extract-pending` | 대기 문서 Extraction |
| GET | `/api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/text` | 추출 text/blocks |
| GET | `/api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/source` | 원본 inline source |
| GET | `/api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/content` | 원본 다운로드 |
| GET | `/api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/preview` | PDF preview 경계 |

HWP/HWPX는 PDF page를 임의 생성하지 않습니다. 원문 위치 표시는 Backend extracted block locator와 `Evidence.location.display`를 우선합니다.

## Company Profile

주요 prefix: `/api/v1/companies`

- Company create/list/read/update/delete
- Industry verification
- Performance create/update/delete
- Certification create/update/delete
- Staff / role 관련 Profile 데이터

자격판정 completeness는 별도 API가 있습니다.

| Method | Path |
| --- | --- |
| GET | `/api/v1/companies/{company_id}/qualification-profile-completeness` |
| PATCH | `/api/v1/companies/{company_id}/qualification-profile-completeness` |

## Preflight Case / Proposal

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/v1/preflight-cases` | 회사·공고·버전을 묶는 검토 Case 생성 |
| GET | `/api/v1/preflight-cases` | Case 목록/검색 |
| GET | `/api/v1/preflight-cases/{case_id}` | Case 조회 |
| POST | `/api/v1/preflight-cases/{case_id}/documents` | 제안서/사용자 문서 업로드 |
| GET | `/api/v1/preflight-cases/{case_id}/documents/{document_id}/text` | 제안서 추출 text/blocks |
| GET | `/api/v1/preflight-cases/{case_id}/documents/{document_id}/source` | 원문 inline source |
| GET | `/api/v1/preflight-cases/{case_id}/documents/{document_id}/content` | 파일 다운로드 |
| GET | `/api/v1/preflight-cases/{case_id}/documents/{document_id}/preview` | viewer 경계 |

## Qualification Analysis

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis` | 해당 공고 버전 Analysis 실행 |
| GET | `/api/v1/notices/{notice_id}/versions/{version_number}/qualification-analyses` | 해당 버전 Analysis Run 목록 |
| GET | `/api/v1/qualification-analyses/{run_id}` | Analysis Run 상세 |

`POST`는 `OpenAIStructuredExtractor`가 사용 가능해야 하며, Provider 미설정 시 `503 AI_PROVIDER_NOT_CONFIGURED` 경계를 가집니다.

## Qualification Judgment

| Method | Path | 역할 |
| --- | --- | --- |
| POST | `/api/v1/preflight-cases/{case_id}/qualification-judgments` | 특정/최신 Analysis 기준 deterministic 판정 |
| GET | `/api/v1/preflight-cases/{case_id}/qualification-judgment-runs` | Case의 Judgment Run 목록 |
| GET | `/api/v1/qualification-judgment-runs/{run_id}` | Judgment Run 상세 |

전체 자격상태는 Judgment Run의 `overall_status`가 Source of Truth입니다.

```text
eligible | ineligible | insufficient_data
```

개별 requirement 상태:

```text
SATISFIED | UNSATISFIED | UNKNOWN
```

## Ask-back

| Method | Path | 역할 |
| --- | --- | --- |
| GET | `/api/v1/preflight-cases/{case_id}/qualification-questions` | 질문 가능한 Requirement 조회 |
| POST | `/api/v1/preflight-cases/{case_id}/qualification-answers` | 사용자 답변 + 부분 재판정 |

질문 목록은 선택적으로 `source_judgment_run_id`를 받아 특정 판정 기준으로 고정할 수 있습니다.

답변 요청의 핵심 필드:

- `source_judgment_run_id`
- `requirement_key`
- `satisfies_requirement`
- `normalized_value`
- `evidence_held`
- `apply_to_profile`

`UNKNOWN`이라고 해서 자동으로 질문하지 않습니다. `askability.py` 정책에서 단순 사용자 사실로 안전하게 해소 가능한 경우만 질문합니다.

## Changed Notice Revalidation

| Method | Path |
| --- | --- |
| POST | `/api/v1/preflight-cases/{case_id}/qualification-revalidation` |

입력은 source Judgment와 baseline/current Analysis를 명시할 수 있고, 출력은 `changes`, `revalidated_keys`, `result` Judgment Run을 반환합니다.

## Profile → Notice Matching

| Method | Path |
| --- | --- |
| GET | `/api/v1/companies/{company_id}/notice-matches` |

현재 저장된/분석된 공고와 회사 Profile을 기반으로 Product 목록에 사용할 matching 결과를 제공합니다. 공고 메타 검색과 완전한 첨부문서 자격판정은 같은 단계가 아닙니다.

## 현재 없는/미확정 Product API

다음은 코드에 이미 존재한다고 가정하면 안 됩니다.

- Evaluation Criterion 전용 extraction/product API
- Proposal Requirement Retrieval 전용 API
- AI Copilot chat/orchestration API
- Copilot session/history API

필요성이 확정되면 기존 Product Service를 재사용하는 최소 API로 추가합니다.

## Error / Consistency 원칙

- Case의 `company_id`, `notice_id`, `current_version`과 Run의 연결이 맞아야 합니다.
- stale Analysis/Judgment/Rule/Profile 기반 결과를 묵시적으로 재사용하지 않습니다.
- 없는 Analysis는 `404 ANALYSIS_RUN_NOT_FOUND` 등 명시적 도메인 오류를 사용합니다.
- Document 원본이 없거나 viewer가 맞지 않으면 404/409/503 경계를 구분합니다.
- Copilot은 DB를 직접 읽어 비공식 판정을 만들기보다 위 Product API/Service를 소비합니다.
