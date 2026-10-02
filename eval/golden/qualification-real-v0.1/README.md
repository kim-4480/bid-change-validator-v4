# Qualification Real Dataset v0.1

실제 공고의 고정 snapshot을 보관하는 Dataset입니다. **모델 성능 Golden Set이나 승인된 정답 데이터가 아닙니다.**
`qualification-quality-v0.1`은 합성 Harness fixture이며 이 디렉터리와 독립적입니다.
기존 `quality_eval` loader/CLI에 이 manifest를 입력하지 않습니다.

| Case | 공고번호 | 등급 | Identity | 문서 레코드 |
| --- | --- | --- | --- | --- |
| G2 | R26BK01686455 | PRODUCT_GOLDEN | VERIFIED | 8 (v1/000 → v2/001) |
| C04 | R26BK01687395 | PRODUCT_GOLDEN | VERIFIED | 6 (v1/000) |
| C01 | R26BK01705963 | SOURCE_GOLDEN | PARTIAL | 3 |
| C02 | R26BK01715895 | SOURCE_GOLDEN | PARTIAL | 3 |
| C03 | R26BK01716363 | SOURCE_GOLDEN | PARTIAL | 3 |

VERIFIED는 확보한 DB snapshot에서 identity를 확인했다는 의미입니다. 실시간 DB 조회나 semantic label 승인을 의미하지 않습니다.
SOURCE_GOLDEN의 notice/document/version UUID와 version_number는 null입니다. `document_key`는 로컬 문서 식별용 키이고 DB ID가 아닙니다.
source order 000은 다운로드 URL의 공고차수이며 DB version_number를 추정하지 않습니다.

## 저장과 provenance

`manifest.json` → `cases/<case>/case.json` → `documents/<hash>.txt`, `<hash>.blocks.json`으로 연결합니다.
같은 Case 안에서 내용이 같은 text/blocks는 한 번만 저장하지만 DB 문서 레코드는 삭제하지 않습니다.
문서 metadata에 snapshot의 parser, 추출 상태, URL 및 기존 해시를 보존합니다.
DB 문서의 historical parser version은 확보되지 않았습니다. Source 문서의 parser version은 export 시점의 재추출 기록입니다.

원본 바이너리 23개는 기존 `exports/golden-candidates-2026-09-10/` snapshot에 보관하며 Git에 중복 추가하지 않습니다.
각 문서의 `source_snapshot_path`는 **외부 snapshot 루트 기준**입니다. Dataset 내부 참조인 `text.path`, `blocks.path`와 구분합니다.
외부 snapshot은 별도 공유해야 하며 Git clone만으로 원본 파일을 재파싱할 수는 없습니다.
snapshot ZIP SHA-256: `1029cabcc5a2ff6b072c60b85ca1eca82153a5bb08131d6e9cd37f6ba61d6600`.
원본 export의 SHA256SUMS.txt 38개 항목과 ZIP 해시를 검증했습니다.
Case provenance에는 원본 metadata 파일 경로와 해시를 기록합니다. 원본 snapshot을 수정하지 않습니다.

해시는 다음처럼 구분합니다.

- `source_file_sha256`: 외부 원본 binary bytes.
- `extracted_text_sha256`: snapshot이 보유한 원래 extracted text의 UTF-8 bytes. text 파일에 그대로 보존.
- `blocks_file_sha256`: 이 Dataset에 저장한 blocks JSON 파일 bytes. blocks 객체의 내용은 snapshot과 동일.

23개 중 20개 문서는 blocks를 newline join한 값과 원래 text 해시가 다릅니다. 손상을 뜻하지 않으며 원본 해시를 교체하지 않습니다.
향후 Adapter가 필요하면 `reconstructed_text_sha256`를 별도로 계산해야 합니다.
`.gitattributes`로 checkout 시 개행 변환을 막습니다. 수정본은 기존 v0.1을 덮어쓰기보다 새 Dataset 버전으로 발행합니다.

## G2 observation

`cases/G2/observations/source-change.json`은 `candidate_removed` / `DRAFT` 관찰입니다.
baseline `f44f265d-f1a3-4463-99ac-399aef98d69b` (v1/000)의 문서
`c17fc7f6-eca6-4ca0-afef-86efe376a431`, PDF 6페이지 / block_index 5 / ‘2. 입찰 참가자격’ 2)에 강원도 본점 제한 문언이 있습니다.
current `c9d11d84-816b-4a95-ae9c-90e73f5de7e7` (v2/001)의 대응 문서는
`f0790ad7-01ed-48ac-bd45-ccf246d8ee84`입니다.
current 첨부 4개에서 공백 정규화한 동일 문언이 확인되지 않습니다.
동일 문언 부재는 의미상 요건 삭제의 확정이 아닙니다. 다른 위치나 표현 및 법적 효력은 사람이 검수해야 합니다.
`expected_change_type` 정답과 APPROVED label은 생성하지 않았습니다.

## 검증

저장 스키마는 `apps/api/app/scripts/validate_real_golden_dataset.py`의 Pydantic 모델입니다.
DB/Core/Harness import 없이 실행하며 체크섬 목록, 경로 containment, UUID/null 정책, 중복 ID,
문서-버전 연결, text/blocks 해시, G2 위치/첨부 coverage를 검사합니다.

```bash
python -m apps.api.app.scripts.validate_real_golden_dataset --dataset samples/golden/qualification-real-v0.1
python -m apps.api.app.scripts.validate_real_golden_dataset --dataset samples/golden/qualification-real-v0.1 --snapshot exports/golden-candidates-2026-09-10
pytest apps/api/tests/test_real_golden_dataset.py -q
```

첫 명령은 Git에 저장된 파일만 검증합니다. 두 번째 명령은 sibling ZIP과 외부 원본 23개, snapshot text/blocks도 비교합니다.
`checksums.sha256`는 자신을 제외한 Dataset 전체 파일을 포함합니다. checksum은 변조 탐지용이며 외부 서명은 아닙니다.
Backend 테스트는 기존 conftest의 DB fixture를 사용하므로 격리된 테스트 DB에서 실행합니다.

## 다음 Adapter PR

nullable identity, selection-only evaluation, 원래 text와 재구성 text의 hash 구분을 처리해야 합니다.
사람이 Source/Canonical label을 검수한 후 점수 산출을 연결합니다.
Judgment/Change/Risk label과 execution run ID는 현재 Harness 밖의 별도 계약 검토가 필요합니다.
DB/API/Core 변경, LLM 실행, 합성 회사 생성, Harness 실행은 이번 Dataset 범위에 포함하지 않습니다.
