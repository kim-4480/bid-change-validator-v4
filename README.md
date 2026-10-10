# bid-change-validator-v4

> 4차 프로젝트 — 나라장터 변경공고 대응형 입찰 제출 검증기 (구조 재설계판)

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하는 프로젝트입니다. 3차 레포(`gyuniverse-hq/bid-change-validator`, `develop` 112a8e3)의 코드를 영역별로 나눠 옮겼고, 모델 성능 개선을 위해 파이프라인 구조를 다시 세우는 중입니다. 결정 배경과 단계별 계획은 [ADR 0001](docs/adr/0001-structure.md)을 봅니다.

## 구조

| 경로 | 역할 | 담당 |
| --- | --- | --- |
| `apps/web/` | 웹 FE (반응형 + PWA로 모바일 지원 예정) | FE |
| `apps/api/` | HTTP API, 인증, 영속화, 공고 수집기 | BE |
| `apps/api/app/copilot/`, `apps/api/app/document_rag/` | copilot 오케스트레이션, RAG 인덱스 로딩 (DB 연결부) | LLM |
| `engine/bidengine/` | 추출·라벨링·요건·판정·차수 비교·RAG 코어. **DB·API를 import하지 않음** | LLM |
| `eval/` | 골든셋(`golden/`), 측정 라이브러리(`bideval/`), 실행기(`runners/`) | LLM |
| `contracts/` | web↔api OpenAPI 계약 | 공동 승인 |
| `db/`, `data/` | 스키마·시드·기준정보 수집 스크립트, 마스터 코드, 표준 예규 원본 | DB |
| `infra/`, `.github/` | 실행 환경, CI | 협업 인프라 |
| `docs/` | 문서. `docs/adr/`이 현재 결정, 나머지는 3차 문서 스냅샷 | 각 영역 |

### 엔진 내부 (파이프라인 순서)

```
document/      원문 블록, 청킹
labeling/      LLM 요건 추출, 코드 구제
requirements/  canonical 변환, 중복 제거, legacy slot 어댑터
grounding/     근거 어댑터
judgment/      결정론 판정(rules.py), askability, clause_safety
diff/          차수 비교
pipeline/      분석 파이프라인 조립, 결과 모델
rag/           문서 청크 저장소, 검색, 근거 답변
clause_review/ 계약조항 표준 대조
clauses/, vocab/  (예정) 코드 주도 조항 열거, 통제 어휘
```

### 의존 방향

```
web ──(HTTP)──> api ──> engine <── eval
                 │
                 └──> db
```

`engine/tests/test_engine_boundary.py`가 엔진의 역방향 import를 막습니다. `Zone guard` 워크플로는 PR이 바꾼 영역과 파일 수를 알려 주기만 하고 실패시키지 않습니다(2026-10-08부터, develop → main 통합 PR은 검사하지 않음).

## 개발 환경

Python 3.12, Node 22, pnpm 10, PostgreSQL 16이 필요합니다.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements-dev.txt   # 저장소 루트에서. 엔진·측정 패키지(-e engine -e eval) 포함
```

### 테스트

```bash
# 엔진 (DB 불필요)
(cd engine && python -m pytest -q tests)

# 측정: 테스트와 골든 회귀 게이트
(cd eval && python -m pytest -q tests)
python eval/runners/run_golden_regression.py --out artifacts/golden_regression.json

# API (PostgreSQL 필요)
export DATABASE_URL=postgresql+psycopg://bidjigi:bidjigi_local_password@localhost:55432/bidjigi
export PYTHONPATH=$PWD
(cd apps/api && python -m alembic upgrade head)
python -m pytest -q apps/api/tests

# 웹
(cd apps/web && pnpm install && pnpm test && pnpm build)
```

### 로컬 실행

이 Compose 구성은 2026-10-08 복원된 **기존 PostgreSQL 17 볼륨**을 요구합니다. 빈 볼륨으로 새 DB를 만들지 않습니다. 전환/롤백과 데이터 볼륨 확인은 [PostgreSQL 17 로컬 Compose 운영 절차](docs/07_handoff/pg17-compose-persistence.md)를 먼저 읽어주세요. `.env.example`을 `.env`로 복사해 값을 채운 뒤 실행합니다. API 이미지는 저장소 루트를 빌드 컨텍스트로 써서 엔진 패키지를 함께 설치합니다.

```bash
docker compose up -d --build api
# 수집이 필요한 경우에만, 중복 실행 여부를 확인한 뒤:
docker compose --profile collector up -d notice-poller
docker compose --profile tools run --rm master-data-import   # 기준정보 적재
cd apps/web && cp .env.example .env.local && pnpm install && pnpm dev
```

- API health: `http://localhost:18000/health`, Swagger: `http://localhost:18000/docs`
- 웹: `http://localhost:3000`

API 목록과 화면 흐름 등 3차 README의 상세 내용은 [docs/legacy/README-v3.md](docs/legacy/README-v3.md)에 그대로 남겨 두었습니다. 경로는 3차 기준이니 위 구조 표와 대조해서 읽어 주세요.
