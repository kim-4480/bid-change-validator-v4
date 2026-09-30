from io import BytesIO
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.app.database import SessionLocal
from apps.api.app.config import get_settings
from apps.api.app.main import app
from apps.api.app.models import (
    BidNotice,
    BidNoticeVersion,
    NoticeCollectionRun,
    NoticeChangeHistory,
    NoticeDocument,
    NoticeFact,
    NoticeHistoryBackfillJob,
    NoticeRelation,
)
from apps.api.app.routers import notices as notices_router
from apps.api.app.routers import preflight_cases as preflight_cases_router
from apps.api.app.schemas import BusinessType, NoticeInquiryType, NoticeSyncRequest
from apps.api.app.services.g2b import G2BClient, G2BPage
from apps.api.app.services.document_storage import (
    LocalDocumentStorage,
    NoticeDocumentDownloader,
)
from apps.api.app.services.notices import run_notice_sync, save_notice_snapshot


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")
client = TestClient(app)
KST = ZoneInfo("Asia/Seoul")


class FakeFileResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {
            "Content-Length": str(len(content)),
            "Content-Type": "application/x-hwp",
        }

    def __enter__(self) -> "FakeFileResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for position in range(0, len(self.content), chunk_size):
            yield self.content[position : position + chunk_size]


class FakeFileSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def get(self, *_args, **_kwargs) -> FakeFileResponse:
        self.calls += 1
        return FakeFileResponse(self.content)


class FakeJsonResponse:
    def __init__(self, payload: bytes) -> None:
        self.content = payload

    def raise_for_status(self) -> None:
        return None


class FakeJsonSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict, float]] = []

    def get(self, url: str, *, params: dict, timeout: float) -> FakeJsonResponse:
        self.calls.append((url, params, timeout))
        return FakeJsonResponse(self.payload)


