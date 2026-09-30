# 나라장터 변경공고 대응형 입찰 제출 검증기 — DB ERD

DB / Data 담당: 정예린 · SKN34 3rd 4team · bid-change-validator
근거: models.py · analysis_models.py · judgment_models.py · ask_back_models.py · revalidation_models.py + 라이브 Supabase DB 대조 (information_schema, 30개 테이블)

> 마이그레이션 010~022 반영 완료 (기존 버전은 009 기준이었음)

## 전체 흐름 (도메인 지도)

```mermaid
flowchart LR
    A["① 공고·버전·원문 문서"] --> C["③ 참가자격 검토 Case"]
    B["② 회사 프로필"] --> C
    C --> D["④ 자격요건 분석·판정"]
    D --> E["⑤ 재검증 · Ask-back"]
    A -. "공고 변경 발생 시" .-> E
    A --> F["⑥ 계약조항 검토"]
```

⑦ 인증(로그인 · 세션)은 회사 프로필과 연결되지만 이 검증기 도메인 흐름과는 독립적이라 위 흐름도에는 표시하지 않음 — 아래 도메인별 섹션에서만 다룸.

---

## ① 공고 · 버전 · 원문 문서 (8개 테이블)

### 1-A. 공고 원문 · 버전 · 첨부문서

```mermaid
erDiagram
    BID_NOTICES ||--o{ BID_NOTICE_VERSIONS : has
    BID_NOTICE_VERSIONS ||--o{ NOTICE_DOCUMENTS : has

    BID_NOTICES {
        uuid id PK
        string bid_notice_no UK
        string title
        string business_type "CHECK 제약"
        string notice_kind "NULL 허용"
        string announcing_institution_code
        string announcing_institution_name
        string demanding_institution_code
        string demanding_institution_name
        timestamptz first_seen_at
        timestamptz last_seen_at
        timestamptz created_at
        timestamptz updated_at
    }
    BID_NOTICE_VERSIONS {
        uuid id PK
        uuid notice_id FK "→ bid_notices"
        int version_number
        string bid_notice_order "g2b 차수 순번(000~)"
        bool is_current "공고당 1개만"
        string notice_kind "선택"
        string registration_type "선택"
        bool is_reannouncement "재공고 여부(단순 플래그)"
        timestamptz posted_at
        timestamptz changed_at
        timestamptz bid_started_at
        timestamptz bid_closed_at
        timestamptz opened_at
        numeric allocated_budget
        numeric estimated_price
        string contract_method
        string change_reason
        string detail_url "선택"
        string source_endpoint
        string payload_hash "복합 UNIQUE: notice_id+payload_hash"
        jsonb raw_json
        timestamptz collected_at
        timestamptz created_at
    }
    NOTICE_DOCUMENTS {
        uuid id PK
        uuid notice_version_id FK "→ bid_notice_versions"
        int document_order
        string name
        string url
        string source_field "복합 UNIQUE: notice_version_id+source_field"
        string download_status "PENDING/DOWNLOADED/FAILED"
        string storage_key "선택"
        string content_type "선택"
        int file_size_bytes "선택"
        string file_sha256
        timestamptz downloaded_at "선택"
        text download_error "선택"
        string extraction_status "PENDING/EXTRACTED/EMPTY/UNSUPPORTED/FAILED"
        text extracted_text
        jsonb extracted_blocks "선택"
        int extracted_char_count "선택"
        string extracted_text_sha256 "선택"
        string text_extractor "선택"
        timestamptz extracted_at "선택"
        text extraction_error "선택"
        timestamptz created_at
    }
    NOTICE_COLLECTION_RUNS {
        uuid id PK
        string business_type
        string inquiry_type "REGISTERED/CHANGED/NOTICE_NUMBER"
        timestamptz window_started_at "선택"
        timestamptz window_ended_at "선택"
        string status "RUNNING/COMPLETED/FAILED"
        int api_calls
        int fetched_count
        int created_count
        int new_version_count
        int unchanged_count
        text error_message
        timestamptz started_at
        timestamptz completed_at "선택"
        int failed_item_count
    }
```

