from uuid import uuid4

from apps.api.app.models import BidNoticeVersion, NoticeDocument
from apps.api.app.qualification.analysis import build_qualification_analysis_input


def test_analysis_input_uses_only_extracted_backend_blocks() -> None:
    version = BidNoticeVersion(
        id=uuid4(),
        notice_id=uuid4(),
        version_number=1,
        bid_notice_order="00",
        is_current=True,
        source_endpoint="fixture",
        payload_hash="a" * 64,
        raw_json={},
    )
    extracted = NoticeDocument(
        id=uuid4(),
        notice_version_id=version.id,
        document_order=0,
        name="공고문.pdf",
        url="https://example.invalid/notice.pdf",
        source_field="stdNtceDocUrl",
        download_status="DOWNLOADED",
        extraction_status="EXTRACTED",
        file_sha256="b" * 64,
        extracted_text_sha256="c" * 64,
        extracted_blocks=[
            {
                "block_index": 0,
                "page": 3,
                "location": "p.3",
                "text": "3. 참가자격\n서울특별시 소재 업체",
            }
        ],
    )
    pending = NoticeDocument(
        id=uuid4(),
        notice_version_id=version.id,
        document_order=1,
        name="미추출.hwp",
        url="https://example.invalid/pending.hwp",
        source_field="ntceSpecDocUrl1",
        download_status="DOWNLOADED",
        extraction_status="PENDING",
        extracted_blocks=None,
    )
    version.documents = [extracted, pending]

    payload = build_qualification_analysis_input(version)

    assert payload.notice_id == str(version.notice_id)
    assert payload.notice_version_id == str(version.id)
    assert len(payload.documents) == 1
    assert payload.documents[0].document_id == str(extracted.id)
    assert payload.documents[0].file_sha256 == "b" * 64
    assert payload.documents[0].extracted_text_sha256 == "c" * 64
    assert payload.documents[0].extracted_blocks[0]["page"] == 3


def test_analysis_input_allows_no_extracted_documents_for_failed_run_diagnostic() -> None:
    version = BidNoticeVersion(
        id=uuid4(),
        notice_id=uuid4(),
        version_number=1,
        bid_notice_order="00",
        is_current=True,
        source_endpoint="fixture",
        payload_hash="d" * 64,
        raw_json={},
    )
    version.documents = []

    payload = build_qualification_analysis_input(version)

    assert payload.documents == []
