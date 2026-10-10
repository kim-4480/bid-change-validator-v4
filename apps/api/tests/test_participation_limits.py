"""나라장터 면허제한·참가가능지역을 공고 차수에 받아 두고 분석·판정에 넘긴다(2026-10-10)."""

from types import SimpleNamespace

from bidengine.contracts import QualificationRequirement

from apps.api.app.config import Settings
from apps.api.app.services.g2b import G2BApiError, G2BClient, G2BPage
from apps.api.app.services.participation_limits import (
    engine_notice_limits,
    ensure_participation_limits,
    normalize_participation_limits,
    notice_api_grounded_keys,
    participation_limits_fetcher,
)

RAW = {
    "licenses": [
        {"lmtGrpNo": "1", "lmtSno": "1", "lcnsLmtNm": "건설폐기물 중간처리업/1253"},
        {"lmtGrpNo": "1", "lmtSno": "2", "lcnsLmtNm": "건설폐기물 수집·운반업/6728"},
        {"lmtGrpNo": "2", "lmtSno": "1", "lcnsLmtNm": "건설폐기물 중간처리업/1253"},
        {"lmtGrpNo": "3", "lmtSno": "1", "lcnsLmtNm": "코드 없는 면허"},
        {"lmtGrpNo": "4", "lmtSno": "1", "lcnsLmtNm": ""},
    ],
    "regions": [{"prtcptPsblRgnNm": "경기도 양평군"}, {"prtcptPsblRgnNm": " "}],
}


class _Db:
    def __init__(self) -> None:
        self.flushed = 0

    def flush(self) -> None:
        self.flushed += 1


def _version(limits=None, raw_json=None):
    return SimpleNamespace(
        participation_limits=limits, bid_notice_order="000", raw_json=raw_json or {},
        notice=SimpleNamespace(bid_notice_no="R26BK01747591"),
    )


def _req(key, type_, value, **scope):
    return QualificationRequirement(requirement_key=key, notice_version_id="v", type=type_, operator="MATCH",
                                    value=value, raw="나라장터 면허제한", scope=scope)


def test_lookup_rows_become_groups_names_and_codes() -> None:
    value = normalize_participation_limits(RAW)
    assert value["licenses"] == [
        {"group": "1", "name": "건설폐기물 중간처리업", "code": "1253"},
        {"group": "1", "name": "건설폐기물 수집·운반업", "code": "6728"},
        {"group": "2", "name": "건설폐기물 중간처리업", "code": "1253"},
        {"group": "3", "name": "코드 없는 면허", "code": None},
    ]
    assert value["regions"] == ["경기도 양평군"]
    assert normalize_participation_limits({}) == {"licenses": [], "regions": []}


def test_limits_are_fetched_once_and_kept_on_the_version() -> None:
    calls = []

    def fetch(bid_notice_no, bid_notice_order):
        calls.append((bid_notice_no, bid_notice_order))
        return RAW

    db, version = _Db(), _version()
    first = ensure_participation_limits(db, version, fetch)
    assert calls == [("R26BK01747591", "000")] and db.flushed == 1
    assert version.participation_limits == first
    # 저장된 값이 있으면 다시 묻지 않는다 — 발주처가 아무것도 입력하지 않은 빈 값도 '받은 값' 이다.
    assert ensure_participation_limits(db, version, fetch) == first and len(calls) == 1
    empty = _version(limits={"licenses": [], "regions": []})
    assert ensure_participation_limits(db, empty, fetch) == {"licenses": [], "regions": []} and len(calls) == 1


def test_a_failed_lookup_is_not_stored_and_analysis_goes_on_without_it() -> None:
    def broken(*_):
        raise G2BApiError("G2B_TRANSPORT_ERROR", "실패")

    db, version = _Db(), _version()
    assert ensure_participation_limits(db, version, broken) is None
    assert version.participation_limits is None and db.flushed == 0
    assert ensure_participation_limits(db, version, None) is None       # 조회 함수를 넘기지 않은 경우
    assert engine_notice_limits(version, None) is None