### 1-B. 공고 변경이력 · 연관관계 (재공고 매칭 · 백필 · 사실 추출)

```mermaid
erDiagram
    BID_NOTICES ||--o{ NOTICE_CHANGE_HISTORIES : "changes"
    BID_NOTICE_VERSIONS |o--o{ NOTICE_CHANGE_HISTORIES : "changes (opt)"
    BID_NOTICE_VERSIONS ||--o{ NOTICE_FACTS : "facts"
    NOTICE_DOCUMENTS |o--o{ NOTICE_FACTS : "evidence (opt)"
    BID_NOTICES ||--o| NOTICE_HISTORY_BACKFILL_JOBS : "backfill (1:1)"
    BID_NOTICES ||--o| NOTICE_RELATIONS : "this notice (1:1)"
    BID_NOTICES |o--o{ NOTICE_RELATIONS : "previous notice (opt, self-ref)"

    BID_NOTICES { uuid id PK "위 1-A 참고" }
    BID_NOTICE_VERSIONS { uuid id PK "위 1-A 참고" }
    NOTICE_DOCUMENTS { uuid id PK "위 1-A 참고" }

    NOTICE_CHANGE_HISTORIES {
        uuid id PK
        uuid notice_id FK "→ bid_notices"
        uuid notice_version_id FK "→ bid_notice_versions, NULL 허용"
        string bid_notice_order
        string rebid_number
        timestamptz changed_at
        string change_data_type
        string item_name
        text before_value
        text after_value
        string business_division_name "선택"
        string source_endpoint
        string payload_hash "복합 UNIQUE: notice_id+payload_hash"
        jsonb raw_json
        timestamptz collected_at
        timestamptz created_at
        timestamptz updated_at
    }
    NOTICE_FACTS {
        uuid id PK
        uuid notice_version_id FK "→ bid_notice_versions"
        string fact_key "복합 UNIQUE: notice_version_id+fact_key"
        jsonb value_json
        string source_type
        string source_field "선택"
        text raw_value "선택"
        uuid document_id FK "→ notice_documents, NULL 허용"
        jsonb evidence_location
        text quote
        timestamptz created_at
        timestamptz updated_at
    }
    NOTICE_HISTORY_BACKFILL_JOBS {
        uuid id PK
        uuid notice_id FK "→ bid_notices, UNIQUE(1:1)"
        string status
        int attempts
        timestamptz next_attempt_at
        text last_error
        timestamptz started_at "선택"
        timestamptz completed_at "선택"
        timestamptz created_at
        timestamptz updated_at
    }
    NOTICE_RELATIONS {
        uuid notice_id PK "FK → bid_notices, 1:1"
        uuid previous_notice_id FK "→ bid_notices, NULL 허용, self-ref"
        string previous_bid_notice_no
        string match_method
        string match_confidence
        timestamptz created_at
        timestamptz updated_at
    }
```

