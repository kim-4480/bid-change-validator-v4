# AI Retrieval · Current State / Upgrade Path

> **상태: Current Baseline + Proposed Experiments**  
> 기준: `develop`

이 문서는 현재 자격요건 추출 단계에서 실제로 어떤 후보 문맥을 선택하고 있으며, 어디부터가 향후 Retrieval 실험인지 구분합니다.

## 현재 사실

현재 `apps/api/app/ai/requirement_extraction.py`의 자격요건 후보선택은 **명시적인 Vector DB / Dense Retriever / Hybrid Retriever가 아닙니다.**

현재 흐름:

```text
Backend extracted_blocks
→ canonical source blocks
→ semantic chunks
→ eligibility section / keyword candidate selection
→ LLM structured extraction
→ source-grounding validation
→ deterministic normalization / canonical mapping
```

## 현재 후보선택 규칙

### 1. Section Anchor

다음과 같은 상위 제목을 우선 anchor로 찾습니다.

```text
참가자격
입찰참가
자격요건
참가 자격
신청자격
제한사항
```

상위 anchor가 발견되면 같은 문서 안에서 다음 top-level section 전까지의 child chunk를 함께 선택합니다.

### 2. Fallback Keyword

anchor가 없거나 다른 문서에 자격조건이 흩어진 경우 다음 유형의 키워드를 사용합니다.

```text
실적 / 면허 / 인증 / 등록 / 소재 / 지역 / 인력
업종 / 업태 / 경험 / 분야
소상공인 / 소기업 / 중소기업 / 중견기업 / 대기업
```

즉 현재 Retrieval baseline은 **section-aware + keyword fallback candidate selection**입니다.

## 현재 Extraction Context 제한

선택된 chunk 전체를 만들더라도 실제 structured extraction 입력은 최대 **32,000 characters**로 잘립니다.

```text
selected chunks
→ full body
→ first 32,000 chars
→ structured extractor
```

따라서 긴 공고/첨부가 많은 공고에서는 다음 문제가 평가 대상입니다.

- 뒤쪽 중요한 자격조건 누락
- 관련 없는 앞부분이 context budget을 점유
- 여러 문서의 자격조건 우선순위
- 표/복합조항/다중 첨부의 recall

## Grounding Validation

LLM 출력은 그대로 신뢰하지 않습니다.

현재 검증:

- `raw`가 실제 source chunk에 존재하는지
- 각 `*_raw` 세부 필드가 해당 source text에 존재하는지
- `근거조항`이 실제 chunk label 또는 source text와 맞는지

불일치하면 accepted requirement가 아니라 rejected/diagnostic으로 처리합니다.

이 때문에 Retrieval 개선은 단순히 “더 많은 chunk를 LLM에 넣기”가 아니라 **필요한 근거 chunk를 더 잘 선택하면서 grounding validation을 유지하는 방향**이어야 합니다.

## 현재와 Proposed를 구분

| 기능 | 상태 |
| --- | --- |
| Semantic Chunking | Current |
| Section/keyword candidate selection | Current |
| Structured Extraction | Current |
| Source-grounding validation | Current |
| Dense Embedding Retriever | Proposed / 실험 후보 |
| BM25 Retriever | Proposed / 실험 후보 |
| Hybrid Retrieval | Proposed / 실험 후보 |
| Reranker | Proposed / 실험 후보 |
| Vector DB | 미확정 선택지 |

Vector DB를 사용해야만 RAG라고 보는 식으로 기술 선택을 역으로 정하지 않습니다. 먼저 현재 baseline을 측정한 뒤 실패 유형에 맞춰 Retrieval을 추가합니다.

## 권장 Evaluation 순서

```text
Current section/keyword baseline
→ Golden requirement/evidence label
→ Retrieval Recall@K / requirement recall 측정
→ 실패 원인 분류
→ 필요한 경우 embedding/BM25 실험
→ hybrid 비교
→ reranker 필요성 판단
→ 최종 조합 결정
```

## 지표 후보

### Candidate Retrieval

- Recall@K
- MRR
- required source chunk hit rate
- irrelevant context ratio

### Requirement Extraction

- field-level precision / recall / F1
- missed requirement count
- false requirement count
- unmapped/rejected rate

### Evidence / Grounding

- citation/source support accuracy
- clause/location correctness
- hallucinated quote count

## 실험 시 지켜야 할 것

- 같은 Golden Set에서 baseline과 비교합니다.
- Retriever가 바뀌어도 Canonical Requirement/Evidence 외부 Contract를 불필요하게 깨지 않습니다.
- Retrieval 개선으로 grounding validation을 약화하지 않습니다.
- 임의 목표치(예: 95%)를 먼저 정하지 않고 baseline → failure analysis → target 순으로 정합니다.
- latency/token/cost는 정확도와 함께 기록합니다.

## `LLM` 브랜치의 Embedding 코드

기존 `LLM` 브랜치의 embedding provider는 **선별 이식 후보**이지 현재 `develop` Production Retrieval이라고 문서화하지 않습니다.

이식 전 확인:

- 최신 Core Contract와 호환되는가
- 현재 chunk locator/evidence provenance를 보존하는가
- 실제 Golden에서 section/keyword baseline보다 개선되는가
- 신규 dependency / 운영비 / latency가 합리적인가

## Owner 경계

현재 Proposed 역할분리 기준:

- **김재현 / AI Core**: Retrieval baseline 측정, Retriever 실험, Requirement/Evidence 품질
- **이홍규 / Copilot**: Retrieval 내부 구현을 직접 재구성하지 않고 Core/Product Contract를 소비

Copilot이 자체 Vector Store를 만들어 Qualification 근거를 별도로 검색하는 이중 구조는 피합니다.
