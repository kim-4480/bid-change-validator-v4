from bidengine.clause_review import detect_patterns


def _chunk(text: str, chunk_id: str = "CHUNK-0001", clause_label: str | None = "3.5") -> dict:
    return {"chunk_id": chunk_id, "clause_label": clause_label, "text": text}


def _forms(findings) -> list[str]:
    return [finding.form for finding in findings]


# ── the shapes a catch-all clause actually takes ─────────────────────────
def test_residual_pointer_with_a_discretionary_verb_is_caught() -> None:
    findings = detect_patterns(
        [_chunk("3.5 기타 발주기관이 요구하는 사항")]
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "open_ended_scope"
    assert findings[0].verdict == "NEEDS_REVIEW"
    assert findings[0].detection_method == "PATTERN_MATCH"
    assert findings[0].standard is None


def test_the_same_shape_is_caught_through_different_wording() -> None:
    # These are three different sentences with one shape between them. Catching
    # all three is the whole point of composing parts instead of memorising text.
    wordings = [
        "3.5 그 밖에 감독관이 지시하는 제반 사항",
        "3.5 상기 외 수요기관이 요청하는 업무",
        "3.5 이 외에 계약담당공무원이 정하는 내용",
    ]
    for wording in wordings:
        findings = detect_patterns([_chunk(wording)])
        assert findings, f"not detected: {wording}"
        assert findings[0].verdict == "NEEDS_REVIEW"


def test_authority_deeming_something_necessary_is_caught_on_its_own() -> None:
    findings = detect_patterns(
        [_chunk("3.5 수요기관이 필요하다고 인정하는 경우 추가 작업을 지시할 수 있다")]
    )

    assert findings
    assert "재량주체+필요인정" in _forms(findings)


def test_deferred_scope_is_caught_inside_a_work_scope_passage() -> None:
    findings = detect_patterns(
        [_chunk("3.5 세부 과업 내용은 추후 협의하여 정한다")]
    )

    assert "미확정 위임" in _forms(findings)


# ── guards against false positives ───────────────────────────────────────
def test_legal_boilerplate_is_not_a_scope_clause() -> None:
    # "등 일체의 …" only counts when what follows is scope wording. Liability
    # boilerplate uses the same connector and must not be reported.
    findings = detect_patterns(
        [_chunk("7.1 계약상대자는 과업 수행 중 발생한 손해배상 등 일체의 민·형사상 책임을 진다")]
    )

    assert findings == []


def test_ancillary_wording_outside_a_work_scope_passage_is_not_reported() -> None:
    findings = detect_patterns(
        [_chunk("첨부 문서에 부수되는 모든 자료는 별첨과 같다", clause_label="붙임")]
    )

    assert findings == []


def test_the_same_wording_inside_a_work_scope_passage_is_reported() -> None:
    findings = detect_patterns(
        [_chunk("3.6 본 과업에 부수되는 일체의 업무를 포함한다")]
    )

    assert findings
    assert "부수·수반 표현" in _forms(findings)


def test_attachment_forms_are_skipped_even_when_they_look_open_ended() -> None:
    findings = detect_patterns(
        [
            _chunk(
                "별지 서식 3호 관리대장\n기타 발주기관이 요구하는 사항\n년 월 일 확인자",
                clause_label="별지",
            )
        ]
    )

    assert findings == []


def test_an_ordinary_scope_item_produces_nothing() -> None:
    findings = detect_patterns(
        [
            _chunk("3.1 시스템 분석 및 설계"),
            _chunk("3.4 최종 산출물: 요구사항정의서, 설계서, 시험결과서"),
        ]
    )

    assert findings == []


# ── reporting shape ──────────────────────────────────────────────────────
def test_one_span_is_reported_once_even_when_two_shapes_match_it() -> None:
    # "기타 … 필요하다고 인정하여 요구하는 사항" satisfies both the residual shape
    # and the discretion shape over the same text; that is one problem.
    findings = detect_patterns(
        [_chunk("3.5 기타 발주기관이 필요하다고 인정하여 요구하는 사항")]
    )

    spans = {finding.matched_text for finding in findings}
    assert len(findings) == len(spans)
    assert len(findings) == 1


def test_findings_carry_their_location_and_the_notice_version() -> None:
    findings = detect_patterns(
        [_chunk("3.5 기타 발주기관이 요구하는 사항", chunk_id="CHUNK-0007", clause_label="3.5")],
        notice_version_id="nv-001",
    )

    finding = findings[0]
    assert finding.chunk_id == "CHUNK-0007"
    assert finding.clause_label == "3.5"
    assert finding.notice_version_id == "nv-001"
    assert finding.matched_text
    assert finding.excerpt
    assert finding.verdict_label == "확인 필요"


def test_every_chunk_is_reviewed_not_just_the_first() -> None:
    findings = detect_patterns(
        [
            _chunk("3.1 시스템 분석 및 설계", chunk_id="CHUNK-0001"),
            _chunk("3.5 기타 발주기관이 요구하는 사항", chunk_id="CHUNK-0002"),
            _chunk("3.6 본 과업에 부수되는 일체의 업무", chunk_id="CHUNK-0003"),
        ]
    )

    assert {finding.chunk_id for finding in findings} == {"CHUNK-0002", "CHUNK-0003"}