### ① 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `bid_notices` (PK id) | bid_notice_no (UNIQUE) · title · business_type (CHECK: SERVICE/GOODS/CONSTRUCTION/FOREIGN/OTHER) · notice_kind (선택) · announcing_institution_code/name · demanding_institution_code/name · first_seen_at · last_seen_at · created_at · updated_at |
| `bid_notice_versions` (PK id) | notice_id→bid_notices · version_number · bid_notice_order · is_current · notice_kind(선택) · registration_type(선택) · is_reannouncement · posted_at/changed_at · bid_started_at/bid_closed_at/opened_at · allocated_budget · estimated_price · contract_method · change_reason · detail_url(선택) · source_endpoint · payload_hash · raw_json · collected_at · created_at. 제약: UNIQUE(notice_id, version_number) · UNIQUE(notice_id, bid_notice_order) · UNIQUE(notice_id, payload_hash) · is_current은 공고당 1개만(부분 유니크 인덱스) · is_reannouncement는 단순 bool 플래그이고 실제 원공고 연결은 notice_relations가 담당 |
| `notice_documents` (PK id) | notice_version_id→bid_notice_versions · document_order · name · url · source_field · download_status(PENDING/DOWNLOADED/FAILED) · storage_key(선택) · content_type(선택) · file_size_bytes(선택) · file_sha256 · downloaded_at(선택) · download_error(선택) · extraction_status(PENDING/EXTRACTED/EMPTY/UNSUPPORTED/FAILED) · extracted_text · extracted_blocks(선택) · extracted_char_count(선택) · extracted_text_sha256(선택) · text_extractor(선택) · extracted_at(선택) · extraction_error(선택) · created_at. 제약: UNIQUE(notice_version_id, source_field) |
| `notice_collection_runs` (PK id) | business_type · inquiry_type(REGISTERED/CHANGED/NOTICE_NUMBER) · window_started_at/window_ended_at(선택) · status(RUNNING/COMPLETED/FAILED) · api_calls · fetched/created/new_version/unchanged/failed_item_count · error_message · started_at · completed_at(선택). 다른 테이블을 참조하지 않는 독립 로그 테이블 |
| `notice_change_histories` (PK id) | notice_id→bid_notices · notice_version_id→bid_notice_versions(nullable) · bid_notice_order · rebid_number · changed_at · change_data_type · item_name · before_value/after_value · business_division_name · source_endpoint · payload_hash · raw_json · collected_at · created_at · updated_at. 제약: UNIQUE(notice_id, payload_hash) — g2b 변경이력 원문 저장 |
| `notice_facts` (PK id) | notice_version_id→bid_notice_versions · fact_key · value_json · source_type · source_field · raw_value · document_id→notice_documents(nullable) · evidence_location · quote · created_at · updated_at. 제약: UNIQUE(notice_version_id, fact_key) |
| `notice_history_backfill_jobs` (PK id) | notice_id→bid_notices · status · attempts · next_attempt_at · last_error · started_at/completed_at · created_at · updated_at. 제약: UNIQUE(notice_id) — 공고당 백필 작업 1건(1:1) |
| `notice_relations` (PK notice_id) | notice_id→bid_notices(PK=FK, 1:1) · previous_notice_id→bid_notices(nullable, self-ref) · previous_bid_notice_no · match_method · match_confidence · created_at · updated_at. 재공고 ↔ 원공고 자동 연결 — befBidBbancNo 매칭 결과 |

---

## ② 회사 프로필 (9개 테이블)

### 2-A. 기본 프로필 · 조직 구성

```mermaid
erDiagram
    COMPANIES ||--o{ COMPANY_INDUSTRIES : has
    COMPANIES ||--o| COMPANY_STAFF : has
    COMPANIES ||--o{ COMPANY_STAFF_ROLES : has
    COMPANIES ||--o{ COMPANY_SW_ENGINEER_GRADES : has
    COMPANIES ||--o| COMPANY_QUAL_COMPLETENESS : has

    COMPANIES {
        uuid id PK
        string name
        string business_registration_number UK
        string region_code
        string region_name
        string company_size
        timestamptz created_at
        timestamptz updated_at
        bool conglomerate_affiliate "대기업 계열 여부"
    }
    COMPANY_INDUSTRIES {
        uuid company_id PK "FK → companies"
        string industry_code PK "FK → industry_codes(외부 코드표)"
        bool verified
        timestamptz created_at
    }
    COMPANY_STAFF {
        uuid company_id PK "FK → companies, 1:1"
        int total_count
        bool verified
        timestamptz updated_at
    }
    COMPANY_STAFF_ROLES {
        uuid company_id PK "FK → companies"
        string role_name PK
        int headcount
        numeric career_years
        bool verified
        timestamptz created_at
        timestamptz updated_at
    }
    COMPANY_SW_ENGINEER_GRADES {
        uuid company_id PK "FK → companies"
        string grade PK "SW기술자 등급"
        int headcount
        bool verified
        timestamptz created_at
        timestamptz updated_at
    }
    COMPANY_QUAL_COMPLETENESS {
        uuid company_id PK "FK → companies, 1:1"
        bool region_complete
        bool company_size_complete
        bool industries_complete
        bool staff_total_complete
        bool staff_roles_complete
        bool performances_complete
        bool certifications_complete
        timestamptz created_at
        timestamptz updated_at
    }
```

