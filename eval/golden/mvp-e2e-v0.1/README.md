# MVP E2E Golden Path v0.1

> Purpose: one deterministic integration fixture that proves the product path end-to-end. This is **evaluation/integration data**, not training data.

## Scenario

A synthetic Seoul small company reviews a public-sector IT notice.

Initial company facts:

- Region: Seoul
- Company size: `SMALL`
- Staff: 8 total, including 5 developers
- One recent public-sector information-system performance worth KRW 500,000,000
- Certification/registration profile is intentionally incomplete

Baseline notice v1 contains four qualification conditions:

1. Seoul company → expected `SATISFIED`
2. 5+ developers → expected `SATISFIED`
3. recent 3-year performance >= KRW 400,000,000 → expected `SATISFIED`
4. `정보통신공사업` registration → expected `UNKNOWN` because certification/registration profile completeness is unknown

The user answers the Ask-back question that the company holds `정보통신공사업` registration. Only requirement 4 is re-judged with `basis_type=USER_ANSWER`, becoming `SATISFIED`.

Changed notice v2 modifies only the performance threshold from KRW 400,000,000 to KRW 600,000,000. Requirement Diff should identify only the performance requirement as `MODIFIED`. Revalidation should re-run that requirement only, producing `UNSATISFIED`; unchanged requirements reuse/preserve their prior judgment context.

## Expected journey

```text
Company Profile
  + Notice v1
  ↓
Requirement Analysis
  ↓
REGION                SATISFIED
STAFF                 SATISFIED
PERFORMANCE_AMOUNT    SATISFIED
REGISTRATION_CERT     UNKNOWN
  ↓
Ask-back: 정보통신공사업 등록 보유 여부
  ↓ yes
REGISTRATION_CERT     SATISFIED (USER_ANSWER)
  ↓
Overall: eligible
  ↓
Notice v2 detected
  ↓
Requirement Diff: PERFORMANCE_AMOUNT MODIFIED 400M → 600M
  ↓
Affected-only revalidation
  ↓
PERFORMANCE_AMOUNT    UNSATISFIED
  ↓
Overall: ineligible
```

## Fixture files

- `company-profile.json`: synthetic company facts plus fixture-only completeness metadata
- `requirements-v1.json`: baseline canonical requirements
- `requirements-v2.json`: changed-notice canonical requirements
- `expected-events.json`: expected judgment / Ask-back / diff / revalidation events

## Contract rules this fixture locks

- `UNKNOWN` means missing comparison information, not LLM execution failure.
- A user answer can become `basis_type=USER_ANSWER` without rerunning document extraction/RAG.
- Notice changes are compared at Canonical Requirement level.
- Only affected requirements are re-judged when the company profile and unrelated notice requirements are unchanged.
- Overall UI/API status is derived after requirement-level judgment; it does not replace canonical judgment status.

## Non-goals

This single fixture is not enough for model quality evaluation. It is the first integration golden path. Evaluation should later add multiple companies, notices, negative cases, ambiguous clauses, unsupported requirements, and evidence-grounding cases.
