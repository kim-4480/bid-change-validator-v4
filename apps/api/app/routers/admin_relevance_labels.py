"""Human relevance grading, independent approval, and append-only audit.

These grades describe business relevance, not qualification or award odds. A
label only becomes training-eligible after a second system administrator
approves a real-company review against unchanged company/notice inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..auth_models import AppUser
from ..database import get_db
from ..errors import ApiError
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..models import BidNoticeVersion, RelevanceReviewEvent, RelevanceReviewLabel
from ..qualification.analysis import qualification_analysis_version_fingerprint
from ..qualification.judgment import QualificationJudgmentError, _load_company, _record_to_completeness, build_company_profile_snapshot


router = APIRouter(prefix="/api/v1/admin/relevance-labels", tags=["admin relevance labels"])


class ReviewInput(BaseModel):
    company_id: UUID
    notice_version_id: UUID
    grade: int = Field(ge=0, le=3)
    rationale: str = Field(min_length=10, max_length=4000)
    subject_origin: Literal["REAL", "SYNTHETIC", "UNKNOWN"] = "UNKNOWN"

    @field_validator("rationale")
    @classmethod
    def substantive_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("A substantive rationale is required")
        return value


class LabelRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    company_id: UUID
    notice_version_id: UUID
    grade: int
    rationale: str
    subject_origin: str
    status: str
    reviewer_id: UUID
    reviewed_at: datetime
    approved_by_id: UUID | None
    approved_at: datetime | None
    updated_at: datetime


class EventRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    label_id: UUID
    actor_id: UUID
    action: str
    before_state: dict | None
    after_state: dict
    created_at: datetime


def _require_reviewer(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role not in {"ADMIN", "SYSTEM_ADMIN"}:
        raise ApiError(403, "REVIEW_ADMIN_REQUIRED", "검수는 회사 관리자 또는 시스템 관리자만 할 수 있습니다.")
    return user


def _require_system_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if user.role != "SYSTEM_ADMIN":
        raise ApiError(403, "SYSTEM_ADMIN_REQUIRED", "라벨 승인·내보내기는 시스템 관리자만 할 수 있습니다.")
    return user


def _scope(user: AppUser, company_id: UUID) -> None:
    if user.role != "SYSTEM_ADMIN" and user.company_id != company_id:
        raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사의 검수 라벨에 접근할 수 없습니다.")


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _company_input_hash(db: Session, company_id: UUID) -> str:
    try:
        company = _load_company(db, company_id)
    except QualificationJudgmentError as error:
        raise ApiError(404, error.code, error.message) from error
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company_id))
    company_snapshot = build_company_profile_snapshot(company, completeness).model_dump(mode="json")
    company_snapshot["company_name"] = company.name
    return _hash(company_snapshot)


def _notice_input_hash(db: Session, version_id: UUID) -> str:
    version = db.get(BidNoticeVersion, version_id)
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "공고 차수를 찾을 수 없습니다.")
    notice_snapshot = {
        "version_id": str(version.id), "notice_id": str(version.notice_id),
        "payload_hash": version.payload_hash, "title": version.notice.title,
        "analysis_input_fingerprint": qualification_analysis_version_fingerprint(version),
    }
    return _hash(notice_snapshot)


def _input_hashes(db: Session, company_id: UUID, version_id: UUID) -> tuple[str, str]:
    return _company_input_hash(db, company_id), _notice_input_hash(db, version_id)


def _state(label: RelevanceReviewLabel) -> dict:
    return {
        "grade": label.grade, "rationale": label.rationale,
        "subject_origin": label.subject_origin, "status": label.status,
        "company_fingerprint": label.company_fingerprint,
        "notice_fingerprint": label.notice_fingerprint,
        "reviewer_id": str(label.reviewer_id), "reviewed_at": label.reviewed_at.isoformat(),
        "approved_by_id": str(label.approved_by_id) if label.approved_by_id else None,
        "approved_at": label.approved_at.isoformat() if label.approved_at else None,
    }


@router.get("", response_model=list[LabelRead])
def list_labels(
    status: Literal["DRAFT", "APPROVED", "REOPENED"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: AppUser = Depends(_require_reviewer),
) -> list[LabelRead]:
    query = select(RelevanceReviewLabel)
    if user.role != "SYSTEM_ADMIN":
        query = query.where(RelevanceReviewLabel.company_id == user.company_id)
    if status:
        query = query.where(RelevanceReviewLabel.status == status)
    rows = db.scalars(query.order_by(RelevanceReviewLabel.updated_at.desc()).limit(limit)).all()
    return [LabelRead.model_validate(row) for row in rows]


@router.post("", response_model=LabelRead)
def submit_review(
    payload: ReviewInput,
    db: Session = Depends(get_db),
    user: AppUser = Depends(_require_reviewer),
) -> LabelRead:
    _scope(user, payload.company_id)
    company_hash, notice_hash = _input_hashes(db, payload.company_id, payload.notice_version_id)
    label = db.scalar(select(RelevanceReviewLabel).where(
        RelevanceReviewLabel.company_id == payload.company_id,
        RelevanceReviewLabel.notice_version_id == payload.notice_version_id,
    ).with_for_update())
    if label is not None and label.status == "APPROVED":
        raise ApiError(409, "APPROVED_LABEL_IMMUTABLE", "승인된 라벨은 수정할 수 없습니다. 별도 검수 변경 절차가 필요합니다.")
    before = _state(label) if label else None
    now = datetime.now(timezone.utc)
    if label is None:
        label = RelevanceReviewLabel(company_id=payload.company_id, notice_version_id=payload.notice_version_id)
        db.add(label)
    label.grade = payload.grade
    label.rationale = payload.rationale.strip()
    label.subject_origin = payload.subject_origin
    label.company_fingerprint = company_hash
    label.notice_fingerprint = notice_hash
    label.status = "DRAFT"
    label.reviewer_id = user.id
    label.reviewed_at = now
    label.approved_by_id = None
    label.approved_at = None
    label.updated_at = now
    try:
        db.flush()
        db.add(RelevanceReviewEvent(label_id=label.id, actor_id=user.id,
                                    action="REVIEWED", before_state=before, after_state=_state(label),
                                    created_at=now))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ApiError(409, "REVIEW_PAIR_CONFLICT", "같은 기업·공고 차수의 검수가 동시에 변경되었습니다.") from error
    db.refresh(label)
    return LabelRead.model_validate(label)


@router.post("/{label_id}/approve", response_model=LabelRead)
def approve_review(
    label_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(_require_system_admin),
) -> LabelRead:
    label = db.scalar(select(RelevanceReviewLabel).where(RelevanceReviewLabel.id == label_id).with_for_update())
    if label is None:
        raise ApiError(404, "REVIEW_LABEL_NOT_FOUND", "검수 라벨을 찾을 수 없습니다.")
    if label.status != "DRAFT":
        raise ApiError(409, "REVIEW_NOT_DRAFT", "대기 중인 검수만 승인할 수 있습니다.")
    if label.reviewer_id == user.id:
        raise ApiError(409, "INDEPENDENT_APPROVAL_REQUIRED", "본인이 입력한 라벨은 직접 승인할 수 없습니다.")
    if label.subject_origin != "REAL":
        raise ApiError(409, "REAL_COMPANY_REQUIRED", "합성 또는 출처 미확인 기업의 라벨은 실제 학습용으로 승인할 수 없습니다.")
    if _input_hashes(db, label.company_id, label.notice_version_id) != (
        label.company_fingerprint, label.notice_fingerprint
    ):
        raise ApiError(409, "REVIEW_INPUT_CHANGED", "회사 또는 공고 입력이 바뀌어 재검수가 필요합니다.")
    before = _state(label)
    label.status = "APPROVED"
    label.approved_by_id = user.id
    label.approved_at = label.updated_at = datetime.now(timezone.utc)
    db.add(RelevanceReviewEvent(label_id=label.id, actor_id=user.id,
                                action="APPROVED", before_state=before, after_state=_state(label),
                                created_at=label.approved_at))
    db.commit()
    db.refresh(label)
    return LabelRead.model_validate(label)


@router.post("/{label_id}/reopen", response_model=LabelRead)
def reopen_review(
    label_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(_require_system_admin),
) -> LabelRead:
    """Require a new human review before a revised approval can be exported."""
    label = db.scalar(select(RelevanceReviewLabel).where(RelevanceReviewLabel.id == label_id).with_for_update())
    if label is None:
        raise ApiError(404, "REVIEW_LABEL_NOT_FOUND", "검수 라벨을 찾을 수 없습니다.")
    if label.status != "APPROVED":
        raise ApiError(409, "REVIEW_NOT_APPROVED", "승인된 라벨만 재검수를 요청할 수 있습니다.")
    before = _state(label)
    now = datetime.now(timezone.utc)
    label.status = "REOPENED"
    label.approved_by_id = None
    label.approved_at = None
    label.updated_at = now
    db.add(RelevanceReviewEvent(label_id=label.id, actor_id=user.id,
                                action="REOPENED", before_state=before, after_state=_state(label),
                                created_at=now))
    db.commit()
    db.refresh(label)
    return LabelRead.model_validate(label)


@router.get("/{label_id}/events", response_model=list[EventRead])
def label_events(
    label_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(_require_reviewer),
) -> list[EventRead]:
    label = db.get(RelevanceReviewLabel, label_id)
    if label is None:
        raise ApiError(404, "REVIEW_LABEL_NOT_FOUND", "검수 라벨을 찾을 수 없습니다.")
    _scope(user, label.company_id)
    events = db.scalars(select(RelevanceReviewEvent).where(RelevanceReviewEvent.label_id == label_id)
                        .order_by(RelevanceReviewEvent.created_at, RelevanceReviewEvent.id)).all()
    return [EventRead.model_validate(event) for event in events]


@router.get("/approved-export")
def approved_labels_for_training(
    db: Session = Depends(get_db),
    _user: AppUser = Depends(_require_system_admin),
) -> dict:
    """Export only independently approved, current, real-company labels.

    This is a review artifact, not an automatically approved training release.
    Holdout leakage checks and Champion approval remain separate gates.
    """
    rows = db.scalars(select(RelevanceReviewLabel).where(
        RelevanceReviewLabel.status == "APPROVED",
        RelevanceReviewLabel.subject_origin == "REAL",
    ).order_by(RelevanceReviewLabel.reviewed_at, RelevanceReviewLabel.id).limit(10000)).all()
    current = [label for label in rows if _input_hashes(db, label.company_id, label.notice_version_id) ==
               (label.company_fingerprint, label.notice_fingerprint)]
    return {
        "label_source": "human_reviewed_approved",
        "approved_count": len(current), "excluded_changed_inputs": len(rows) - len(current),
        "items": [{
            "company_id": str(label.company_id), "notice_version_id": str(label.notice_version_id),
            "label": label.grade, "rationale": label.rationale,
            "subject_origin": label.subject_origin,
            "reviewer_id": str(label.reviewer_id), "reviewed_at": label.reviewed_at.isoformat(),
            "approved_by_id": str(label.approved_by_id), "approved_at": label.approved_at.isoformat(),
            "company_fingerprint": label.company_fingerprint,
            "notice_fingerprint": label.notice_fingerprint,
        } for label in current],
    }