### 2-B. 실적 · 인증 (증빙 이력)

```mermaid
erDiagram
    COMPANIES ||--o{ COMPANY_PERFORMANCES : has
    COMPANY_PERFORMANCES ||--o{ COMPANY_PERFORMANCE_FIELDS : has
    COMPANIES ||--o{ COMPANY_CERTIFICATIONS : has

    COMPANIES { uuid id PK "위 2-A 참고" }

    COMPANY_PERFORMANCES {
        uuid id PK
        uuid company_id FK "→ companies"
        string name
        string client_name "선택"
        string client_institution_code FK "→ institution_codes(외부 코드표), 선택"
        numeric amount
        date started_at
        date completed_at
        text description "선택"
        bool verified
        timestamptz created_at
        timestamptz updated_at
        int completed_year
    }
    COMPANY_PERFORMANCE_FIELDS {
        uuid performance_id PK "FK → company_performances"
        string field_name PK
        timestamptz created_at
    }
    COMPANY_CERTIFICATIONS {
        uuid id PK
        uuid company_id FK "→ companies"
        string name
        string certification_code "코드표 매칭용"
        string certificate_number
        string issuer_name
        date issued_at
        date expires_at
        bool verified
        timestamptz created_at
        timestamptz updated_at
    }
```

### ② 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `companies` (PK id) | name · business_registration_number(UNIQUE) · region_code/region_name · company_size · created_at · updated_at · conglomerate_affiliate |
| `company_industries` (PK company_id+industry_code) | company_id→companies · industry_code→industry_codes · verified · created_at |
| `company_staff` (PK company_id) | company_id→companies · total_count · verified · updated_at (1:1) |
| `company_staff_roles` (PK company_id+role_name) | company_id→companies · headcount · career_years · verified · created_at · updated_at |
| `company_sw_engineer_grades` (PK company_id+grade) | company_id→companies · grade · headcount · verified · created_at · updated_at |
| `company_performances` (PK id) | name · client_name(선택) · company_id→companies · client_institution_code→institution_codes(선택) · amount · started_at/completed_at · description(선택) · verified · created_at · updated_at · completed_year |
| `company_performance_fields` (PK performance_id+field_name) | performance_id→company_performances · created_at |
| `company_certifications` (PK id) | name · certification_code · company_id→companies · certificate_number · issuer_name · issued_at/expires_at · verified · created_at · updated_at |
| `company_qualification_profile_completeness` (PK company_id) | company_id→companies · region/company_size/industries/staff_total/staff_roles/performances/certifications_complete (1:1) · created_at · updated_at |

---

## ③ 참가자격 검토 Case (2개 테이블)

