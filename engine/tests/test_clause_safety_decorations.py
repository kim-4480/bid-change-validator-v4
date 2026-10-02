"""안전 가드가 조항의 장식(법령 인용·조문 번호·괄호 설명)이 아니라 조항 자체를 보는지.

"「…법률」 제21조에 따른 건설폐기물중간처리업(업종코드 1253)을 등록한 업체" 는
판정이 업종코드 보유 여부로 단순한데 '법률' 문자열 때문에 절차 규정으로 막혔다.
canonical raw 가 인용을 뗀 형태라면 골든 러너에서도 이 제품 경로 실패가 보이지 않는다.

여기서는 그 경계를 고정한다 — 장식은 통과시키고 진짜 복합·부정·절차 조항은 여전히
막는다. 전체 측정 수치는 fixture bundle을 포함한 골든 러너 결과로 별도 검증한다.
"""

from bidengine.judgment.clause_safety import strip_decorations
from bidengine.judgment.clause_safety import unsafe_clause_reason


def test_a_statute_citation_is_not_a_procedural_rule() -> None:
    """실제 제품 추출 결과. 법령 인용은 근거 표시이지 절차 규정이 아니다."""
    raw = (
        "나. 「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 "
        "건설폐기물중간처리업 (업종코드 : 1253)을 등록한 업체"
    )

    assert unsafe_clause_reason(raw) is None


def test_an_alternative_inside_a_parenthetical_is_not_an_alternative_requirement() -> None:
    """골든셋 J01~J04 region. 괄호 안 '또는' 은 어느 서류로 주소를 보는지의 설명이다."""
    raw = (
        "본점소재지(개인사업자인 경우 사업자등록증 또는 허가․ 인가․면허․등록․신고 등에 "
        "관련된 서류가 기재된 사업장의 소재지)를 전남광주통합특별시에 소재한 업체"
    )

    assert unsafe_clause_reason(raw) is None


def test_a_real_alternative_in_the_main_clause_is_still_guarded() -> None:
    """골든셋 transport (REVIEW_HELD). '등록한 업체 또는 장비기준을 충족한 업체' 는 진짜 대안이다."""
    raw = (
        "다. 「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물수집·운반업 "
        "(업종코드 : 6728)을 등록한 업체 또는 같은 법 시행규칙 제12조 제5항 [별표2] 1. 가. "
        "수집·운반업 허가기준의 장비기준을 충족한 업체"
    )

    assert unsafe_clause_reason(raw) == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_real_procedural_negated_and_composite_rules_are_still_guarded() -> None:
    assert unsafe_clause_reason("관계법령에 따라 입찰무효 처리한다") == "LEGAL_PROCEDURAL_RULE"
    assert unsafe_clause_reason("대기업이 아닌 자") == "NEGATED_RULE"
    assert unsafe_clause_reason("공동수급체 구성원 각각 등록") == "COMPOSITE_PARTY_RULE"


def test_stripping_removes_decorations_but_keeps_the_clause() -> None:
    stripped = strip_decorations(
        "「지방자치단체를 당사자로 하는 계약에 관한 법률」 시행령 제20조 및 같은 법 시행규칙 "
        "제24조에 따라 공고일 전일(법인등기일 기준)부터 본점이 전남에 있는 업체"
    )

    assert "법률" not in stripped
    assert "제20조" not in stripped and "제24조" not in stripped
    # 괄호는 기본 보존한다 — 주소 증빙 설명 괄호가 아니면 그대로 둔다.
    assert "(법인등기일 기준)" in stripped
    assert "본점이 전남에 있는 업체" in stripped


def test_a_real_restriction_inside_parentheses_is_not_hidden() -> None:
    raw = "업종코드 1253 등록업체(공동수급은 허용하지 않음)"

    assert "공동수급" in strip_decorations(raw)
    assert unsafe_clause_reason(raw) == "COMPOSITE_PARTY_RULE"


def test_a_real_alternative_inside_parentheses_is_not_hidden() -> None:
    raw = "중소기업(소기업 또는 소상공인)만 참가할 수 있음"

    assert "소기업 또는 소상공인" in strip_decorations(raw)
    assert unsafe_clause_reason(raw) == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_a_quoted_alternative_is_not_mistaken_for_a_statute_citation() -> None:
    """「…」 는 법령명에도, 조건을 감싸는 데도 쓰인다 (#128 리뷰).

    「소기업 또는 소상공인」 을 인용으로 보고 통째로 지우면 '또는' 이 가드에 닿기 전에
    사라져 대안 조건 검사가 우회된다. 법령명일 때만 벗긴다.
    """
    quoted_condition = "「소기업 또는 소상공인」 확인서를 소지한 자"
    statute = "「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 업종코드 1253 등록업체"

    assert "소기업 또는 소상공인" in strip_decorations(quoted_condition)
    assert unsafe_clause_reason(quoted_condition) == "ALTERNATIVE_OR_EXCEPTION_RULE"
    assert "법률" not in strip_decorations(statute)
    assert unsafe_clause_reason(statute) is None


