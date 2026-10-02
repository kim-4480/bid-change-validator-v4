# Stage 5-6 Retrieval Experiment

실행일: 2026-09-11 KST. 브랜치: `feature/ai-copilot`. 변경 전 commit: `64a5e50`.

**실험 완료.** 동일 공개 공고의 세 질문에서 근거 그룹 Recall@4가 Dense 33.3% → Hybrid 50.0% → 재정렬 포함 100%로 개선됐다. 기존 서비스는 Dense Baseline을 유지하며, 신규 함수는 명시적으로 호출하는 실험 경로다. 단일 공고의 개발 질문만으로 일반 품질을 보증하거나 자동 기본값 전환을 하지 않는다.

## 범위와 평가 기준

- notice_id: `5739772e-caef-47ce-8532-2bb39c7b0a90`
- notice_version_id: `9de1b445-d999-4278-8e11-2148e920f9bd`
- 공개 문서 3개, 원본 chunk 47개, 9,411자. 변경 전과 구현 검증의 모든 record를 대조했다.
- OpenAI `text-embedding-3-small`, 1,536차원, FAISS `IndexFlatIP`, final k=4.
- 실제 임베딩 호출: 문서 batch 1회 + 질문 3회 / 구현 검증 라운드. 동일 벡터를 모든 방식에서 재사용했다.
- 모델 payload에는 승인된 질문과 해당 공개 원문만 사용했다. 자격증명·Profile·Ask-back·사용자 제안서는 포함하지 않았다.
- DB 읽기 전용, 실제 FAISS 인덱스는 메모리에서만 생성했다.

문서 표기와 chunk ID는 다음 규칙을 사용한다. 예: `A0003`은 `44025f6b-03a2-4be7-b27c-ccd84877ecfc:CHUNK-0003`이다. 전체 ID·원문·locator·score는 [측정 JSON](ai-copilot-stage5-6-retrieval.json)에 보존했다.

| 표기 | document_id | document_name |
|---|---|---|
| A | 44025f6b-03a2-4be7-b27c-ccd84877ecfc | 01_입찰공고문_NMS_소프트웨어_개발_용역_초거대제조AI.pdf |
| S | e2e37ddc-7e9b-44cb-ba4e-22e86ab024fc | 표준공고문 |
| R | fd529eab-8b16-48b9-ac6a-adc597ed86a4 | 02_제안요청서_NMS_소프트웨어_개발_용역_초거대제조AI.pdf |

| 질문 | 원문 | 평가 근거 그룹 |
|---|---|---|
| Q1 | 실적 조건 근거가 어디야? | A0003/S0003 중 하나: 실적 요건 명시 |
| Q2 | 참가자격에 지역 제한이 있어? | A0003/S0003 중 하나 + R0027 |
| Q3 | 이 공고의 자격조건 관련 원문을 찾아줘. | A0003/S0003 중 하나 + R0027 |

Recall@4는 반환된 **관련 근거 그룹 수 / 사전 지정 근거 그룹 수**이며 표의 평균은 세 질문의 macro 평균이다. 동일 표준·첨부공고문은 하나의 그룹이다. 제출서류·평가항목의 간접 언급은 Q1의 직접 실적 자격요건으로 계산하지 않았다. Q2의 참가자격 조항 검색 성공은 공고 전체에 지역 제한이 없음을 확정하는 판정이 아니다. 문서 ID 기반 gold label은 평가 데이터에만 있고 검색 구현에는 없다.

## A. 변경 전 Baseline 보존

아래 값은 소스 변경 전에 측정한 실제 Top-4다. 이전 Stage 5-5와 chunk 순서가 같았다. API 재실행 간 일부 점수는 조금 달라졌으므로 원래 값을 덮어쓰지 않았다. JSON의 `baseline`에는 원문 47개, k=4/8/12/47 순위와 점수를 보존했다.

| 질문 | 변경 전 Top-4 (cosine) | 직접 관련 근거 순위 |
|---|---|---|
| Q1 | R0014 (0.367136), R0022 (0.330833), R0005 (0.318704), R0029 (0.312189) | Top-4 밖, 전체 11위 |
| Q2 | A0003 (0.409197), S0003 (0.409197), R0027 (0.367419), R0029 (0.310331) | 1위 |
| Q3 | R0004 (0.380473), R0003 (0.379117), R0014 (0.359744), R0030 (0.354788) | Top-4 밖, 전체 8위 |

평균 Recall@4 33.3%, 중복 1개, 목차/제목성 결과 5개. 단순 키워드나 제목 출현을 정답으로 세지 않았다.

## B. Dense + Post-processing