```mermaid
erDiagram
    COMPANIES |o--o{ PREFLIGHT_CASES : "owns (opt)"
    BID_NOTICES ||--o{ PREFLIGHT_CASES : reviews
    BID_NOTICE_VERSIONS |o--o{ PREFLIGHT_CASES : "baseline (opt)"
    BID_NOTICE_VERSIONS ||--o{ PREFLIGHT_CASES : current
    PREFLIGHT_CASES ||--o{ PROPOSAL_DOCUMENTS : has

    COMPANIES { uuid id PK "외부: ② 회사 프로필" }
    BID_NOTICES { uuid id PK "외부: ① 공고" }
    BID_NOTICE_VERSIONS { uuid id PK "외부: ① 공고" }

    PREFLIGHT_CASES {
        uuid id PK
        uuid company_id FK "→ companies, NULL 허용(SET NULL)"
        uuid notice_id FK "→ bid_notices"
        uuid baseline_version_id FK "→ bid_notice_versions, NULL 허용"
        uuid current_version_id FK "→ bid_notice_versions"
        string title
        string status "DRAFT/READY/PROCESSING/COMPLETED/FAILED"
        timestamptz created_at
        timestamptz updated_at
    }
    PROPOSAL_DOCUMENTS {
        uuid id PK
        uuid case_id FK "→ preflight_cases"
        int document_order
        string role "PROPOSAL/ATTACHMENT"
        string name
        string storage_status "STORED/FAILED"
        string storage_key
        string content_type "선택"
        int file_size_bytes
        string file_sha256
        timestamptz stored_at
        text storage_error "선택"
        string extraction_status
        text extracted_text "선택"
        jsonb extracted_blocks "선택"
        int extracted_char_count "선택"
        string extracted_text_sha256 "선택"
        string text_extractor "선택"
        timestamptz extracted_at "선택"
        text extraction_error "선택"
        timestamptz created_at
    }
```

### ③ 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `preflight_cases` (PK id) | company_id→companies(nullable, SET NULL) · notice_id→bid_notices · baseline_version_id→bid_notice_versions(nullable) · current_version_id→bid_notice_versions · title · status(DRAFT/READY/PROCESSING/COMPLETED/FAILED) · created_at · updated_at. 주의: baseline_version_id가 NULL이거나 current_version_id와 같으면 변경 비교가 성립하지 않음(J13~J16 시드에서 실제로 겪은 문제) |
| `proposal_documents` (PK id) | case_id→preflight_cases · document_order · role(PROPOSAL/ATTACHMENT) · name · storage_status(STORED/FAILED) · storage_key · content_type(선택) · file_size_bytes · file_sha256 · stored_at · storage_error(선택) · extraction_status · extracted_text(선택) · extracted_blocks(선택) · extracted_char_count(선택) · extracted_text_sha256(선택) · text_extractor(선택) · extracted_at(선택) · extraction_error(선택) · created_at. 제약: UNIQUE(case_id, file_sha256) · UNIQUE(case_id, document_order) |

---

## ④ 자격요건 분석 · 판정 (5개 테이블)

### 4-A. 자격요건 분석 (LLM 추출)

```mermaid
erDiagram
    BID_NOTICE_VERSIONS ||--o{ QUALIFICATION_ANALYSIS_RUNS : "analyzed by"
    QUALIFICATION_ANALYSIS_RUNS ||--o{ QUALIFICATION_REQUIREMENTS : extracts
    QUALIFICATION_ANALYSIS_RUNS ||--o{ QUALIFICATION_EVIDENCE : cites

    BID_NOTICE_VERSIONS { uuid id PK "외부: ① 공고" }

    QUALIFICATION_ANALYSIS_RUNS {
        uuid id PK
        uuid notice_version_id FK "→ bid_notice_versions"
        string contract_version
        string analysis_kind
        string status "SUCCEEDED/PARTIAL/FAILED"
        jsonb target_chunk_ids
        jsonb diagnostics
        timestamptz created_at
        jsonb dropped_requirements
    }
    QUALIFICATION_REQUIREMENTS {
        uuid id PK
        uuid analysis_run_id FK "→ qualification_analysis_runs"
        string requirement_key "복합 UNIQUE: analysis_run_id+requirement_key"
        string requirement_group_key "선택"
        string group_operator "선택"
        string type
        string operator "선택"
        jsonb value_json "선택"
        string unit "선택"
        numeric period_months "선택"
        jsonb scope
        bool required
        text raw
        numeric confidence
        jsonb evidence_keys
        timestamptz created_at
        string requirement_role
        string condition_complexity
    }
    QUALIFICATION_EVIDENCE {
        uuid id PK
        uuid analysis_run_id FK "→ qualification_analysis_runs"
        string evidence_key "복합 UNIQUE: analysis_run_id+evidence_key"
        string source_type
        string document_id "텍스트 저장, FK 아님"
        string notice_version_id "선택, 텍스트 저장"
        string case_id "선택, 텍스트 저장"
        string chunk_id "선택, 텍스트 저장"
        jsonb location
        text quote
        string source_sha256 "선택"
        string extracted_text_sha256 "선택"
        timestamptz created_at
    }
```

