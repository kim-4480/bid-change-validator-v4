# 청크 저장소 설계 초안 (러프)

> 작성 2026-09-09 · LLM / RAG
> **논의용 초안입니다.** 구현하지 않았고, 스키마는 확정이 아닙니다.
> `models.py`·마이그레이션은 DB 담당(정예린) 영역이라 합의 후에 만들어야 합니다.

## 왜 지금 이 이야기를 하나

RAG 를 제대로 하려면 청크를 어딘가 두어야 하는데, 그 전에 **지금 이미 깨져 있는 것**이
하나 있습니다.

## 0. RAG 와 무관하게 이미 문제인 것

청크는 **저장되지 않습니다.** 요청마다 `notice_documents.extracted_blocks`(JSONB)에서
새로 만듭니다. 그런데 `chunk_id` 는 위치 기반(`CHUNK-0004`)이고
`analysis_pipeline._build_global_chunks` 가 매번 다시 매깁니다.

그리고 그 id 가 **DB에 저장됩니다**:

```
qualification_analysis_runs.target_chunk_ids   ← 어떤 청크를 읽었는지
qualification_evidence.chunk_id                ← 근거가 어느 청크인지
```

즉 **청커를 한 줄만 고쳐도 저장된 감사 기록이 조용히 다른 곳을 가리키게 됩니다.**
로드맵의 청킹 개선(최소 크기 누적, 초과 블록 분할)을 하는 순간 과거 근거가 전부
어긋납니다. 지금은 청킹을 안 건드려서 안 터졌을 뿐입니다.

**그래서 청크 저장소의 1번 목적은 벡터가 아니라 안정적인 식별자입니다.**

## 1. 코퍼스가 두 개고 성격이 다릅니다

| | 공고 문서 청크 | 계약예규 조문 |
|---|---|---|
| 규모 | 공고당 약 330개, 계속 증가 | **221개 고정** |
| 수명 | 공고 버전마다 다시 생김 | 예규 개정 때만 |
| 질의 | 그 공고 안에서만 | 모든 조항 검토가 참조 |
| 지금 | 매번 재생성 | `data/standards/clauses.json` 파일 |

**예규는 DB로 옮길 이유가 없어 보입니다.** 221개면 파일로 충분하고, 지금 방식
(예규 원문에서 매번 기준값 추출)이 개정 대응에 유리합니다. 임베딩이 필요해지면
파일 옆에 캐시를 두면 됩니다.

**DB가 필요한 건 공고 청크 쪽입니다.**

## 2. 그런데 DB의 역할이 벡터 검색은 아닙니다

중요한 지점이라 따로 적습니다. **검색 범위가 공고 하나 안입니다.**

자격요건을 찾을 때도, 조항을 검토할 때도, 대상은 그 공고의 첨부 문서들입니다.
공고 하나가 약 330청크이고, 4,096차원 코사인 전수 계산은 **마이크로초**입니다.
ANN 인덱스가 풀어주는 문제가 지금은 없습니다.

그러면 저장소가 실제로 하는 일은:

1. **안정적인 식별자** — 위 0번. 이게 제일 큽니다
2. **임베딩 캐시** — 같은 문서를 다시 볼 때마다 임베딩 값을 다시 지불하지 않기
3. **평가 재현성** — 골든셋이 특정 청크를 가리킬 수 있어야 함
4. (나중에) 공고 간 검색 — "이 공고와 비슷한 과거 공고"

1~3은 평범한 테이블로 됩니다. **4가 생길 때만 pgvector 이야기가 의미 있습니다.**
지금 이미지는 `postgres:16-alpine` 이라 pgvector 가 없고, 넣으려면
`pgvector/pgvector:pg16` 으로 바꾸는 인프라 변경이 필요합니다.

## 3. 러프한 스키마

