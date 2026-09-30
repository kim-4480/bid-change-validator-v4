# Local Run / Operations Runbook

> **상태: Local + Shared DB Current / Production TBD**  
> 기준: `develop` + 2026-09-10 팀 운영 상태

이 문서는 개발자가 새 환경에서 현재 제품을 실행하고, 코드 변경 후 필요한 재빌드/검증을 확인하기 위한 운영 기준입니다.

## 기본 구성

`docker-compose.yml` 기준 로컬 서비스:

- `db`: PostgreSQL 16
- `migrate`: Alembic migration
- `api`: FastAPI
- `notice-poller`: 나라장터 변경공고 수집 Worker
- `master-data-import`: 기준정보 적재 Tool

Frontend는 `apps/web`에서 별도로 실행합니다.

## Shared DB · Current

팀 공용 개발 DB는 **Supabase PostgreSQL**을 사용합니다.

- 팀원은 공용 Supabase 연결 문자열을 `DATABASE_URL`에 설정해 같은 DB를 기준으로 작업할 수 있습니다.
- 연결은 Session/Pooler 기반으로 운영합니다.
- Discord 기준 공유 DB에는 migration **001~012**가 적용된 상태로 확인됐습니다.
- Backend에서 별도로 만든 migration은 공유 DB history와 같은 Alembic lineage로 재조정한 뒤 반영합니다.
- 자동 수집 Worker는 여러 환경에서 중복 실행하지 않도록 한 환경을 기준으로 운영합니다.

> 공용 DB가 존재한다는 것과 Production 배포 구조가 확정됐다는 것은 다른 의미입니다. 현재 Web/API Production Hosting은 TBD입니다.

## Backend 로컬 실행

```powershell
Copy-Item .env.example .env
docker compose up -d --build api notice-poller
docker compose ps
```

확인:

- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`

Backend 컨테이너는 build image 방식이므로 Backend 코드를 변경하면 다시 build 합니다.

```powershell
docker compose up -d --build api
```

Docker Desktop / daemon이 실행 중이어야 합니다.

## Migration

```powershell
docker compose run --rm migrate
```

또는 `api` 시작 시 migration service 완료를 기다리는 compose dependency를 사용합니다.

공용 Supabase에 새 migration을 적용할 때는:

1. 현재 공유 DB Alembic head 확인
2. 다른 담당자가 만든 migration 번호/parent 확인
3. 충돌 없이 하나의 lineage로 정리
4. 로컬/공유 DB regression 확인
5. 적용 후 팀에 head 상태 공유

순서를 지킵니다.

## Master Data

```powershell
docker compose --profile tools run --rm master-data-import
```

현재 업종/품목/기관 기준정보 적재에 사용합니다.

## Frontend 실행

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

기본 주소: `http://localhost:3000`

## 인증 · MVP Current

현재 데모는 **관리자 로그인** 기준으로 진행합니다.

Production 사용자 인증/권한 구조는 배포 구조와 함께 별도 확정합니다.

## 주요 환경변수

- PostgreSQL / Supabase: `DATABASE_URL`, 로컬 PostgreSQL 관련 값
- 나라장터: `G2B_SERVICE_KEY`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL_DEFAULT`
- Document Storage: `DOCUMENT_STORAGE_BACKEND`, `DOCUMENT_STORAGE_PATH`, S3 관련 값
- CORS: `CORS_ORIGINS`
- Notice polling: `NOTICE_POLL_*`

Secret은 `.env`에 두고 Commit하지 않습니다.

## Document Storage · Current / TBD

현재 첨부문서는 **LOCAL 저장**으로 운영합니다.

- 로컬 Docker 볼륨: `notice_documents_data`
- 로컬 DB 볼륨: `postgres_data`
- S3 / Supabase Storage 등 최종 첨부파일 저장소는 아직 TBD

컨테이너 재생성만으로 볼륨 데이터가 삭제되지는 않습니다. 데이터 초기화가 필요한 경우 볼륨 삭제는 별도 의도된 작업으로 취급합니다.

## MVP Demo / Golden 데이터

- 관리자 로그인으로 데모를 진행합니다.
- 특정 회사 1개에 맞춘 결과만 검증하지 않고 **합성 회사 Profile 여러 개**를 Golden Set에 사용합니다.
- 실제/합성 데이터 여부와 사용한 notice/company/version/run 식별자를 함께 기록합니다.

## 변경 후 확인

### Backend 변경
- image rebuild
- migration 필요 여부
- pytest
- Swagger/API regression

### Frontend 변경
- type check / lint
- build
- 주요 Route 확인

### AI 변경
- 기존 Golden regression
- 실제 Extraction sample
- Contract version/Schema 변경 여부
- Evidence/Guardrail drop diagnostic 영향

### DB 변경
- migration upgrade
- 공유 Supabase lineage 충돌 여부
- 기존 데이터 호환성
- API regression

## Known Gaps

- Web/API Production Hosting 구조
- Production 인증/권한
- 최종 첨부파일 저장소(S3/Supabase Storage 등)
- Secret 관리 방식
- Migration lineage reconciliation
- CI/CD와 배포 연결
- 장애 대응 / backup / restore
- 모니터링/로그