def test_only_address_evidence_parentheses_are_removed() -> None:
    """괄호는 기본 보존. 주소를 어느 서류로 보는지 나열한 설명 괄호만 벗긴다."""
    address = "본점소재지(사업자등록증 또는 허가 서류가 기재된 사업장의 소재지)가 전남인 업체"
    plain = "건설폐기물중간처리업 (업종코드 : 1253)을 등록한 업체"

    assert "사업자등록증" not in strip_decorations(address)
    assert unsafe_clause_reason(address) is None
    assert "(업종코드 : 1253)" in strip_decorations(plain)


def test_quoted_condition_ending_in_criteria_is_not_stripped() -> None:
    """#128 2차 리뷰 반례. '기준' 은 법령 접미가 아니라 흔한 조건 낱말이다.

    접미 하나로는 법령명과 조건을 못 가르므로, 뒤따르는 인용 문맥(제N조 · 에 따른 …)
    까지 있어야 인용으로 본다.
    """
    raw = "「소기업 또는 소상공인 기준」에 해당하는 업체"

    assert "소기업 또는 소상공인 기준" in strip_decorations(raw)
    assert unsafe_clause_reason(raw) == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_a_statute_name_without_citation_context_is_left_alone() -> None:
    """법령명 꼴이어도 인용 문맥이 없으면 건드리지 않는다 — 지우는 쪽이 위험하다."""
    raw = "「중소기업기본법」 중소기업 확인서를 소지한 자"

    assert "중소기업기본법" in strip_decorations(raw)


def test_a_document_alternative_in_parentheses_is_not_mistaken_for_address_evidence() -> None:
    """#128 2차 리뷰 반례. '(사업자등록증 또는 허가 서류 제출)' 은 실제 대안 제출 조건이다.

    주소 증빙 설명은 반드시 '사업장' 과 '소재지' 를 함께 말한다. 그 둘이 없으면 괄호를
    남겨 '또는' 이 가드에 닿게 한다.
    """
    raw = "참가자는 (사업자등록증 또는 허가 서류 제출) 요건을 충족해야 한다"

    assert "사업자등록증 또는 허가 서류 제출" in strip_decorations(raw)
    assert unsafe_clause_reason(raw) == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_nara_market_registration_is_a_procedure_not_a_qualification() -> None:
    """[재현 2026-09-15] 모델이 나라장터 입찰참가자격등록을 등록 요건으로 냈다 안 냈다 해서
    실행마다 요건 수가 오락가락했다(J14 6·5·6). 모든 입찰자가 거치는 절차이지 회사 프로필과
    대조할 자격이 아니다 — 골든셋도 그렇게 본다. 절차 규칙으로 고정한다."""
    from bidengine.judgment.clause_safety import unsafe_clause_reason

    for raw in (
        "「국가종합전자조달시스템 입찰참가자격등록규정」에 의하여 반드시 나라장터(G2B시스템)에 등록한 업체",
        "국가종합전자조달시스템 입찰참가자격등록을 마친 업체이어야 한다.",
        "나라장터시스템 전자입찰 이용자 등록을 한 자이어야 합니다.",
    ):
        assert unsafe_clause_reason(raw) == "LEGAL_PROCEDURAL_RULE", raw

    # 업종 등록은 절차가 아니라 자격이다 — 그대로 통과해야 한다.
    assert unsafe_clause_reason("폐기물수집·운반업(1227) 등록업체") is None
    assert unsafe_clause_reason("영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자") is None


def test_nara_market_registration_is_caught_even_when_properly_cited() -> None:
    """[재현 2026-09-15, 검수] 01634263-003 실제 원문. 위 테스트의 세 raw 는 전부 "나라장터
    (G2B시스템)에 등록" 처럼 꾸밈없는 꼬리 문구를 겸해 갖고 있어서, 「…규정」 인용이
    strip_decorations 에 지워져도 나머지 꼬리로 걸렸다. 실제 공고는 인용 하나뿐이다 —

        「국가종합전자조달시스템 입찰참가자격등록규정」에 따라 입찰 참가등록
        마감일시까지 입찰참가자격을 등록한 업체

    strip_decorations 는 「…규정」+"에 따라" 를 정상적인 법령 인용으로 보고 지운다. 그러면
    '국가종합전자조달시스템' 이라는 글자 자체가 패턴이 돌기 전에 사라져, 이 조항이 절차가
    아니라 일반 등록 요건처럼 통과해버렸다(검수 재현: 5회 중 4회 REGISTRATION_CERTIFICATION
    유령 생성). 이 규정은 인용이 곧 요건 전문이라 다른 조항의 "근거 법령 인용"과 다르므로,
    벗기기 전 원문에 먼저 댄다."""
    from bidengine.judgment.clause_safety import unsafe_clause_reason

    real = (
        "「지방자치단체를 당사자로 하는 계약에 관한 법률」 시행령 제13조 및 같은 법 시행규칙\n"
        "제14조에 따른 자격을 갖추고 「국가종합전자조달시스템 입찰참가자격등록규정」에 따라 입찰\n"
        "참가등록 마감일시까지 입찰참가자격을 등록한 업체로 아래의 자격을 모두 갖추어야 합니다."
    )
    assert unsafe_clause_reason(real) == "LEGAL_PROCEDURAL_RULE"

    # 같은 공고의 업종코드 조항(나./다.)은 인용을 달고 있어도 절차가 아니라 그대로 통과해야
    # 한다 — 이 조항들이 이번 요건 도달의 핵심(REACHED 2)이다.
    assert unsafe_clause_reason(
        "「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물중간처리업\n"
        "(업종코드 : 1253)을 등록한 업체"
    ) is None