```sql
-- 청크: 문서에서 파생되지만 안정적으로 참조 가능해야 한다
notice_document_chunks
  id                  uuid pk
  notice_document_id  uuid fk -> notice_documents
  chunking_version    text        -- 예: "chunk-v2". 청커가 바뀌면 새 버전으로 다시 생성
  chunk_index         int         -- 문서 내 순서
  content_hash        text        -- sha256(정규화 텍스트). 재생성해도 같으면 같은 청크
  clause_label        text null
  text                text
  char_count          int
  source_blocks       jsonb       -- page/section/paragraph 로케이터 보존
  created_at          timestamptz
  unique (notice_document_id, chunking_version, chunk_index)
  index on (content_hash)

-- 임베딩: 청크 × 모델. 캐시 성격이라 언제든 지우고 다시 만들 수 있다
notice_chunk_embeddings
  chunk_id    uuid fk -> notice_document_chunks
  model       text        -- "text-embedding-3-small" / "ngram-4096"
  dim         int
  vector      jsonb       -- float 배열. pgvector 도입 전까지
  created_at  timestamptz
  unique (chunk_id, model)
```

### 왜 `content_hash` 인가

`chunk_index` 만으로는 청커를 고치는 순간 의미가 달라집니다. 내용 해시를 같이
두면 재생성 후에도 "같은 내용의 청크"를 알아볼 수 있고, 감사 기록이 살아남습니다.
`chunking_version` 은 옛 버전 청크를 지우지 않고 남겨둬서 과거 분석을 그대로
재현할 수 있게 하는 장치입니다.

### 왜 `vector` 를 jsonb 로 두나

pgvector 가 없어서이기도 하지만, **지금 규모에서 ANN 이 필요 없기 때문**입니다.
공고 하나 범위의 전수 계산이면 jsonb 에서 읽어 파이썬에서 코사인 계산해도 충분합니다.
공고 간 검색이 실제로 필요해지면 그때 `vector(1536)` 컬럼으로 옮기고 인덱스를 겁니다
— 그때는 이미지 교체가 정당화됩니다.

### 저장하지 않기로 한 것

- **청크별 요약** — 요약은 매번 조금씩 다르고, 캐시했다가 원문이 바뀌면 어긋납니다
- **판정 결과** — 이미 `qualification_judgment_runs` 에 있습니다
- **예규 조문** — 위 1번. 파일이 낫습니다

## 4. 단계와 발동 조건

무엇을 언제 만들지를 조건으로 묶어둡니다. 지금 다 만들면 쓰지도 않을 테이블이
스키마에 남습니다.

| 단계 | 무엇 | 언제 |
|---|---|---|
| 0 | **아무것도 안 만듦** | 지금. 측정 하네스(로드맵 1번)가 먼저 |
| 1 | `notice_document_chunks` | **청킹을 고치기 직전에.** 안 만들고 고치면 감사 기록이 어긋남 |
| 2 | `notice_chunk_embeddings` | 밀집 임베딩을 실제로 쓰기로 했을 때 (로드맵 4.7 발동 조건) |
| 3 | pgvector 전환 | 공고 간 검색이 필요해졌을 때 |

**1번이 실질적으로 가장 먼저 올 가능성이 높습니다.** RAG 때문이 아니라 청킹 개선의
전제 조건이라서요.

## 5. 확인이 필요한 것

**정예린님께**
- 청크 테이블을 만든다면 공고 문서당 300~400행이 쌓입니다. 공고 1,000건이면 30~40만 행
  인데, 보관 정책(오래된 `chunking_version` 정리)을 어떻게 볼지
- `content_hash` 를 인덱스로 두는 게 맞는지, 아니면 `(document_id, chunking_version)`
  조합만으로 충분한지
- 임베딩을 jsonb 로 두는 것에 대한 의견 (pgvector 는 이미지 교체가 필요)

**전진환님께**
- 청크 생성을 언제 하는지 — 문서 추출 직후 미리 만들지, 분석 요청 때 만들지.
  전자면 `extract_pending_documents` 옆에 자리가 필요합니다

**공통**
- 지금 `target_chunk_ids` / `evidence.chunk_id` 가 불안정한 값이라는 것에 대한 합의.
  청킹을 고치기 전에 정리하지 않으면 과거 근거가 조용히 어긋납니다

## 6. 요약

- 청크 저장소의 첫 번째 이유는 **벡터가 아니라 안정적인 식별자**입니다
- 예규(221조문)는 DB로 옮길 이유가 없어 보입니다
- 검색 범위가 공고 하나 안이라 **ANN 인덱스는 아직 필요 없습니다**
- pgvector 는 공고 간 검색이 생길 때. 그전엔 jsonb + 전수 계산으로 충분
- **지금 만들 것은 없습니다.** 청킹을 고치기로 할 때 1단계가 같이 와야 합니다
