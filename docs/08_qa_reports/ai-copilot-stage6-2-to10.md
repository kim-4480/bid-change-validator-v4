# AI Copilot Stage 6-2 → 10

검증일: 2026-09-11. Branch: `feature/ai-copilot`.
기준 HEAD: `d35d2aa5f83a0ae72ffc26ed614ddf392f44b47e`. 변경은 미커밋 상태.

## 구현

| Stage | 결과 |
| --- | --- |
| 6-2 | 읽기 전용 ActionProposal과 명시적 confirm 분리. 기존 Ask-back 서비스 재사용 |
| 7 | `POST /api/v1/copilot/chat`, `POST /api/v1/copilot/actions/confirm` 추가 |
| 8 | 로컬 persisted Golden fixture로 판정→UNKNOWN→원문→제안→확인→새 판정 검증 |
| 9 | 기존 Requirement Diff 재사용. baseline/current provenance, affected-only 재검증, replay 거부 |
| 10 | 검토 완료: LangGraph 보류. 현재 stateless Router→Tool 처리에 graph/checkpoint 불필요 |

Qualification Rule, Judgment 서비스, `app/ai/**`, Document RAG/Citation 구현 및 DB Schema는 변경하지 않았다.
새 의존성, migration, frontend, 자동 프로필 변경은 추가하지 않았다.

## API Contract

Chat 요청의 필수 필드는 `case_id`, `message`다. 선택 필드는 `intent`, `requirement_key`,
`user_input`, `public_document_question`, `allow_external_processing`이다.
의도 분류는 제한된 한국어 keyword routing이며 explicit intent로 읽을 Tool을 지정할 수 있다.
인식된 참가자격 질문과 requirement_key가 있는 근거 질문은 Product Tool을 우선한다.
명시적인 사용자 입력 없이 자연어에서 충족 여부를 추론하거나 답변을 저장하지 않는다.

응답은 `answer`, `intent`, `product_state`, `citations`, `sources`, `actions`, `warnings`,
`external_processing_used`, `external_processing_scope`를 포함한다.
Product state는 기존 persisted 결과다. LLM은 이 필드를 생성하지 않는다.
Canonical evidence는 `source_origin=PRODUCT_EVIDENCE`와 원본 `Evidence` 객체를 반환한다.
Document RAG는 `source_origin=DOCUMENT_RAG`와 기존 `GroundedCitation` metadata를 반환한다.
Copilot V0는 답변 LLM을 호출하지 않는다. 검색된 Source의 ID·문서명·조항·위치를
서버가 결정론적으로 안내하고 원문 quote는 Source metadata로 제공한다.
모든 검색 Source를 안내문에서 인용하므로 이 경로의 citations와 sources는 동일하다.
검색 결과가 없으면 citations/sources 모두 비우고 근거가 없다고 응답한다.
두 경로 모두 `sources`와 실제 사용한 `citations`를 구분한다.

Confirm 요청은 `{ "confirmed": true, "action": <chat의 proposal> }`이다.
문자열 true, 숫자 1, false는 승인으로 인정하지 않는다.
Ask-back 입력은 명시적 boolean `satisfies_requirement`, `evidence_held`, 선택 `normalized_value`다.
`apply_to_profile=true`는 허용하지 않는다.
서명된 승인 토큰은 사용하지 않는다. Confirm은 사용자가 제출한 입력을 현재 DB와 다시 검증하는 API다.
제안 자체가 인증 증명이나 변경 불가능한 서버 기록인 것은 아니다.

Confirm은 case row lock을 획득하고 최신 DB를 읽어 기대한 company/version/analysis/judgment/rule 문맥과 비교한다.
Ask-back은 기존 `answer_and_rejudge`, 재검증은 `run_qualification_revalidation`만 호출한다.
기존 서비스의 profile/rule/askability 검증도 그대로 적용된다.
재검증 기대 문맥에 nullable current judgment ID를 포함하므로 첫 실행 후 같은 proposal의 replay는 거부된다.
재검증은 baseline 판정에서 새 current 판정을 만드는 작업이며, 기존 current 판정에 답변을 합치는 작업이 아니다.
오래된 제안을 성공한 것처럼 응답하는 idempotency는 제공하지 않는다.

## 외부 처리

기본값은 외부 호출 없음이다. Document QA는 별도의 `public_document_question`과
`allow_external_processing=true`가 모두 필요하다. 일반 `message`, 회사 profile,
Ask-back `user_input`은 embedding/답변 모델로 전달하지 않는다.
별도 질문 필드에는 공개 공고문 질의만 입력해야 한다. 이 필드의 내용에 개인정보가 없는지
자동으로 증명하는 DLP 기능은 없다.

