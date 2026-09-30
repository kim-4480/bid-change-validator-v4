# bid-change-validator-v4

> 4차 프로젝트 — 나라장터 변경공고 대응형 입찰 제출 검증기 (구조 재설계판)

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하는 프로젝트입니다. 3차 레포(`gyuniverse-hq/bid-change-validator`)의 코드를 영역별로 나눠 이관하면서, 모델 성능 개선을 위해 파이프라인 구조를 다시 세웁니다. 결정 배경은 [ADR 0001](docs/adr/0001-structure.md)을 봅니다.

## 구조

| 경로 | 역할 | 담당 |
| --- | --- | --- |
| `apps/web/` | 웹 FE (반응형 + PWA로 모바일 지원) | FE |
| `apps/api/` | HTTP API, 인증, 영속화, 엔진 어댑터 | BE |
| `engine/` | 문서 모델 → 조항 열거 → LLM 라벨링 → 요건 → 판정·차수 비교, RAG, copilot | LLM |
| `eval/` | 골든셋, e2e·안정성 측정, eval 전용 DB | LLM |
| `contracts/` | web↔api(OpenAPI), api↔engine(JSON Schema) 계약 | 공동 승인 |
| `db/`, `data/` | 마이그레이션(단일 경로), 스키마, 마스터 코드·통제 어휘 | DB |
| `infra/`, `.github/` | 실행 환경, CI | 협업 인프라 |

## 의존 방향

```
web ──(generated types)──> contracts <── api ──(ports)──> engine <── eval
                                          │
                                          └──> db
```

역방향 import는 금지하며, CI에서 검사합니다.