- Dense fetch_k=8과 12를 비교했다. 이 표본에서는 최종 4개가 같았다.
- 번호·제목 목록 형태와 본문 유무를 함께 확인하여 제목성 후보를 **후순위**로 보낸다. 짧다는 이유로 삭제하지 않는다.
- 서술·의무 표현, 불허·금액 비교·업체 조건 및 bullet 본문은 보호한다. 인덱스는 삭제하지 않으며 본문 후보가 부족하면 제목성 후보도 반환될 수 있다.
- NFKC + 공백 정규화가 동일한 원문은 document_id에 관계없이 한 번만 반환한다. 실제 내용이 다른 문장을 잘못 합치지 않도록 fuzzy similarity 제거는 도입하지 않았다. 숫자·부정 표현 차이는 보존한다.
- 처리 순서: fetch_k → 제목성 후보 후순위 → 정규화 동일문 중복 제거 → final k=4. 고유 후보가 부족하면 4개보다 적게 반환한다.

## C. Hybrid + Post-processing

B에서 Q1/Q3 실패가 남아 Hybrid를 실행했다. 한국어 복합어·조사를 부분 매칭하도록 단어 내부 문자 2·3-gram을 사용하고 영문·숫자는 토큰을 유지한다. BM25 k1=1.5, b=0.75와 동일 가중치 RRF 상수 60을 사용했다. Dense 상위 12개와 양의 BM25 점수를 가진 상위 최대 12개를 합친 뒤 같은 후처리를 적용한다. 외부 라이브러리나 질문별 가중치 조정은 없다.

Q3의 관련 본문은 2위로 올라왔지만 Q1은 여전히 계약조건·증빙서류 언급을 높게 평가했다. Hybrid만으로 목표를 충족하지 못했다.

## 조건부 재정렬 실험

Hybrid에서도 Q1이 실패한 뒤에만 재정렬을 실험했다. Hybrid 후처리 후보 최대 12개와 질문을 `gpt-5.6-luna`에 전달한다. 원문은 데이터로 취급하도록 지시하고 ID 순서만 반환받는다. 모든 후보 ID를 정확히 한 번씩 반환하는지 검증한다. 누락·중복·알 수 없는 ID·잘못된 JSON·API 오류는 실패로 전달하며, 범위를 넓히는 fallback은 없다.

프로토타입과 구현 검증 두 라운드 모두 세 질문의 직접 근거가 1위였지만 보조 결과 순서와 동일 문서 대표는 일부 달랐다. 반복 안정성에 대한 통계적 보증은 아니다. 재정렬은 수치 점수를 만들지 않으며 반환 `score`는 기존 RRF 점수라 최종 순서에서 단조 감소하지 않을 수 있다.

## 구현 후 실제 Query별 결과

아래는 반영된 `retrieval.py`를 실제 API 임베딩과 함께 실행한 결과다. Dense/Dense+Post 점수는 cosine, Hybrid 계열은 RRF 점수로 서로 크기를 비교하지 않는다. 모든 결과는 위의 동일 notice_version_id에 속한다.

### Query 1

실적 조건 근거가 어디야?

| 방식 | Top-4 (score) | relevant rank | Recall@4 | duplicate | navigation |
|---|---|---:|---:|---:|---:|
| Dense | R0014 (0.367136), R0022 (0.330956), R0005 (0.318708), R0029 (0.312189) | 없음 | 0% | 0 | 2 |
| Dense+Post (8) | R0022 (0.330956), R0029 (0.312189), R0028 (0.302920), R0013 (0.302702) | 없음 | 0% | 0 | 0 |
| Dense+Post (12) | R0022 (0.330956), R0029 (0.312189), R0028 (0.302920), R0013 (0.302702) | 없음 | 0% | 0 | 0 |
| Hybrid+Post | R0022 (0.032258), R0029 (0.030777), A0004 (0.030159), R0030 (0.029199) | 없음 | 0% | 0 | 0 |
| Hybrid+Post+Rerank | A0003 (0.027973), R0025 (0.014286), R0028 (0.015152), R0029 (0.030777) | 1 | 100% | 0 | 0 |

재정렬 결과 원문과 locator:

| rank | chunk | locator | 원문 일부 |
|---:|---|---|---|
| 1 | A0003 | p.2, p.3 | 2. 입찰참가자격 ○ 사업자등록증상 소프트웨어 개발·공급 또는 정보통신 관련 업종을 보유하고 본 용역을 수행할 수 있는 업체 3 ○ 공고일 현재 국가를 당사자로 하는 계약에 관한 법률 및 관계 법령에 따라 … |
| 2 | R0025 | p.8 | 3. 필수 포함사항 제안서에는 다음 사항이 포함되어야 한다. ○ NMS·네트워크 관제 소프트웨어 개발, SNMP/API 기반 장비 연동 또는 산업용 유·무선 통신망 모 니터링 시스템 구축 수행실적 ○ 기존 … |
| 3 | R0028 | p.8, p.9 | 3. 제안서 평가 방법 ○ 제안서 기술평가는 당사 자체 평가위원회가 당사 평가기준에 따라 100점 만점으로 실시한 후 90 점 만점으로 환산한다. 9 ○ 가격평가는 유효한 총액입찰가격을 기준으로 10점 만점… |
| 4 | R0029 | p.9 | 4. 제출서류 및 일정 ○ 제출서류 : 제안서, 가격제안서 및 산출내역서, 사업자등록증 사본, 유사 수행실적 증빙자료, 투입 인력 현황 및 기타 요구 증빙서류 ○ 제출기한 및 방법 : 나라장터 전자입찰 공고… |

### Query 2

참가자격에 지역 제한이 있어?

| 방식 | Top-4 (score) | relevant rank | Recall@4 | duplicate | navigation |
|---|---|---:|---:|---:|---:|
| Dense | A0003 (0.409197), S0003 (0.409123), R0027 (0.367419), R0029 (0.310331) | 1 | 100% | 1 | 0 |
| Dense+Post (8) | A0003 (0.409197), R0027 (0.367419), R0029 (0.310331), S0004 (0.290247) | 1 | 100% | 0 | 0 |
| Dense+Post (12) | A0003 (0.409197), R0027 (0.367419), R0029 (0.310331), S0004 (0.290247) | 1 | 100% | 0 | 0 |
| Hybrid+Post | A0003 (0.032266), R0027 (0.032002), R0023 (0.029274), R0029 (0.015625) | 1 | 100% | 0 | 0 |
| Hybrid+Post+Rerank | A0003 (0.032266), R0027 (0.032002), R0008 (0.014493), A0002 (0.014286) | 1 | 100% | 0 | 0 |

재정렬 결과 원문과 locator:

| rank | chunk | locator | 원문 일부 |
|---:|---|---|---|
| 1 | A0003 | p.2, p.3 | 2. 입찰참가자격 ○ 사업자등록증상 소프트웨어 개발·공급 또는 정보통신 관련 업종을 보유하고 본 용역을 수행할 수 있는 업체 3 ○ 공고일 현재 국가를 당사자로 하는 계약에 관한 법률 및 관계 법령에 따라 … |
| 2 | R0027 | p.8 | 2. 입찰참가 자격 ○ 입찰공고문에서 정한 참가자격을 충족하는 업체이어야 한다. ○ 사업자등록증상 소프트웨어 개발·공급 또는 정보통신 관련 업종을 보유하고 본 용역을 수행할 수 있어야 한다. ○ 기존 NMS… |
| 3 | R0008 | p.3, p.4 | 3. 사업개요 ○ 사업명 : 산업용 무선통신망 통합관제 NMS 소프트웨어 개발 용역 ○ 발주기관 : ㈜라임씨에스아이 ○ 개발대상 : 당사 NMS 기본 플랫폼(데이터 수집·저장, 사용자·권한, 기본 대시보드·… |
| 4 | A0002 | p.2 | 1. 사업개요 ○ 사 업 명 : 산업용 무선통신망 통합관제 NMS 소프트웨어 개발 용역 ○ 사업내용 - 당사 NMS 기본 플랫폼을 기반으로 중앙 관제 서버 연계 및 다수 수요기업(멀티사이트) 통합 운영 화면… |

### Query 3

이 공고의 자격조건 관련 원문을 찾아줘.

| 방식 | Top-4 (score) | relevant rank | Recall@4 | duplicate | navigation |
|---|---|---:|---:|---:|---:|
| Dense | R0004 (0.380195), R0003 (0.379069), R0014 (0.359744), R0030 (0.354788) | 없음 | 0% | 0 | 3 |
| Dense+Post (8) | R0030 (0.354788), R0021 (0.346644), R0026 (0.336903), R0024 (0.331569) | 없음 | 0% | 0 | 0 |
| Dense+Post (12) | R0030 (0.354788), R0021 (0.346644), R0026 (0.336903), R0024 (0.331569) | 없음 | 0% | 0 | 0 |
| Hybrid+Post | R0030 (0.031754), R0027 (0.031099), R0026 (0.030303), R0023 (0.028370) | 2 | 50% | 0 | 0 |
| Hybrid+Post+Rerank | A0003 (0.015873), R0027 (0.031099), R0029 (0.014493), S0004 (0.014085) | 1 | 100% | 0 | 0 |

재정렬 결과 원문과 locator:

| rank | chunk | locator | 원문 일부 |
|---:|---|---|---|
| 1 | A0003 | p.2, p.3 | 2. 입찰참가자격 ○ 사업자등록증상 소프트웨어 개발·공급 또는 정보통신 관련 업종을 보유하고 본 용역을 수행할 수 있는 업체 3 ○ 공고일 현재 국가를 당사자로 하는 계약에 관한 법률 및 관계 법령에 따라 … |
| 2 | R0027 | p.8 | 2. 입찰참가 자격 ○ 입찰공고문에서 정한 참가자격을 충족하는 업체이어야 한다. ○ 사업자등록증상 소프트웨어 개발·공급 또는 정보통신 관련 업종을 보유하고 본 용역을 수행할 수 있어야 한다. ○ 기존 NMS… |
| 3 | R0029 | p.9 | 4. 제출서류 및 일정 ○ 제출서류 : 제안서, 가격제안서 및 산출내역서, 사업자등록증 사본, 유사 수행실적 증빙자료, 투입 인력 현황 및 기타 요구 증빙서류 ○ 제출기한 및 방법 : 나라장터 전자입찰 공고… |
| 4 | S0004 | p.3 | 3. 제출서류 ○ 제안서(PDF) ○ 가격제안서 및 산출내역서 ○ 사업자등록증 사본 ○ 유사 수행실적 증빙자료 및 투입인력 현황 ○ 기타 입찰공고 및 제안요청서에서 요구하는 증빙서류… |

## 비교

| Metric | Dense | Dense+Post (12) | Hybrid+Post | Hybrid+Post+Rerank |
|---|---:|---:|---:|---:|
| Macro 근거 그룹 Recall@4 | 33.3% | 33.3% | 50.0% | 100% |
| 관련 근거 발견 질문 | 1/3 | 1/3 | 2/3 | 3/3 |
| Q1/Q2/Q3 최초 관련 순위 | 없음/1/없음 | 없음/1/없음 | 없음/1/2 | 1/1/1 |
| 중복 합계 | 1 | 0 | 0 | 0 |
| 제목성 결과 합계 | 5 | 0 | 0 | 0 |
| cross-version | 0 | 0 | 0 | 0 |

### Latency와 비용 경계

로컬 검색 시간은 질문 벡터를 캐시한 **31회 중앙값**이다. API 임베딩과 재정렬은 각 질문 1회 측정이며 31번 호출하지 않았다. 시간은 환경과 API 응답에 따라 달라진다. 인덱스 생성(문서 임베딩 포함)은 1.921초였다.

| Q | 질문 임베딩 API (ms) | Dense local (ms) | Post 8 local (ms) | Post 12 local (ms) | Hybrid local (ms) | 재정렬 포함, 질문 임베딩 제외 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 146.339 | 0.117 | 0.170 | 0.188 | 4.992 | 4758.959 |
| 2 | 155.282 | 0.077 | 0.174 | 0.276 | 6.696 | 5998.969 |
| 3 | 248.661 | 0.070 | 0.149 | 0.263 | 5.731 | 4261.976 |

구현 검증의 재정렬 API 3회 사용량: input 6122, output 1293, total 7415 tokens. 요금으로 환산하지 않았다. API 키가 있다는 이유만으로 새 함수가 자동 재정렬을 호출하지 않으며, `method="hybrid_rerank"`와 명시적인 client가 모두 필요하다.

## Tests

실행 디렉터리: `apps/api`. 기존 Python 3.12.10 가상환경, 로컬 테스트 PostgreSQL 사용. UTF-8 및 PYTHONPATH는 프로세스에만 설정하고 .env는 수정하지 않았다.

```text
python -m pytest -q -p no:cacheprovider --tb=short tests/test_document_rag_store.py tests/test_document_rag_answer.py
21 passed in 3.81s

python -m pytest -q -p no:cacheprovider --tb=short
218 passed, 1 warning in 12.65s
```

남은 경고는 기존 Starlette/anyio BlockingPortal deprecation이다. 변경 전 같은 실행은 RAG 6개, 전체 203개 통과했다.

추가 검사는 짧은 실질 조항 보존, 타 문서의 동일 원문 통합, 숫자·부정 조건 차이 보존, 제목 fallback, Dense 후보 밖 lexical 근거 검색, GroundedCitation 원문·페이지 보존, 재정렬 payload 제한, 잘못된 ID/JSON 거부, embedding/API 호출 전 버전·인자 검증을 포함한다.

실제 검증은 모든 반환 hit의 text와 전체 metadata를 원본 record와 대조했고, 재정렬 payload의 ID/본문도 승인된 47개 원문에 한정됨을 확인했다. 이 단계에서는 답변 LLM의 새 답변 품질을 재평가하지 않았다.

## 사용과 재현

기존 `VersionFaissIndex.search(query, k=4)`와 `service.search_document_chunks`는 그대로다. 실험 함수는 직접 import한다. Hybrid 검색에는 새 dependency가 필요 없다.

```python
from apps.api.app.document_rag.retrieval import retrieve

baseline = index.search(question, k=4)
post = retrieve(index, question, method="dense_post", fetch_k=12)
hybrid = retrieve(index, question, method="hybrid", fetch_k=12)
reranked = retrieve(
    index, question, method="hybrid_rerank", fetch_k=12,
    rerank_client=client, rerank_model="gpt-5.6-luna",
)
```

원격 호출 없이 보존된 변경 전 Dense 순위를 사용해 B/Hybrid를 재생하려면 저장소 루트에서 아래를 실행한다. 재정렬 응답 자체와 token usage는 JSON에 있으며, 모델 재호출은 동일한 순서를 보장하지 않는다.

```python
import json
from pathlib import Path
from types import SimpleNamespace
from apps.api.app.document_rag.store import DocumentChunkRecord, DocumentChunkHit
from apps.api.app.document_rag.retrieval import retrieve

report = json.loads(Path(
    "docs/08_qa_reports/ai-copilot-stage5-6-retrieval.json"
).read_text(encoding="utf-8"))
records = [DocumentChunkRecord.model_validate(r) for r in report["baseline"]["records"]]
by_id = {r.metadata.chunk_id: r for r in records}
for row in report["baseline"]["queries"]:
    def search(query, *, k):
        assert query == row["query"]
        saved = row["dense"].get(str(k), row["dense"]["47"])["hits"][:k]
        return [DocumentChunkHit(
            text=by_id[h["chunk_id"]].text,
            metadata=by_id[h["chunk_id"]].metadata, score=h["score"],
        ) for h in saved]
    replay = SimpleNamespace(
        notice_version_id=report["scope"]["notice_version_id"],
        records=records, search=search,
    )
    for method in ("dense_post", "hybrid"):
        hits = retrieve(replay, row["query"], method=method, fetch_k=12)
        print(row["query"], method, [(h.metadata.chunk_id, h.score) for h in hits])
```

실제 API 재검증은 동일 DB version에서 `build_notice_version_records`를 호출해 보존된 47개 record와 일치함을 확인한 뒤, `create_openai_embeddings(model="text-embedding-3-small")`와 `VersionFaissIndex.build`로 메모리 인덱스를 만든다. 키는 실행 환경/client에만 넣고 보고서나 문서 payload에 넣지 않는다. local DB 연결과 저장소 루트 PYTHONPATH, `PYTHONUTF8=1`, `PYTHONDONTWRITEBYTECODE=1`을 프로세스에 설정한다. 위 세 질문 이외의 실데이터 범위는 이 실험에 포함하지 않는다.

## 수정 파일과 판단

- `apps/api/app/document_rag/retrieval.py`: opt-in 후처리·BM25/RRF·재정렬과 경계 검증.
- `apps/api/tests/test_document_rag_store.py`: 위 동작과 Citation/Version 안전성 회귀 검사.
- 본 Markdown 및 JSON: 원래 Baseline, 입력 원문, 후보, 점수, 평가 그룹, prototype/구현 결과와 latency 보존.

Stage 5-6 실험은 완료 가능하다. 품질을 우선하는 호출에는 **Hybrid + Post + 명시적 Rerank**를 추천 후보로 남긴다. 재정렬 없이 세 질문을 모두 해결했다고 보고하지 않는다. 약 4.3–6.0초의 추가 대기와 토큰 비용이 있으므로 기존 서비스 기본값을 자동 교체하지 않았다.

Golden 질문/문서명/ID 하드코딩은 검색 구현에 없다. 다만 한국어 제목 휴리스틱과 한 공고의 세 개발 질문만으로 평가했으므로 과적합 위험이 없다고 단정할 수 없다. 다른 공개 공고와 새로운 질문의 hold-out 평가, 재정렬 지연·오류 예산을 확인한 뒤 서비스 기본값 채택을 결정한다. 절대형 주장이나 조건이 다른 문장을 합칠 수 있는 fuzzy dedup은 측정 근거 없이 추가하지 않았다. Qualification Rule, Judgment, app/ai Core, 기존 Citation 계약은 변경하지 않았다.