### 4-B. 참가자격 판정 (룰 기반)

```mermaid
erDiagram
    PREFLIGHT_CASES ||--o{ QUALIFICATION_JUDGMENT_RUNS : "judged in"
    QUALIFICATION_ANALYSIS_RUNS ||--o{ QUALIFICATION_JUDGMENT_RUNS : "based on"
    COMPANIES ||--o{ QUALIFICATION_JUDGMENT_RUNS : "profile of"
    BID_NOTICE_VERSIONS ||--o{ QUALIFICATION_JUDGMENT_RUNS : against
    QUALIFICATION_JUDGMENT_RUNS ||--o{ QUALIFICATION_JUDGMENTS : has

    PREFLIGHT_CASES { uuid id PK "외부: ③ Case" }
    COMPANIES { uuid id PK "외부: ② 회사 프로필" }
    BID_NOTICE_VERSIONS { uuid id PK "외부: ① 공고" }
    QUALIFICATION_ANALYSIS_RUNS { uuid id PK "위 4-A 참고" }

    QUALIFICATION_JUDGMENT_RUNS {
        uuid id PK
        uuid preflight_case_id FK "→ preflight_cases"
        uuid analysis_run_id FK "→ qualification_analysis_runs"
        uuid company_id FK "→ companies"
        uuid notice_version_id FK "→ bid_notice_versions"
        string overall_status "eligible/ineligible/insufficient_data"
        string rule_version
        date reference_date
        jsonb profile_snapshot
        string analysis_status
        timestamptz created_at
    }
    QUALIFICATION_JUDGMENTS {
        uuid id PK
        uuid judgment_run_id FK "→ qualification_judgment_runs"
        string judgment_key
        string requirement_key "복합 UNIQUE: judgment_run_id+requirement_key"
        string status "SATISFIED/UNSATISFIED/UNKNOWN"
        string basis_type "PROFILE/USER_ANSWER/NONE"
        string reason_code
        bool evidence_held
        bool requires_evidence
        jsonb profile_refs
        jsonb requirement_evidence_keys
        string rule_version "선택"
        timestamptz created_at
        string value_source
        string evidence_status
        string unknown_reason
    }
```

### ④ 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `qualification_analysis_runs` (PK id) | notice_version_id→bid_notice_versions · contract_version · analysis_kind · status(SUCCEEDED/PARTIAL/FAILED) · target_chunk_ids · diagnostics · created_at · dropped_requirements. 같은 버전에 여러 run 가능 — 추출 비결정성으로 run마다 결과가 달라질 수 있음(현재 확인 중, 재현님 PR#135로 상당부분 개선됨) |
| `qualification_requirements` (PK id) | analysis_run_id→qualification_analysis_runs · requirement_key · requirement_group_key(선택) · group_operator(선택) · type · operator(선택) · value_json(선택) · unit(선택) · period_months(선택) · scope · required · raw · confidence · evidence_keys · created_at · requirement_role · condition_complexity. 제약: UNIQUE(analysis_run_id, requirement_key) |
| `qualification_evidence` (PK id) | analysis_run_id→qualification_analysis_runs · evidence_key · source_type · document_id(텍스트, FK 아님) · notice_version_id(선택) · case_id(선택) · chunk_id(선택) · location · quote · source_sha256(선택) · extracted_text_sha256(선택) · created_at. 제약: UNIQUE(analysis_run_id, evidence_key) |
| `qualification_judgment_runs` (PK id) | preflight_case_id→preflight_cases · analysis_run_id→qualification_analysis_runs · company_id→companies · notice_version_id→bid_notice_versions · overall_status(eligible/ineligible/insufficient_data) · rule_version · reference_date · profile_snapshot · analysis_status · created_at |
| `qualification_judgments` (PK id) | judgment_run_id→qualification_judgment_runs · judgment_key · requirement_key · status(SATISFIED/UNSATISFIED/UNKNOWN) · basis_type(PROFILE/USER_ANSWER/NONE — 문서근거·귀사답변 구분) · reason_code(RULE_MATCH/RULE_MISMATCH/INSUFFICIENT_DATA/NEEDS_REVIEW/UNSUPPORTED_REQUIREMENT) · evidence_held · requires_evidence · profile_refs · requirement_evidence_keys · rule_version(선택) · created_at · value_source · evidence_status · unknown_reason. 제약: UNIQUE(judgment_run_id, requirement_key) |

