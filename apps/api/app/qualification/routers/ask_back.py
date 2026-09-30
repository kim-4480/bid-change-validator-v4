from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ...auth import authorize_case_access, get_optional_current_user
from ...auth_models import AppUser
from ...database import get_db
from ...errors import ApiError
from ...ask_back_schemas import QualificationAnswerCreate, QualificationAnswerRead, QualificationQuestionRead
from ..ask_back import answer_and_rejudge, list_questions
from ..judgment import QualificationJudgmentError

router=APIRouter(prefix="/api/v1",tags=["qualification ask-back"])
def _err(e:QualificationJudgmentError)->ApiError: return ApiError(e.status_code,e.code,e.message)

@router.get("/preflight-cases/{case_id}/qualification-questions",response_model=list[QualificationQuestionRead])
def questions(case_id:UUID,source_judgment_run_id:UUID|None=Query(default=None),db:Session=Depends(get_db),user:AppUser|None=Depends(get_optional_current_user)):
    authorize_case_access(db,user,case_id)
    try: return list_questions(db,case_id=case_id,source_judgment_run_id=source_judgment_run_id)
    except QualificationJudgmentError as e: raise _err(e) from e

@router.post("/preflight-cases/{case_id}/qualification-answers",response_model=QualificationAnswerRead)
def answer(case_id:UUID,payload:QualificationAnswerCreate,db:Session=Depends(get_db),user:AppUser|None=Depends(get_optional_current_user)):
    authorize_case_access(db,user,case_id)
    try: return answer_and_rejudge(db,case_id=case_id,payload=payload)
    except QualificationJudgmentError as e: raise _err(e) from e
