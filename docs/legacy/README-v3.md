# bid-change-validator

> Validates how changed public procurement notices affect existing bid qualifications, required documents, and submission readiness.

## Project

**나라장터 변경공고 대응형 입찰 제출 검증기**

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하고, 변경된 조건과 원문 근거를 바탕으로 영향을 받은 항목을 재검증하는 프로젝트입니다.

**Current Stage**  
**Product Baseline 구현·안전성 보강 / Ready 보류** — 2026-09-08, `fix/product-baseline-audit` / [PR #74](https://github.com/gyuniverse-hq/bid-change-validator/pull/74). 이 문서의 구현 기준은 PR #74 코드 `87b9a5f`이며, 문서 갱신 시 PR은 Draft·미병합입니다.

## Team

| Member | Initial Role |
| --- | --- |
| 김재현 | LLM / RAG |
| 이홍규 | LLM / RAG · Collaboration Infrastructure |
| 전진환 | Backend / Overall Structure |
| 정예린 | DB / Data Management |
| 황수빈 | Frontend / UI·UX |

> 역할은 2026-09-02 회의에서 정한 초기 역할 기준이며, 기능별 세부 책임은 Figma·프로토타입 검토 후 조정할 수 있습니다.

## Parallel Development Workspaces

초기 병렬 개발에서 사용한 Frontend / Backend / LLM·RAG workspace는 다음과 같습니다. 현재 제품 통합 기준은 이 저장소의 Product Baseline이며, 아래 저장소의 최신 동기화 상태를 뜻하지 않습니다.

| Workspace | Owners | Repository |
| --- | --- | --- |
| Frontend | 황수빈 (Main), 이홍규 (Sub) | https://github.com/gyuniverse-hq/bid-change-validator-frontend |
| Backend / Data | 전진환 (Backend), 정예린 (DB / Data) | https://github.com/gyuniverse-hq/bid-change-validator-backend |
| LLM / RAG | 김재현, 이홍규 | https://github.com/gyuniverse-hq/bid-change-validator-llm-rag |

현재 구현·계약·검증 상태는 [Product Baseline 문서](docs/mvp-baseline/README.md)를 우선 확인하고, 초기 협업 맥락은 아래 문서를 참고합니다.

- 병렬 작업 가이드: `docs/parallel-development.md`
- Frontend ↔ Backend 계약 초안: `docs/contracts/frontend-backend.md`
- Backend ↔ LLM / RAG 계약 초안: `docs/contracts/backend-llm.md`

## Current Focus

- 01~07 제품 화면과 Analysis → deterministic Judgment → Evidence → Ask-back 연결 유지
- `qualification-rules-v0.2`의 보수적 판정, `UNKNOWN != ASKABLE`, USER_ANSWER Policy A 유지
- 실제 추출 품질·표/예외 문맥, 과거 분석 캐시 재검증, meaningful 변경공고 G2 확보
- G0 통과, G1 실제 경로/안전한 보류 확인, G2 미확보: **Product Baseline Ready는 보류**
- 코드 기준 Backend 102개·Frontend 회귀 3개·타입·수정 파일 lint·build 통과, [CI #58 성공](https://github.com/gyuniverse-hq/bid-change-validator/actions/runs/34178537233). 전체 lint의 기존 오류 27개는 남아 있습니다.

상세 상태·남은 blocker는 [audit](docs/mvp-baseline/11-product-baseline-audit.md), 담당별 후속 작업은 [handoff](docs/mvp-baseline/08-team-handoff-current-state.md)를 확인하세요.

## 로컬 PostgreSQL 실행

PostgreSQL을 실행하고 마이그레이션, API, 변경공고 수집기를 시작합니다.

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

실행 주소는 다음과 같습니다.

- 상태 확인: `http://localhost:8000/health`
- Swagger API 문서: `http://localhost:8000/docs`

API가 시작되기 전에 Alembic이 데이터베이스 스키마를 자동으로 적용합니다. 마이그레이션을 수동으로 적용하려면 다음 명령을 사용합니다.

```powershell
docker compose run --rm migrate
```

업종, 품목, 기관 기준정보 CSV를 최초 적재하거나 갱신합니다.

```powershell
docker compose --profile tools run --rm master-data-import
```

기준정보 적재는 UPSERT 방식이므로 다시 실행해도 중복 데이터가 만들어지지 않고 기존 코드가 갱신됩니다.

기준정보 검색 API는 다음과 같습니다.

```text
GET /api/v1/master-codes/industries?q=토목&limit=20
GET /api/v1/master-codes/products?q=1010150201
GET /api/v1/master-codes/institutions?q=서울&active_only=false
GET /api/v1/master-codes/institutions/1011052
```

검색 결과는 정확한 코드, 코드 앞부분, 정확한 이름, 이름 앞부분 순서로 우선 정렬됩니다. `active_only=true`가 기본값이며 `limit`은 1부터 100까지 지정할 수 있습니다.

## 로컬 Qualification Integration 확인

`fix/product-baseline-audit`의 `/qualification` 화면에서 실제 Backend API와 OpenAI 기반 자격요건 분석 경로를 확인할 수 있습니다. PR #74의 대상은 `integration/mvp-baseline`이며 `main`/`develop`을 직접 수정하지 않습니다.

먼저 저장소 루트에서 `.env.example`을 `.env`로 복사하고 OpenAI API Key를 입력합니다.

```powershell
Copy-Item .env.example .env
```

`.env`의 다음 값을 설정합니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_DEFAULT=gpt-5.6-luna
```

`.env`와 `.env.*`는 Git ignore 대상이며 `.env.example`만 추적합니다. 실제 API Key를 commit하지 마세요.

Backend API 컨테이너는 source bind mount가 아닌 build image 방식입니다. **Backend 코드를 변경한 뒤에는 다시 빌드해야 합니다.**

```powershell
docker compose up -d --build api
```

최초 실행 시 수집기도 함께 시작할 수 있습니다.

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

프론트엔드는 별도 터미널에서 실행합니다.

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

`apps/web/.env.example`에는 로컬 API 주소가 기본값으로 들어 있습니다. `pnpm-workspace.yaml`은 `esbuild`, `sharp`, `workerd`의 필수 build script를 허용하므로 별도의 `pnpm approve-builds` 단계 없이 설치할 수 있습니다.

확인 주소:

- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- 기본 화면: `http://localhost:3000`
- Qualification Integration: `http://localhost:3000/qualification`

`OPENAI_API_KEY`가 비어 있으면 qualification analysis 실행 시 `AI_PROVIDER_NOT_CONFIGURED` 오류가 반환되는 것이 정상입니다.

## 나라장터 공고 수집

등록공고, 변경공고 또는 공고번호 한 건을 API로 수집할 수 있습니다.

```text
POST /api/v1/notices/sync
GET  /api/v1/notices?q=정보시스템&business_type=SERVICE
GET  /api/v1/notices/{notice_id}
GET  /api/v1/notices/{notice_id}/versions
GET  /api/v1/notices/collection-runs
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/content
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/text
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/preview
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/source
POST /api/v1/notices/documents/extract-pending
```

수집기는 정규화한 공고 필드와 나라장터 원본 JSON을 함께 저장합니다. 이전과 동일한 원본 데이터는 기존 버전을 재사용하고, 내용이 바뀌면 다음 버전을 생성해 현재 버전으로 표시합니다.

표준공고문과 `ntceSpecDocUrl1`부터 `ntceSpecDocUrl10`까지의 첨부파일을 내려받습니다. URL과 파일 해시가 같은 파일은 한 번만 저장하며 저장경로, MIME 유형, 파일 크기, SHA-256, 다운로드 상태를 PostgreSQL에 기록합니다.

HWP/HWPX는 구역·문단 단위로, PDF는 페이지 단위로 텍스트를 추출합니다. `/text` API는 비교 화면에서 사용할 전체 텍스트와 원문 위치 블록을 반환합니다. 텍스트 추출 결과는 시각적 서식을 보존하지 않으므로 원본 파일을 최종 근거로 사용합니다.

PDF는 `/preview` API로 브라우저에서 표시합니다. HWP/HWPX는 rhwp WebAssembly 뷰어에서 렌더링할 수 있도록 `viewer_type`, `render_source_url`, `text_url`, `preview_url`을 제공합니다. 프론트엔드 연결 규격은 `docs/contracts/rhwp-viewer.md`에서 확인할 수 있습니다.

`notice-poller` 서비스는 5분마다 용역, 물품, 공사, 외자 분야의 변경공고를 조회합니다. 마지막 성공 구간부터 수집을 재개하며 경계 누락을 방지하기 위해 5분을 겹쳐 다시 조회합니다. 중복 데이터는 원본 해시로 걸러내고 PostgreSQL advisory lock을 사용해 여러 수집기가 동시에 실행되지 않도록 합니다.

실행 간격과 조회 범위는 `NOTICE_POLL_*` 환경변수로 조정할 수 있으며, 실행 결과는 `GET /api/v1/notices/collection-runs`에서 확인할 수 있습니다.

## 제안서 사전검토 건

공고 버전을 기준으로 검토 건을 생성하고 제안서 파일을 업로드합니다.

```text
POST /api/v1/preflight-cases
GET  /api/v1/preflight-cases
GET  /api/v1/preflight-cases/{case_id}
POST /api/v1/preflight-cases/{case_id}/documents
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/source
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/content
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/text
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/preview
```

업로드 API는 HWP, HWPX, PDF, DOCX, TXT 형식을 지원합니다. 파일 크기를 제한하고 SHA-256으로 검토 건 안의 중복 파일을 차단합니다. 공고 첨부파일과 동일한 로컬/S3 저장구조를 사용하며 업로드 직후 텍스트를 추출합니다. 추출에 성공한 제안서가 하나 이상 있으면 검토 건 상태가 `DRAFT`에서 `READY`로 변경됩니다.

이 단계에서는 LLM을 호출하거나 자격판정 결과를 생성하지 않습니다.

## 현재 제품 화면과 실제 흐름

[Figma 7개 화면](https://www.figma.com/design/eWoeKC5CCjuWwVzXLvb4ES/?node-id=7-45)은 Product IA Source of Truth입니다. 아래 7개 route는 구현되어 브라우저 이동을 확인했으며, 모든 기능의 최종 품질 완료를 뜻하지 않습니다.

| 화면 | Route | 현재 범위 |
| --- | --- | --- |
| 01 공고 찾기 | `/notices` | 실공고 조회와 분석된 현재 공고의 Rule Matching 구분 |
| 02 참가자격 검토 | `/qualification` | 한 번의 검토 시작으로 Analysis → Judgment; 요약·첨부·위험/미구조화·회사값·근거 |
| 03 확인 필요 | `/ask-back` | Askable만 답변, 해당 Requirement 부분 재판정 |
| 04 근거 원문 | `/evidence` | 현재 문서·Evidence·판정 연결, HWPX/PDF 추출 원문 대조 |
| 05 평가 대응 | `/evaluation` | 참가자격 기반 회사정보 참고; **평가 전용 extraction 미완료**, 점수 예측 없음 |
| 06 변경 이력 | `/changes` | 버전 비교·Requirement Diff·affected-only API 연결; 실제 G2 미검증 |
| 07 회사 프로필 | `/company` | 회사값 표시, 수행실적·인증/등록 관리 |

02~06은 같은 `caseId`와 참가자격 / 확인 필요 / 근거 원문 / 평가 대응 / 변경 이력 5개 탭을 유지합니다.

```text
회사 Profile → 실제 공고 조회 → 분석된 공고 Matching → Case/Version 선택
→ 원문 Parsing → LLM/RAG Requirement Extraction·Mapping·Evidence
→ deterministic Rule → SATISFIED / UNSATISFIED / UNKNOWN
→ Askable UNKNOWN만 USER_ANSWER → 해당 Requirement 부분 재판정
→ 원문 확인 → 평가 대응 참고 → 변경공고 Requirement Diff → affected-only revalidation
```

LLM은 최종 참가 가능/불가를 결정하지 않습니다. 복합·법적·예외·불명확 조건은 UNMAPPED/UNKNOWN으로 보류합니다. PARTIAL은 답변으로 모든 현재 항목을 충족해도 eligible로 승격하지 않습니다. 필수 그룹이 확정 미달이면 ineligible, 그렇지 않으면 insufficient_data입니다.

USER_ANSWER는 `apply_to_profile=false`인 **Policy A**로 현재 Case 판정 근거에만 저장합니다. 회사 프로필로 자동 승격하지 않습니다. Evidence는 전체 raw와 source-local 조항을 검증하고 원본 파일/추출 텍스트 해시를 구분합니다.

### PR #74 이후 기존 Demo/Golden 재검증

Rule은 `qualification-rules-v0.2`, Analysis Contract는 `ai-analysis-v0.2`입니다. **과거 AnalysisRun의 SUCCEEDED나 같은 Contract 버전이 새 grounding/validation 정책 통과를 뜻하지 않습니다.** 자동 소급 검증·일괄 캐시 무효화는 구현되지 않았습니다.

PR #74 merge 이후 API를 rebuild하고, 기존 Demo/Golden의 baseline/current를 **full re-analysis → 새 analysis ID로 Judgment → 필요한 안전한 답변 → 변경 재검증** 순서로 실행하세요. 기존 결과를 삭제하거나 성공 상태로 고치지 않습니다. [상세 절차](docs/mvp-baseline/06-handoff-and-merge.md)를 따릅니다.

G0는 합성 회귀 통과, G1은 실제 PARTIAL 분석·원문·판정·unsafe 답변 거절 확인입니다. G2는 후보 10건 검산 후에도 미확보입니다. `R26BK01715087`은 RFP가 같고 시간/설명회 안내만 바뀌어 탈락했습니다. [후보 검산·남은 조건](docs/mvp-baseline/05-e2e-golden-path.md)을 참고하세요.

기존 Proposal 업로드·저장·추출·원문 API와 관련 검토 구성요소는 유지됩니다. 현재 7개 제품 화면과 제안서 대응/누락검사 전체 연결은 별도로 검증해야 하며, 해당 기능을 dead code로 분류하지 않습니다.

로컬 프런트엔드는 `http://localhost:3000`, API는 `NEXT_PUBLIC_API_BASE_URL`로 연결합니다. 실제 외부 배포 완료를 의미하지 않습니다.

## AWS 배포 설정

로컬 Docker에서는 `notice_documents_data` 볼륨에 문서를 저장합니다. AWS에서는 다음 환경변수를 설정해 S3 저장소를 사용합니다.

- `DOCUMENT_STORAGE_BACKEND=S3`
- `DOCUMENT_S3_BUCKET`
- `DOCUMENT_S3_PREFIX`
- `AWS_REGION`

ECS 또는 EC2에는 고정 AWS 키를 저장하지 않고 IAM 역할로 S3 접근 권한을 부여해야 합니다. PostgreSQL은 RDS, API와 변경공고 수집기는 별도 ECS 서비스 또는 EC2 프로세스로 운영하는 구성을 권장합니다.

## Collaboration

기본 개발 흐름은 다음과 같이 운영합니다.

```text
Figma / Requirement
→ Jira Work Item
→ Branch
→ Pull Request
→ Review / Test
→ Merge
→ Jira Done
```

- `main`: 안정 버전 / 배포 기준
- `develop`: 이후 통합 검토 대상 브랜치; 현재 Baseline 작업에서 직접 수정 금지
- 현재 문서/코드 작업: `fix/product-baseline-audit` → PR #74 → `integration/mvp-baseline`
- PR 보강 변경의 merge 판단과 Product Baseline Ready/동결 승인은 별도입니다.
- 기능 브랜치: `feat/SKN34-XX-summary`, `fix/SKN34-XX-summary` 등
- 주요 변경은 Pull Request와 최소 1명 Review를 거칩니다.

## Documentation

현재 구현·정책·검증·handoff의 시작점은 [docs/mvp-baseline/README.md](docs/mvp-baseline/README.md)입니다. 과거 설계/Proposal 문서는 맥락을 유지하며 현재 구현 상태와 구분합니다.