def test_the_engine_gets_limits_with_the_notice_flags() -> None:
    version = _version(raw_json={"cntrctCnclsMthdNm": "일반경쟁", "indstrytyLmtYn": "N", "bidNtceNm": "무관한 값"})
    limits = engine_notice_limits(version, {"licenses": [], "regions": []})
    assert limits is not None and limits.no_restriction_stated
    restricted = engine_notice_limits(_version(raw_json={"cntrctCnclsMthdNm": "제한경쟁"}), normalize_participation_limits(RAW))
    assert [item.code for item in restricted.licenses] == ["1253", "6728", "1253", None]
    assert not restricted.no_restriction_stated


def test_notice_api_requirements_are_grounded_only_by_the_stored_value() -> None:
    value = normalize_participation_limits(RAW)
    reqs = [
        _req("group", "INDUSTRY", "1253", origin="NOTICE_API", with_codes=["6728"]),
        _req("single", "INDUSTRY", "1253", origin="NOTICE_API"),
        _req("gone", "INDUSTRY", "9999", origin="NOTICE_API"),
        _req("region", "REGION", "경기도 양평군", origin="NOTICE_API"),
        _req("other-region", "REGION", "부산광역시", origin="NOTICE_API"),
        _req("document", "INDUSTRY", "1253"),            # 문서에서 온 요건은 문서 인용으로 확인한다 — 여기서는 다루지 않는다
    ]
    assert notice_api_grounded_keys(reqs, value) == {"group", "single", "region"}
    assert notice_api_grounded_keys(reqs, None) == set()
    assert notice_api_grounded_keys(reqs, {"licenses": [], "regions": []}) == set()


def test_no_fetcher_without_a_key_or_when_switched_off() -> None:
    assert participation_limits_fetcher(Settings(g2b_service_key=None)) is None
    assert participation_limits_fetcher(Settings(g2b_service_key="key", participation_limits_lookup_enabled=False)) is None
    assert callable(participation_limits_fetcher(Settings(g2b_service_key="key")))


def test_client_asks_both_lookups_with_the_notice_order(monkeypatch) -> None:
    seen = []

    def fake_page(self, *, endpoint, params):
        seen.append((endpoint, params["bidNtceNo"], params["bidNtceOrd"], params["inqryDiv"], params["pageNo"]))
        items = [{"n": params["pageNo"]}] if params["pageNo"] <= 2 and endpoint.endswith("LicenseLimit") else []
        return G2BPage(items=items, total_count=150 if endpoint.endswith("LicenseLimit") else 0,
                       page_number=params["pageNo"], page_size=100, endpoint=endpoint)

    monkeypatch.setattr(G2BClient, "_fetch_json_page", fake_page)
    result = G2BClient("key", "https://example.invalid").fetch_participation_limits(
        bid_notice_no="R26BK01747591", bid_notice_order="000")
    assert result == {"licenses": [{"n": 1}, {"n": 2}], "regions": []}
    assert seen == [
        ("getBidPblancListInfoLicenseLimit", "R26BK01747591", "000", "2", 1),
        ("getBidPblancListInfoLicenseLimit", "R26BK01747591", "000", "2", 2),
        ("getBidPblancListInfoPrtcptPsblRgn", "R26BK01747591", "000", "2", 1),
    ]


def test_stored_coverage_tells_the_judge_the_tender_is_open() -> None:
    """요건이 하나도 없는 공고는 나라장터가 '제한 없는 입찰' 이라 한 분석에서만 핵심 요건 충족으로 확정된다."""
    from datetime import date

    from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirements
    from bidengine.pipeline.analysis_result import AnalysisCoverage

    from apps.api.app.qualification.analysis import no_restriction_stated

    open_tender = SimpleNamespace(coverage=AnalysisCoverage(section_selection="anchored", no_restriction_stated=True))
    unknown = SimpleNamespace(coverage=AnalysisCoverage(section_selection="anchored"))
    assert no_restriction_stated(open_tender) and not no_restriction_stated(unknown)
    assert not no_restriction_stated(SimpleNamespace(coverage=None))          # 예전 분석
    assert not no_restriction_stated(SimpleNamespace())

    profile = CompanyProfileSnapshot(company_id="c", region_name="서울특별시 중구", company_size="SMALL")

    def overall(analysis):
        return judge_requirements([], profile, preflight_case_id="c", reference_date=date(2026, 10, 10),
                                  coverage_complete=analysis.coverage.verdict_complete,
                                  no_restriction_stated=no_restriction_stated(analysis)).overall_status

    assert overall(open_tender) == "core_met"
    assert overall(unknown) == "needs_review"