---

## ⑤ 재검증 · Ask-back (2개 테이블)

```mermaid
erDiagram
    PREFLIGHT_CASES ||--o{ QUALIFICATION_ANSWERS : "ask-back for"
    QUALIFICATION_JUDGMENT_RUNS ||--o{ QUALIFICATION_ANSWERS : "source run"
    PREFLIGHT_CASES ||--o{ QUALIFICATION_REVALIDATION_RUNS : "revalidated in"
    QUALIFICATION_JUDGMENT_RUNS ||--o{ QUALIFICATION_REVALIDATION_RUNS : "source/result"
    QUALIFICATION_ANALYSIS_RUNS ||--o{ QUALIFICATION_REVALIDATION_RUNS : "baseline/current"

    PREFLIGHT_CASES { uuid id PK "외부: ③ Case" }
    QUALIFICATION_JUDGMENT_RUNS { uuid id PK "외부: ④ 분석·판정" }
    QUALIFICATION_ANALYSIS_RUNS { uuid id PK "외부: ④ 분석·판정" }

    QUALIFICATION_ANSWERS {
        uuid id PK
        uuid preflight_case_id FK "→ preflight_cases"
        uuid source_judgment_run_id FK "→ qualification_judgment_runs"
        uuid result_judgment_run_id FK "→ qualification_judgment_runs, NULL 허용"
        string requirement_key "복합 UNIQUE: source_judgment_run_id+requirement_key"
        jsonb answer_json
        string normalized_value "선택"
        bool evidence_held
        bool apply_to_profile
        timestamptz created_at
    }
    QUALIFICATION_REVALIDATION_RUNS {
        uuid id PK
        uuid preflight_case_id FK "→ preflight_cases"
        uuid source_judgment_run_id FK "→ qualification_judgment_runs"
        uuid result_judgment_run_id FK "→ qualification_judgment_runs"
        uuid baseline_analysis_run_id FK "→ qualification_analysis_runs"
        uuid current_analysis_run_id FK "→ qualification_analysis_runs"
        jsonb changes
        jsonb revalidated_keys
        timestamptz created_at
    }
```

### ⑤ 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `qualification_answers` (PK id) | preflight_case_id→preflight_cases · source_judgment_run_id→qualification_judgment_runs · result_judgment_run_id→qualification_judgment_runs(nullable) · requirement_key · answer_json · normalized_value(선택) · evidence_held · apply_to_profile · created_at. 제약: UNIQUE(source_judgment_run_id, requirement_key) |
| `qualification_revalidation_runs` (PK id) | preflight_case_id→preflight_cases · source/result_judgment_run_id→qualification_judgment_runs · baseline/current_analysis_run_id→qualification_analysis_runs · changes · revalidated_keys · created_at |

---

## ⑥ 계약조항 검토 (2개 테이블 · 신규 편입)