def test_the_procurement_service_is_also_a_name_for_the_same_registration() -> None:
    """[골든 17개 실측 2026-09-15] 실제 공고가 쓰는 세 표현. 두 개는 3/3 으로 고정된 유령이었다
    (01697220·01706001), 하나는 목적격 조사 '을' 때문에 빠져나갔다(01635124)."""
    from bidengine.judgment.clause_safety import unsafe_clause_reason

    for raw in (
        "3.2. 조달청에 입찰참가자격등록을 한 자이어야 합니다.",
        "아. 본 입찰은 전자입찰방식에 의하여 집행하므로 조달청 전자입찰 이용자등록한 업체만이 입찰에 참여할 수 있습니다.",
        "나라장터에 입찰참가자격을 등록한 업체",
    ):
        assert unsafe_clause_reason(raw) == "LEGAL_PROCEDURAL_RULE", raw

    # '조달청' 은 진짜 자격도 수식한다 — 우수제품 등록은 절차가 아니다.
    assert unsafe_clause_reason("조달청 우수제품에 등록된 업체") is None


def test_an_industry_code_in_the_same_sentence_outranks_the_procedural_wording() -> None:
    """[재현 2026-09-15, 골든 17개 실측] 절차 문구와 업종코드가 한 문장에 온다. 문장 전체를
    절차로 막았더니 골든이 기대하는 INDUSTRY 1468(01635124)·9901(01684825, J20)이 사라졌다.
    코드는 닫힌 식별자라 그 문장의 요건을 확신할 수 있다 — 코드가 있으면 절차 문구는 무시한다."""
    from bidengine.judgment.clause_safety import unsafe_clause_reason

    mixed_1468 = (
        "○「소프트웨어진흥법」 제24조의 규정에 의거 입찰공고일 현재 소프트웨어사업자"
        "(컴퓨터관련서비스사업[업종코드:1468])로 등록을 필한 업체로 나라장터에 입찰참가자격을 등록한 업체"
    )
    mixed_9901 = (
        "국가종합전자조달시스템입찰참가자격등록규정에 따라 반드시 전자입찰서 제출마감일 전일까지 "
        "나라장터(G2B시스템)에 아래의 사항을 입찰참가자격으로 등록한 자 "
        "-[기타자유업(행사대행업)(9901)] 업종을 등록한 업체"
    )
    assert unsafe_clause_reason(mixed_1468) is None
    assert unsafe_clause_reason(mixed_9901) is None

    # 코드가 없으면 그대로 절차다.
    assert unsafe_clause_reason("나라장터에 입찰참가자격을 등록한 업체") == "LEGAL_PROCEDURAL_RULE"
    # 시스템명이 하나도 없는 맨 형태도 절차다(우치공원 1/3 재발 raw 그대로).
    assert unsafe_clause_reason("입찰참가등록 마감일시까지 입찰참가자격을 등록한 업체") == "LEGAL_PROCEDURAL_RULE"
    # 코드 항목들의 우산 문장(J14 1/3 재발 raw 그대로) — 코드는 각자 줄에서 살아난다.
    assert unsafe_clause_reason(
        "○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다."
    ) == "LEGAL_PROCEDURAL_RULE"
    # 제목·제한 문구에는 '등록' 이 안 붙어서 이 패턴에 안 걸린다.
    assert unsafe_clause_reason("3. 입찰참가자격 가. 지역 소재 업체") is None
    # 코드는 낱말 안에서 줄이 바뀌어도 코드다 — 원문 "[업⏎종코드: 5898]"(골든 01688607).
    assert unsafe_clause_reason(
        "「국가종합전자조달시스템 입찰참가자격등록규정(조달청 고시)」에 의하여 전자입찰서 제출 마감일 "
        "전일까지 아래 자격을 등록한 업체 1) ｢자동차관리법 제30조에 의한 제작자 등(자동차-국내 제작·조립[업\n종코드: 5898])"
    ) is None
    # 논리를 바꾸는 가드는 코드가 있어도 그대로 건다.
    assert unsafe_clause_reason(
        "업종코드 1468 등록업체. 다만 공동수급체 구성원은 제외한다"
    ) in ("ALTERNATIVE_OR_EXCEPTION_RULE", "COMPOSITE_PARTY_RULE")
