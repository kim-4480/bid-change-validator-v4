# LLM / RAG 문서

> 담당: 김재현, 이홍규 · 최종 갱신 2026-09-08

`LLM` 전용 브랜치에서 진행한 작업을 `integration/mvp-baseline` 으로 이식하면서
정리한 문서입니다.

| 문서 | 내용 |
|---|---|
| [01-branch-comparison.md](01-branch-comparison.md) | LLM 브랜치 ↔ Integration Baseline 비교. 겹치는 부분(판정기 24:19 측정 비교), 한쪽에만 있는 것, 이식/보류 결정과 근거 |
| [02-integration-requests.md](02-integration-requests.md) | **다른 담당 영역에 요청드릴 것 6건**과 **부득이하게 이미 수정한 것 6건** |
| [03-quality-roadmap.md](03-quality-roadmap.md) | Extraction · RAG · Rule · Eval 고도화. 실측 기반 우선순위와 검증 방법 |

## 지금 상태 한 줄 요약

이식 완료(계약조항 검토 + 예규 221조문 + 임베딩 + 요약 + 확장항목 + API필드 변환 +
DB 없는 첨부 수집), 테스트 108개 통과. 판정기는 Baseline 것을 채택하되 인증 명칭 대조
버그 1건을 이식했습니다.

**가장 급한 것**: 실제 공고에서 자격요건 8개 중 5개가 가드레일에 잘못 걸려 사라지고,
그중에 "대기업·중견기업 참여 제한"이 있어 **지금 대기업이 적격으로 나옵니다.**
→ [03-quality-roadmap.md](03-quality-roadmap.md) 2.1