```mermaid
erDiagram
    BID_NOTICE_VERSIONS ||--o{ CONTRACT_CLAUSE_REVIEW_RUNS : reviews
    CONTRACT_CLAUSE_REVIEW_RUNS ||--o{ CONTRACT_CLAUSE_FINDINGS : finds

    BID_NOTICE_VERSIONS { uuid id PK "외부: ① 공고" }

    CONTRACT_CLAUSE_REVIEW_RUNS {
        uuid id PK
        uuid notice_version_id FK "→ bid_notice_versions"
        string status
        timestamptz created_at
    }
    CONTRACT_CLAUSE_FINDINGS {
        uuid id PK
        uuid review_run_id FK "→ contract_clause_review_runs"
        string category "대표 분류 1개 — 필터·집계·인덱스용"
        string rule_id
        string risk_type "대표 위험유형 1개 — 필터·집계·인덱스용"
        jsonb risk_types "같은 조항에서 탐지된 위험유형 전부 — 화면 표시용, risk_types[0]=risk_type"
        jsonb categories "같은 조항에서 탐지된 분류 전부 — 화면 표시용, categories[0]=category"
        string detection_method
        string matched_via
        string verdict
        text reason
        text matched_text
        string rfp_clause_label
        string rfp_chunk_id
        text rfp_excerpt
        jsonb rfp_value
        jsonb standard
        string form
        timestamptz created_at
    }
```

### ⑥ 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `contract_clause_review_runs` (PK id) | notice_version_id→bid_notice_versions · status · created_at |
| `contract_clause_findings` (PK id) | review_run_id→contract_clause_review_runs · category · rule_id · risk_type · risk_types · categories · detection_method · matched_via · verdict · reason · matched_text · rfp_clause_label/rfp_chunk_id/rfp_excerpt/rfp_value · standard · form · created_at. category/risk_type(단일)과 categories/risk_types(배열, jsonb)는 컬럼 전환 중이 아니라 용도가 다름(재현님 확인, 9/15) — 단수는 대표 분류 1개로 필터·집계·인덱스용, 복수는 같은 조항에서 함께 탐지된 분류 전부로 화면 표시용. categories[0]=category, risk_types[0]=risk_type이 코드로 강제됨. 화면 표시는 복수, 검색·통계는 단수 사용 |

---

## ⑦ 인증 (2개 테이블 · 이 ERD 핵심 범위 밖, 참고용)

```mermaid
erDiagram
    COMPANIES |o--o{ APP_USERS : "employs (opt)"
    APP_USERS ||--o{ AUTH_SESSIONS : sessions

    COMPANIES { uuid id PK "외부: ② 회사 프로필" }

    APP_USERS {
        uuid id PK
        string username UK
        string password_hash
        string role
        bool active
        int failed_login_attempts
        timestamptz locked_until
        timestamptz created_at
        timestamptz updated_at
        uuid company_id FK "→ companies, NULL 허용"
    }
    AUTH_SESSIONS {
        uuid id PK
        uuid user_id FK "→ app_users"
        string token_hash UK
        timestamptz expires_at
        timestamptz revoked_at
        timestamptz created_at
    }
```

### ⑦ 테이블 참조

| 테이블 | 주요 컬럼 |
|---|---|
| `app_users` (PK id) | username(UNIQUE) · password_hash · role · active · failed_login_attempts · locked_until · created_at · updated_at · company_id→companies(nullable) |
| `auth_sessions` (PK id) | user_id→app_users · token_hash(UNIQUE) · expires_at · revoked_at · created_at |

---

## 다루지 않는 테이블

public 스키마 전체 34개 테이블 중 아래 4개는 도메인 다이어그램에 박스로 그리지 않았습니다. 존재는 라이브 DB(information_schema)로 확인했고, 코드표·인프라 성격이라 FK 코멘트로만 참조합니다.

- `industry_codes` · `institution_codes` — 업종/기관 코드표. company_industries.industry_code, company_performances.client_institution_code 등에서 참조.
- `product_codes` — 품목 코드표. 이번 ERD의 21+9개 테이블 어디에서도 직접 FK로 참조하지는 않아 연결 지점은 별도 확인 필요.
- `alembic_version` — 마이그레이션 버전 관리용 시스템 테이블, 도메인 데이터 아님.