현재 case version의 기존 FAISS index를 사용하며 Hybrid+Post, fetch_k=12, final k=4다.
index가 없으면 기존 서비스가 현재 버전의 문서 index를 생성한다.
`DOCUMENT_RAG_INDEX_ROOT` 기본값은 `data/document-rag`다.
캐시 저장은 파일 쓰기이며 chat의 DB write 금지와 구분한다.
Embedding은 기존 OpenAI 설정을 사용한다. 이번 검증에서는 실제 OpenAI 호출을 하지 않았다.
Stage 5의 생성형 Grounded Answer는 변경하지 않았고 별도 baseline으로 유지한다.

## 실행 결과

Windows, Python 3.12.10, 프로젝트 `.venv` 사용.
DB는 환경값으로 **127.0.0.1 PostgreSQL**에 명시적으로 연결했다.
원격 Supabase에 fixture나 판정을 쓰지 않았다. fixture는 테스트 후 기존 cleanup으로 삭제한다.

작업 디렉터리 `apps/api`:

```text
python -m pytest -q -p no:cacheprovider --tb=short tests/test_copilot_flow.py tests/test_copilot_product_tools.py tests/test_document_rag_answer.py tests/test_document_rag_store.py
67 passed, 1 warning in 13.02s

python -m pytest -q -p no:cacheprovider --tb=short
264 passed, 1 warning in 28.54s
```

Warning은 기존 Starlette TestClient의 anyio BlockingPortal deprecation이다.
새 `test_copilot_flow.py` 16개, 기존 Product Tool 19개, Document RAG 32개가 관련 테스트에 포함된다.

검증한 경계:

- Chat/proposal에서 pending caller 변경이 있어도 SQL SELECT만 수행, commit/flush 금지.
- 저장된 overall status와 canonical evidence의 원문·locator 유지.
- Ask-back 후 기존 판정 보존, 새 판정 생성, 해당 요건만 USER_ANSWER 적용.
- expected company/version/analysis/judgment 변조 시 신규 판정 없음.
- 최신 분석 변경, profile 변경, non-askable, cross-version evidence 거부.
- strict confirm 및 profile 변경 입력 거부.
- fake embedding + 실제 FAISS Hybrid로 sources/citations S1/S2와 locator 검증.
- 답변 LLM 호출 금지, 빈 검색 결과의 abstention 확인.
- 일반 message/회사명/사용자 답변이 embedding payload에 없음.
- Product 질문과 canonical evidence가 explicit DOCUMENT_QA보다 우선.
- 변경공고 API read/confirm, 실적 요건만 affected 재검증, 동일 proposal replay 거부.
- 변경된 baseline/current analysis 및 cross-version evidence로 재검증 시 신규 lineage 없음.

## 직접 협의 및 잔여 한계

연결된 ChatGPT `AI 챗봇 기획 설계`와 직접 협의했다.
Proposal/confirm 분리, expected context 방식, 별도 baseline/current provenance,
deterministic routing, LangGraph 보류 허용, 재검증 replay guard,
별도 공개 질문/외부처리 opt-in Contract를 승인받아 반영했다.

최종 ChatGPT 리뷰는 생성형 `grounded.answer`를 그대로 노출하는 1건을 Blocking으로 지적했다.
Copilot V0의 문서 답변을 결정론적 원문 안내로 제한하라는 수정 요청을 반영했다.
LLM 호출 자체가 불필요해 제거했고 기존 Document RAG 코드는 유지했다.
나머지 구조와 Stage 10 보류는 승인되었다.

키워드 라우팅은 모든 자연어를 포괄하지 않는다. Stage 12에서 paraphrase/intent 평가가 필요하다.
Document QA는 검색된 원문을 안내하며 관련성을 보장하거나 자연어 결론을 생성하지 않는다.
기존 Stage 5 생성형 Grounded Answer의 prompt 기반 안전성 한계를 Copilot V0에 노출하지 않는다.
실제 모델/브라우저 E2E, 동시 확인 stress test는 이번 실행 범위에 포함하지 않았다.
인증/인가 체계는 기존 API와 동일하며 사용자별 접근통제는 별도 제품 과제다.
LangGraph는 여러 Tool 분기, 지속 상태, 중단 후 resume이 실제로 필요해질 때 다시 검토한다.

`exports/`는 변경·staging하지 않았다. commit/push는 수행하지 않았다.
