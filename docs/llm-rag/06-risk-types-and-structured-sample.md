# 위험조항 최종 목록 및 구조화 결과 샘플

> 팀 공유용 · 2026-09-10

## 결론

위험조항의 최종 공유 목록은 **9종**입니다. 기존 8종에서 지체상금을 서로 다른 기준과
비교하는 두 항목으로 분리하면서 `LATE_PENALTY_RATE`가 추가되었습니다.

1. `WARRANTY_PERIOD` — 하자담보 기간
2. `LATE_PENALTY` — 지체상금 상한
3. `LATE_PENALTY_RATE` — 지체상금 요율
4. `COPYRIGHT_OWNERSHIP` — 저작권·지식재산권 귀속
5. `ACCEPTANCE_CRITERIA` — 검사·검수
6. `SCOPE_AMBIGUITY` — 과업범위 모호·포괄조항
7. `TERMINATION_CONDITION` — 계약해지 요건
8. `PAYMENT_TERMS` — 대금지급
9. `LIABILITY_SCOPE` — 손해배상

`LATE_PENALTY`와 `LATE_PENALTY_RATE`는 합치면 안 됩니다. 상한은 계약예규의 상한 조문,
일별 요율은 국가계약법 시행규칙 제75조의 계약 종류별 요율과 비교하므로 근거와 판정이
독립적입니다.

내부 검사 `warranty_bond_rate`의 한글 `risk_type`은 별도로 유지하고, 그룹핑 오류 코드는
`category=WARRANTY_PERIOD`를 사용합니다. 따라서 오류 코드 목록은 최종 9종을 유지합니다.

## 실제 구조화 결과 샘플

캐시된 실제 공사 공고 `R26BK01716363`에서 추출·판정한 `LATE_PENALTY_RATE` 결과입니다.
공고 특수조건의 `1/1,000`을 `0.1%`로 정규화하고, 시행규칙의 공사 기준
`1천분의 0.5`(`0.05%`)와 비교한 결과입니다.

```json
{
  "risk_type": "지체상금 요율 과다",
  "risk_types": ["지체상금 요율 과다"],
  "category": "LATE_PENALTY_RATE",
  "categories": ["LATE_PENALTY_RATE"],
  "label": "지체상금 요율 과다",
  "rule_id": "penalty_rate",
  "verdict": "NEEDS_REVIEW",
  "verdict_label": "확인 필요",
  "reason": "공고 값이 표준(지연 1일당 계약금액의 100분의 0.05)을 초과",
  "matched_text": null,
  "clause_label": "제22조",
  "chunk_id": "CHUNK-0315",
  "excerpt": "제22조(지체상금의 특칙) ① 지체상금은 계약금액을 기준으로 지체1일당 1/1,000로 산정한다. ② 분담이행방식으로 체결된 공동계약의 경우 공동수급체의 각 구성원은 지체상금 납부의무에 대하여 연대책임을 지므로 각 구성원은 상호 긴밀히 협조하여 공사를 완공하여야 한다. …",
  "notice_value_raw": "1/1,000로 산정한다",
  "notice_value": 0.1,
  "standard": {
    "clause_ref": "국가계약법 시행규칙 제75조제1호",
    "description": "지연 1일당 계약금액의 100분의 0.05",
    "value_raw": "1천분의 0.5",
    "text_excerpt": "제75조(지체상금률) … 1. 공사: 1천분의 0.5 …"
  },
  "drift": null
}
```

코드 기준 원본은 `apps/api/app/ai/clause_review/contracts.py`의 `CategoryCode`와
`CATEGORY_BY_RULE`입니다.