def _hwpx_content() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(
            "Contents/section0.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <hs:sec xmlns:hs="urn:hancom:section" xmlns:hp="urn:hancom:paragraph">
              <hp:p><hp:run><hp:t>입찰 참가자격은 6억원 이상입니다.</hp:t></hp:run></hp:p>
              <hp:p><hp:run><hp:t>필수 제출서류를 확인하십시오.</hp:t></hp:run></hp:p>
            </hs:sec>""",
        )
    return output.getvalue()


def _item(notice_no: str, estimated_price: str = "123000000") -> dict:
    return {
        "bidNtceNo": notice_no,
        "bidNtceOrd": "00",
        "bidNtceNm": "테스트 정보시스템 구축",
        "ntceKindNm": "일반공고",
        "rgstTyNm": "나라장터",
        "reNtceYn": "N",
        "bidNtceDt": "2026-09-05 09:00:00",
        "chgDt": "2026-09-05 09:00:00",
        "bidBeginDt": "2026-09-06 10:00:00",
        "bidClseDt": "2026-09-10 10:00:00",
        "opengDt": "2026-09-10 11:00:00",
        "ntceInsttCd": "1234567",
        "ntceInsttNm": "테스트 공고기관",
        "dminsttCd": "7654321",
        "dminsttNm": "테스트 수요기관",
        "cntrctCnclsMthdNm": "제한경쟁",
        "asignBdgtAmt": "125000000",
        "presmptPrce": estimated_price,
        "bidNtceDtlUrl": "https://example.test/notices/1",
        "stdNtceDocUrl": "https://example.test/files/request.hwpx",
        "ntceSpecFileNm1": "제안요청서.hwpx",
        "ntceSpecDocUrl1": "https://example.test/files/request.hwpx",
    }


def test_notice_version_deduplication_file_download_and_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notice_no = f"TEST-{uuid4()}"
    file_content = _hwpx_content()
    file_session = FakeFileSession(file_content)
    downloader = NoticeDocumentDownloader(
        storage=LocalDocumentStorage(str(tmp_path)),
        storage_prefix="",
        timeout_seconds=1,
        max_file_size_bytes=1024,
        session=file_session,
    )
    test_settings = get_settings().model_copy(
        update={"document_storage_backend": "LOCAL", "document_storage_path": str(tmp_path)}
    )
    monkeypatch.setattr(notices_router, "get_settings", lambda: test_settings)
    monkeypatch.setattr(preflight_cases_router, "get_settings", lambda: test_settings)
    db = SessionLocal()
    notice_id = None
    try:
        result, notice, first_version = save_notice_snapshot(
            db,
            item=_item(notice_no),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 10, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        notice_id = notice.id
        assert result == "CREATED"
        assert first_version.version_number == 1
        assert file_session.calls == 1

        documents = db.scalars(
            select(NoticeDocument).where(
                NoticeDocument.notice_version_id == first_version.id
            )
        ).all()
        assert len(documents) == 2
        document = documents[0]
        assert document.download_status == "DOWNLOADED"
        assert document.file_size_bytes == len(file_content)
        assert document.file_sha256 is not None
        assert (tmp_path / document.storage_key).read_bytes() == file_content
        assert documents[0].storage_key == documents[1].storage_key
        assert documents[0].file_sha256 == documents[1].file_sha256
        assert all(document.extraction_status == "EXTRACTED" for document in documents)
        assert all(document.text_extractor == "HWPX_XML" for document in documents)
        assert "6억원 이상" in documents[0].extracted_text
        assert documents[0].extracted_blocks[0]["section_index"] == 0

        unchanged, _, same_version = save_notice_snapshot(
            db,
            item=_item(notice_no),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 11, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        assert unchanged == "UNCHANGED"
        assert same_version.id == first_version.id
        assert file_session.calls == 1

        changed_item = _item(notice_no, estimated_price="130000000")
        changed_item["bidNtceOrd"] = "01"
        changed, _, second_version = save_notice_snapshot(
            db,
            item=changed_item,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
            collected_at=datetime(2026, 9, 5, 12, tzinfo=KST),
            document_downloader=downloader,
        )
        db.commit()
        assert changed == "NEW_VERSION"
        assert second_version.version_number == 2
        assert file_session.calls == 2
        assert db.scalar(
            select(func.count()).select_from(BidNoticeVersion).where(
                BidNoticeVersion.notice_id == notice_id
            )
        ) == 2

        list_response = client.get("/api/v1/notices", params={"q": notice_no})
        assert list_response.status_code == 200, list_response.text
        assert list_response.json()["items"][0]["current_version"] == 2

        detail_response = client.get(f"/api/v1/notices/{notice_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["latest"]["estimated_price"] == 130000000
        assert detail["latest"]["documents"][0]["download_status"] == "DOWNLOADED"
        extracted_document = detail["latest"]["documents"][0]
        assert extracted_document["viewer_type"] == "RHWP"
        assert extracted_document["preview_url"] is None
        source_response = client.get(extracted_document["render_source_url"])
        assert source_response.status_code == 200
        assert source_response.content == file_content
        assert source_response.headers["content-type"] == "application/hwp+zip"
        assert "content-disposition" not in source_response.headers
        text_response = client.get(
            f"/api/v1/notices/{notice_id}/versions/2/documents/"
            f"{extracted_document['id']}/text"
        )
        assert text_response.status_code == 200, text_response.text
        assert "필수 제출서류" in text_response.json()["text"]
        assert text_response.json()["blocks"][0]["location"].startswith("section 1")
        preview_response = client.get(
            f"/api/v1/notices/{notice_id}/versions/2/documents/"
            f"{extracted_document['id']}/preview"
        )
        assert preview_response.status_code == 409
        assert (
            preview_response.json()["error"]["code"]
            == "DOCUMENT_PREVIEW_CONVERSION_REQUIRED"
        )

        same_version_case_response = client.post(
            "/api/v1/preflight-cases",
            json={
                "notice_id": str(notice_id),
                "baseline_version_number": 2,
                "current_version_number": 2,
                "title": "동일 차수 비교 요청",
            },
        )
        assert same_version_case_response.status_code == 422
        assert same_version_case_response.json()["error"]["code"] == "INVALID_VERSION_RANGE"

        case_response = client.post(
            "/api/v1/preflight-cases",
            json={
                "notice_id": str(notice_id),
                "baseline_version_number": 1,
                "current_version_number": 2,
                "title": "변경공고 제안서 검토",
            },
        )
        assert case_response.status_code == 201, case_response.text
        case = case_response.json()
        case_id = case["id"]
        assert case["baseline_version_number"] == 1
        assert case["current_version_number"] == 2
        assert case["status"] == "DRAFT"

        upload_response = client.post(
            f"/api/v1/preflight-cases/{case_id}/documents",
            data={"role": "PROPOSAL"},
            files={
                "file": (
                    "사업제안서.hwpx",
                    file_content,
                    "application/hwp+zip",
                )
            },
        )
        assert upload_response.status_code == 201, upload_response.text
        proposal = upload_response.json()
        assert proposal["viewer_type"] == "RHWP"
        assert proposal["extraction_status"] == "EXTRACTED"
        assert proposal["extracted_char_count"] > 0

        duplicate_response = client.post(
            f"/api/v1/preflight-cases/{case_id}/documents",
            data={"role": "PROPOSAL"},
            files={"file": ("복사본.hwpx", file_content, "application/hwp+zip")},
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["code"] == "DUPLICATE_PROPOSAL_DOCUMENT"

        fetched_case = client.get(f"/api/v1/preflight-cases/{case_id}")
        assert fetched_case.status_code == 200
        assert fetched_case.json()["status"] == "READY"
        assert len(fetched_case.json()["documents"]) == 1

        proposal_source = client.get(proposal["render_source_url"])
        assert proposal_source.status_code == 200
        assert proposal_source.content == file_content
        proposal_text = client.get(proposal["text_url"])
        assert proposal_text.status_code == 200
        assert "입찰 참가자격" in proposal_text.json()["text"]

        versions_response = client.get(f"/api/v1/notices/{notice_id}/versions")
        assert versions_response.status_code == 200
        assert [version["version_number"] for version in versions_response.json()] == [2, 1]
    finally:
        if notice_id is not None:
            persisted = db.get(BidNotice, notice_id)
            if persisted is not None:
                db.delete(persisted)
                db.commit()
        db.close()


def test_reannouncement_relation_is_preserved_and_resolved_later() -> None:
    previous_notice_no = f"TEST-PREV-{uuid4()}"
    current_notice_no = f"TEST-RE-{uuid4()}"
    current_notice_id = None
    previous_notice_id = None
    db = SessionLocal()
    try:
        reannouncement = _item(current_notice_no)
        reannouncement["reNtceYn"] = "Y"
        reannouncement["befBidBbancNo"] = previous_notice_no

        result, current_notice, _ = save_notice_snapshot(
            db,
            item=reannouncement,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        current_notice_id = current_notice.id

        assert result == "CREATED"
        unresolved = db.get(NoticeRelation, current_notice.id)
        assert unresolved is not None
        assert unresolved.previous_bid_notice_no == previous_notice_no
        assert unresolved.previous_notice_id is None
        assert unresolved.match_confidence == "CONFIRMED"

        _, previous_notice, _ = save_notice_snapshot(
            db,
            item=_item(previous_notice_no),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        previous_notice_id = previous_notice.id
        db.expire_all()

        resolved = db.get(NoticeRelation, current_notice.id)
        assert resolved is not None
        assert resolved.previous_notice_id == previous_notice.id

        response = client.get(f"/api/v1/notices/{current_notice.id}")
        assert response.status_code == 200
        assert response.json()["relation"]["previous_notice_id"] == str(previous_notice.id)
        assert response.json()["relation"]["resolved"] is True
    finally:
        for notice_id in (current_notice_id, previous_notice_id):
            if notice_id is None:
                continue
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        db.close()


def test_notice_facts_are_versioned_and_diffed() -> None:
    notice_no = f"TEST-FACT-{uuid4()}"
    notice_id = None
    db = SessionLocal()
    try:
        first = _item(notice_no)
        first["cmmnSpldmdMethdCd"] = ""
        first["cmmnSpldmdMethdNm"] = "(없음)공동수급불허"
        _, notice, first_version = save_notice_snapshot(
            db,
            item=first,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        notice_id = notice.id

        second = _item(notice_no)
        second["bidNtceOrd"] = "01"
        second["bidClseDt"] = "2026-09-12 10:00:00"
        second["asignBdgtAmt"] = "150000000"
        second["cmmnSpldmdMethdCd"] = "공500001"
        second["cmmnSpldmdMethdNm"] = "(전자)공동이행"
        _, _, second_version = save_notice_snapshot(
            db,
            item=second,
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()

        assert db.scalar(
            select(func.count())
            .select_from(NoticeFact)
            .where(NoticeFact.notice_version_id == first_version.id)
        ) == 4
        assert db.scalar(
            select(func.count())
            .select_from(NoticeFact)
            .where(NoticeFact.notice_version_id == second_version.id)
        ) == 4

        response = client.get(f"/api/v1/notices/{notice.id}/fact-changes")
        assert response.status_code == 200, response.text
        changes = {item["fact_key"]: item for item in response.json()["changes"]}
        assert set(changes) == {
            "BUDGET_AMOUNT",
            "JOINT_SUPPLY",
            "SUBMISSION_DEADLINE",
        }
        assert all(item["change_type"] == "MODIFIED" for item in changes.values())
    finally:
        if notice_id is not None:
            persisted = db.get(BidNotice, notice_id)
            if persisted is not None:
                db.delete(persisted)
                db.commit()
        db.close()


def test_fact_diff_rejects_unrelated_baseline_version() -> None:
    first_notice_id = None
    other_notice_id = None
    db = SessionLocal()
    try:
        _, first_notice, _ = save_notice_snapshot(
            db,
            item=_item(f"TEST-FIRST-{uuid4()}"),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        _, other_notice, other_version = save_notice_snapshot(
            db,
            item=_item(f"TEST-OTHER-{uuid4()}"),
            business_type=BusinessType.SERVICE,
            source_endpoint="getBidPblancListInfoServc",
        )
        db.commit()
        first_notice_id = first_notice.id
        other_notice_id = other_notice.id

        response = client.get(
            f"/api/v1/notices/{first_notice.id}/fact-changes",
            params={"baseline_version_id": str(other_version.id)},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BASELINE_NOTICE_VERSION_INVALID"
    finally:
        for notice_id in (first_notice_id, other_notice_id):
            if notice_id is None:
                continue
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        db.close()


def test_sync_fetches_and_links_direct_previous_notice() -> None:
    previous_notice_no = f"TEST-PREV-{uuid4()}"
    current_notice_no = f"TEST-RE-{uuid4()}"
    reannouncement = _item(current_notice_no)
    reannouncement["reNtceYn"] = "Y"
    reannouncement["befBidBbancNo"] = previous_notice_no
    previous = _item(previous_notice_no)

    class FakeG2BClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def fetch_page(self, **kwargs) -> G2BPage:
            self.calls.append(kwargs)
            items = (
                [previous]
                if kwargs["inquiry_type"] == NoticeInquiryType.NOTICE_NUMBER
                else [reannouncement]
            )
            return G2BPage(
                items=items,
                total_count=len(items),
                page_number=kwargs["page_number"],
                page_size=kwargs["page_size"],
                endpoint="getBidPblancListInfoServc",
            )

    fake_client = FakeG2BClient()
    db = SessionLocal()
    run_id = None
    notice_ids = []
    try:
        run = run_notice_sync(
            db,
            request=NoticeSyncRequest(
                business_type=BusinessType.SERVICE,
                inquiry_type=NoticeInquiryType.REGISTERED,
                window_started_at=datetime(2026, 9, 5, 9, tzinfo=KST),
                window_ended_at=datetime(2026, 9, 5, 10, tzinfo=KST),
            ),
            client=fake_client,
        )
        run_id = run.id

        current = db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == current_notice_no)
        )
        previous_notice = db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == previous_notice_no)
        )
        assert current is not None
        assert previous_notice is not None
        notice_ids = [current.id, previous_notice.id]
        relation = db.get(NoticeRelation, current.id)
        assert relation is not None
        assert relation.previous_notice_id == previous_notice.id
        assert run.api_calls == 2
        assert len(fake_client.calls) == 2
    finally:
        for notice_id in notice_ids:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        if run_id is not None:
            collection_run = db.get(NoticeCollectionRun, run_id)
            if collection_run is not None:
                db.delete(collection_run)
                db.commit()
        db.close()


def test_g2b_change_history_uses_notice_number_operation() -> None:
    payload = b'''{"response":{"header":{"resultCode":"00","resultMsg":"normal"},"body":{"items":[{"bidNtceNo":"R26TEST","chgItemNm":"bid deadline"}],"totalCount":1,"pageNo":1,"numOfRows":100}}}'''
    session = FakeJsonSession(payload)
    g2b = G2BClient(
        service_key="decoded-key",
        base_url="https://example.test/BidPublicInfoService",
        timeout_seconds=7,
        session=session,
    )

    page = g2b.fetch_change_history_page(
        business_type=BusinessType.SERVICE,
        bid_notice_no="R26TEST",
    )

    assert page.endpoint == "getBidPblancListInfoChgHstryServc"
    assert page.total_count == 1
    assert page.items[0]["chgItemNm"] == "bid deadline"
    url, params, timeout = session.calls[0]
    assert url.endswith("/getBidPblancListInfoChgHstryServc")
    assert params["inqryDiv"] == "2"
    assert params["bidNtceNo"] == "R26TEST"
    assert timeout == 7

    g2b.fetch_change_history_page(
        business_type=BusinessType.SERVICE,
        window_started_at=datetime(2026, 9, 5, 9, tzinfo=KST),
        window_ended_at=datetime(2026, 9, 5, 10, tzinfo=KST),
    )
    _, window_params, _ = session.calls[1]
    assert window_params["inqryDiv"] == "1"
    assert window_params["inqryBgnDt"] == "202609050900"
    assert window_params["inqryEndDt"] == "202609051000"


def test_g2b_replaces_unpaired_surrogates_before_persistence() -> None:
    payload = b'''{"response":{"header":{"resultCode":"00"},"body":{"items":[{"bidNtceNo":"R26TEST","bidNtceNm":"bad\\udb80title"}],"totalCount":1,"pageNo":1,"numOfRows":100}}}'''
    g2b = G2BClient(
        service_key="decoded-key",
        base_url="https://example.test/BidPublicInfoService",
        session=FakeJsonSession(payload),
    )

    page = g2b.fetch_page(
        business_type=BusinessType.SERVICE,
        inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
        page_number=1,
        page_size=100,
        bid_notice_no="R26TEST",
    )

    assert page.items[0]["bidNtceNm"] == "bad\ufffdtitle"
    assert "\udb80" not in page.items[0]["bidNtceNm"]


def test_notice_number_backfill_orders_versions_and_is_idempotent() -> None:
    notice_no = f"TEST-HISTORY-{uuid4()}"
    db = SessionLocal()
    notice_id = None
    run_ids = []
    try:
        current_item = _item(notice_no)
        current_item["bidNtceOrd"] = "003"
        first_run = run_notice_sync(
            db,
            request=NoticeSyncRequest(
                business_type=BusinessType.SERVICE,
                inquiry_type=NoticeInquiryType.REGISTERED,
                window_started_at=datetime(2026, 9, 5, 9, tzinfo=KST),
                window_ended_at=datetime(2026, 9, 5, 10, tzinfo=KST),
            ),
            client=type(
                "RegisteredClient",
                (),
                {
                    "fetch_page": lambda _self, **kwargs: G2BPage(
                        items=[current_item],
                        total_count=1,
                        page_number=kwargs["page_number"],
                        page_size=kwargs["page_size"],
                        endpoint="getBidPblancListInfoServc",
                    )
                },
            )(),
        )
        run_ids.append(first_run.id)
        notice = db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == notice_no)
        )
        assert notice is not None
        notice_id = notice.id
        assert db.scalar(
            select(func.count())
            .select_from(NoticeHistoryBackfillJob)
            .where(NoticeHistoryBackfillJob.notice_id == notice.id)
        ) == 1

        history_items = []
        for order in range(5, -1, -1):
            item = _item(notice_no, estimated_price=str(100_000_000 + order))
            item["bidNtceOrd"] = f"{order:03d}"
            item["ntceKindNm"] = "취소공고" if order == 5 else "변경공고"
            if order == 5:
                item["stdNtceDocUrl"] = ""
                item["ntceSpecDocUrl1"] = ""
            history_items.append(item)

        class HistoryClient:
            def fetch_page(self, **kwargs) -> G2BPage:
                return G2BPage(
                    items=history_items,
                    total_count=len(history_items),
                    page_number=kwargs["page_number"],
                    page_size=kwargs["page_size"],
                    endpoint="getBidPblancListInfoServc",
                )

        request = NoticeSyncRequest(
            business_type=BusinessType.SERVICE,
            inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
            bid_notice_no=notice_no,
        )
        history_run = run_notice_sync(db, request=request, client=HistoryClient())
        run_ids.append(history_run.id)

        versions = db.scalars(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice.id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
        assert [version.bid_notice_order for version in versions] == [
            "000", "001", "002", "003", "004", "005"
        ]
        assert [version.version_number for version in versions] == [1, 2, 3, 4, 5, 6]
        assert [version.is_current for version in versions] == [
            False, False, False, False, False, True
        ]
        assert versions[-1].notice_kind == "취소공고"
        assert len(versions[-1].documents) == 0

        repeat_run = run_notice_sync(db, request=request, client=HistoryClient())
        run_ids.append(repeat_run.id)
        assert db.scalar(
            select(func.count())
            .select_from(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice.id)
        ) == 6
    finally:
        if notice_id is not None:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        for run_id in run_ids:
            run = db.get(NoticeCollectionRun, run_id)
            if run is not None:
                db.delete(run)
        db.commit()
        db.close()


def test_one_invalid_notice_does_not_abort_remaining_items() -> None:
    valid_notice_no = f"TEST-VALID-{uuid4()}"
    invalid = _item(f"TEST-INVALID-{uuid4()}")
    invalid.pop("bidNtceNm")
    valid = _item(valid_notice_no)

    class MixedClient:
        def fetch_page(self, **kwargs) -> G2BPage:
            return G2BPage(
                items=[invalid, valid],
                total_count=2,
                page_number=kwargs["page_number"],
                page_size=kwargs["page_size"],
                endpoint="getBidPblancListInfoServc",
            )

    db = SessionLocal()
    notice_id = None
    run_id = None
    try:
        run = run_notice_sync(
            db,
            request=NoticeSyncRequest(
                business_type=BusinessType.SERVICE,
                inquiry_type=NoticeInquiryType.REGISTERED,
                window_started_at=datetime(2026, 9, 5, 9, tzinfo=KST),
                window_ended_at=datetime(2026, 9, 5, 10, tzinfo=KST),
            ),
            client=MixedClient(),
        )
        run_id = run.id
        notice = db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == valid_notice_no)
        )
        assert notice is not None
        notice_id = notice.id
        assert run.status == "FAILED"
        assert run.fetched_count == 2
        assert run.created_count == 1
        assert run.failed_item_count == 1
        assert "TEST-INVALID" in (run.error_message or "")
    finally:
        if notice_id is not None:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        if run_id is not None:
            run = db.get(NoticeCollectionRun, run_id)
            if run is not None:
                db.delete(run)
                db.commit()
        db.close()


def test_changed_sync_persists_authoritative_change_history() -> None:
    notice_no = f"TEST-CHANGE-{uuid4()}"
    changed_item = _item(notice_no)
    changed_item["bidNtceOrd"] = "000"
    history_item = {
        "bsnsDivNm": "용역",
        "chgDataDivNm": "입찰공고",
        "chgDt": "2026-09-05 12:00:00",
        "bidNtceNo": notice_no,
        "bidNtceOrd": "000",
        "rbidNo": "000",
        "chgItemNm": "입찰마감일시",
        "bfchgVal": "2026/09/10 10:00",
        "afchgVal": "2026/09/12 10:00",
    }

    class FakeChangedG2BClient:
        def __init__(self) -> None:
            self.history_calls: list[dict] = []

        def fetch_page(self, **kwargs) -> G2BPage:
            return G2BPage(
                items=[changed_item],
                total_count=1,
                page_number=kwargs["page_number"],
                page_size=kwargs["page_size"],
                endpoint="getBidPblancListInfoServc",
            )

        def fetch_change_history_page(self, **kwargs) -> G2BPage:
            self.history_calls.append(kwargs)
            return G2BPage(
                items=[history_item],
                total_count=1,
                page_number=kwargs["page_number"],
                page_size=kwargs["page_size"],
                endpoint="getBidPblancListInfoChgHstryServc",
            )

    fake_client = FakeChangedG2BClient()
    db = SessionLocal()
    notice_id = None
    run_ids = []
    try:
        request = NoticeSyncRequest(
            business_type=BusinessType.SERVICE,
            inquiry_type=NoticeInquiryType.CHANGED,
            window_started_at=datetime(2026, 9, 5, 9, tzinfo=KST),
            window_ended_at=datetime(2026, 9, 5, 13, tzinfo=KST),
        )
        first_run = run_notice_sync(db, request=request, client=fake_client)
        run_ids.append(first_run.id)
        notice = db.scalar(
            select(BidNotice).where(BidNotice.bid_notice_no == notice_no)
        )
        assert notice is not None
        notice_id = notice.id
        version = db.scalar(
            select(BidNoticeVersion).where(BidNoticeVersion.notice_id == notice.id)
        )
        history = db.scalar(
            select(NoticeChangeHistory).where(
                NoticeChangeHistory.notice_id == notice.id
            )
        )
        assert history is not None
        assert history.notice_version_id == version.id
        assert history.item_name == "입찰마감일시"
        assert history.before_value == "2026/09/10 10:00"
        assert history.after_value == "2026/09/12 10:00"
        assert first_run.api_calls == 2

        second_run = run_notice_sync(db, request=request, client=fake_client)
        run_ids.append(second_run.id)
        assert db.scalar(
            select(func.count())
            .select_from(NoticeChangeHistory)
            .where(NoticeChangeHistory.notice_id == notice.id)
        ) == 1

        response = client.get(f"/api/v1/notices/{notice.id}/change-history")
        assert response.status_code == 200, response.text
        assert response.json()[0]["item_name"] == "입찰마감일시"
        version_response = client.get(
            f"/api/v1/notices/{notice.id}/change-history",
            params={"version_number": 1},
        )
        assert len(version_response.json()) == 1
        assert len(fake_client.history_calls) == 2
    finally:
        if notice_id is not None:
            notice = db.get(BidNotice, notice_id)
            if notice is not None:
                db.delete(notice)
                db.commit()
        for run_id in run_ids:
            run = db.get(NoticeCollectionRun, run_id)
            if run is not None:
                db.delete(run)
        db.commit()
        db.close()
