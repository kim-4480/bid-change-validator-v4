from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analysis_models import QualificationAnalysisRun, QualificationEvidenceRecord, QualificationRequirementRecord
from ..ask_back_models import QualificationAnswer
from ..database import SessionLocal
from ..judgment_models import QualificationJudgmentRecord, QualificationJudgmentRun
from ..models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    NoticeCollectionRun,
    NoticeDocument,
    PreflightCase,
    ProposalDocument,
)
from ..revalidation_models import QualificationRevalidationRun


def _count(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def collect_product_data_inventory(db: Session) -> dict[str, object]:
    version_rows = db.execute(
        select(BidNoticeVersion.notice_id, func.count(BidNoticeVersion.id)).group_by(
            BidNoticeVersion.notice_id
        )
    ).all()
    version_distribution = Counter(int(count) for _, count in version_rows)

    document_download_status = dict(
        db.execute(
            select(NoticeDocument.download_status, func.count(NoticeDocument.id)).group_by(
                NoticeDocument.download_status
            )
        ).all()
    )
    document_extraction_status = dict(
        db.execute(
            select(NoticeDocument.extraction_status, func.count(NoticeDocument.id)).group_by(
                NoticeDocument.extraction_status
            )
        ).all()
    )
    collection_status = dict(
        db.execute(
            select(NoticeCollectionRun.status, func.count(NoticeCollectionRun.id)).group_by(
                NoticeCollectionRun.status
            )
        ).all()
    )

    return {
        "notices": {
            "count": _count(db, BidNotice),
            "versions": _count(db, BidNoticeVersion),
            "with_multiple_versions": sum(
                count for versions, count in version_distribution.items() if versions >= 2
            ),
            "version_distribution": {
                str(versions): count for versions, count in sorted(version_distribution.items())
            },
        },
        "documents": {
            "count": _count(db, NoticeDocument),
            "download_status": {
                str(key): int(value) for key, value in document_download_status.items()
            },
            "extraction_status": {
                str(key): int(value) for key, value in document_extraction_status.items()
            },
        },
        "collection_runs": {
            "count": _count(db, NoticeCollectionRun),
            "status": {str(key): int(value) for key, value in collection_status.items()},
        },
        "companies": {"count": _count(db, Company)},
        "preflight": {
            "cases": _count(db, PreflightCase),
            "proposal_documents": _count(db, ProposalDocument),
        },
        "qualification": {
            "analysis_runs": _count(db, QualificationAnalysisRun),
            "requirements": _count(db, QualificationRequirementRecord),
            "evidence": _count(db, QualificationEvidenceRecord),
            "judgment_runs": _count(db, QualificationJudgmentRun),
            "judgments": _count(db, QualificationJudgmentRecord),
            "answers": _count(db, QualificationAnswer),
            "revalidation_runs": _count(db, QualificationRevalidationRun),
        },
    }


def main() -> None:
    db = SessionLocal()
    try:
        inventory = collect_product_data_inventory(db)
        print(json.dumps(inventory, ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
