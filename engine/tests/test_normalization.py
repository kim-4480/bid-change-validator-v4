from bidengine.normalization import (
    normalize_amount,
    normalize_count,
    normalize_percent,
    normalize_period,
    normalize_value,
    parse_korean_number,
)


def test_parse_korean_number_handles_mixed_units():
    assert parse_korean_number("3억 5천만") == 350000000
    assert parse_korean_number("오억") == 500000000
    assert parse_korean_number("500,000,000") == 500000000


def test_normalize_amount_preserves_operator_and_unit():
    result = normalize_amount("4억원 이상")

    assert result["parse_status"] == "success"
    assert result["value"] == 400000000
    assert result["unit"] == "KRW"
    assert result["op"] == ">="


def test_normalize_period_converts_years_to_months():
    result = normalize_period("최근 3년")

    assert result["parse_status"] == "success"
    assert result["value"] == 36
    assert result["unit"] == "MONTH"


def test_normalize_percent_and_count():
    assert normalize_percent("30% 이상")["value"] == 30
    assert normalize_count("기술인력 2명 이상")["value"] == 2


def test_normalize_value_fails_explicitly_for_unknown_text():
    result = normalize_value("충분한 경험을 보유할 것")

    assert result["parse_status"] == "failed"
    assert result["value"] is None
