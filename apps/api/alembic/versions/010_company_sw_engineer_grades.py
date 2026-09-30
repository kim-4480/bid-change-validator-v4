"""소프트웨어기술자 등급별 인원 + 대기업집단 계열 여부를 회사 프로필에 추가.

두 항목의 공통점: 업종에 따라 필요 없을 수 있어 '선택'이지만, 요구하는 공고에서는
없으면 판정 자체가 불가능하다. 그래서 NULL/행 없음이 '해당 없음'이 아니라
'아직 확인하지 않음'을 뜻하도록 설계했다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "010_company_sw_engineer_grades"
down_revision = "009_qualification_revalidation"

VERIFICATION_COMMENT = "증빙 서류로 확인된 값인지 여부. 미확인 값도 판정에는 쓰되 결과에 표시한다"


def upgrade():
    op.create_table(
        "company_sw_engineer_grades",
        # ── 왜 company_staff_roles 에 넣지 않았는가 ────────────────────────
        # role_name 은 'PM'·'개발자' 같은 직무다. 그런데 한 사람이 동시에
        # 개발자이면서 특급이다. 등급은 직무와 직교하는 축이라 같은 테이블에
        # 섞으면 headcount 를 합산하는 순간 인원이 두 배가 된다.
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "grade",
            sa.Text(),
            primary_key=True,
            comment=(
                "소프트웨어기술자 등급. 특급/고급/중급/초급 4종으로 닫혀 있으며 "
                "소프트웨어기술자 신고제도(한국소프트웨어산업협회)의 등급 체계를 따른다. "
                "공고가 '특급기술자 2인 이상' 형태로 요구하므로 등급 문자열을 그대로 보관한다"
            ),
        ),
        sa.Column(
            "headcount",
            sa.Integer(),
            nullable=False,
            comment=(
                "해당 등급 보유 인원. 0 은 '해당 등급이 없음을 확인했다'는 뜻이고, "
                "행 자체가 없으면 '아직 물어보지 않았다'는 뜻이다 — 판정에서 "
                "UNSATISFIED(미충족)와 UNKNOWN(확인 불가)을 가르는 기준이므로 "
                "값이 없다고 0 으로 채워 넣지 말 것"
            ),
        ),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
            comment=(
                "인력은 변하므로 값이 오래되면 다시 물어봐야 한다. "
                "재질의 주기는 아직 정하지 않았고 이 컬럼이 그 판단 근거가 된다"
            ),
        ),
        # 4종 외의 값이 들어오면 판정기가 등급 순서를 계산하지 못한다
        # (상위 등급이 하위 요건을 충족하는지 따질 때 순서가 필요하다).
        sa.CheckConstraint(
            "grade IN ('특급', '고급', '중급', '초급')",
            name="company_sw_engineer_grades_grade_valid",
        ),
        sa.CheckConstraint(
            "headcount >= 0",
            name="company_sw_engineer_grades_headcount_nonnegative",
        ),
        comment=(
            "회사가 보유한 소프트웨어기술자를 등급별로 집계한 표. 회사당 최대 4행. "
            "소프트웨어 용역 공고에서만 요구되므로 가입 시 필수가 아니며, "
            "해당 공고를 검토할 때 채워진다"
        ),
    )

    op.add_column(
        "companies",
        sa.Column(
            "conglomerate_affiliate",
            sa.Boolean(),
            nullable=True,
            comment=(
                "상호출자제한기업집단(대기업집단) 계열회사 해당 여부. "
                "NULL 은 '아직 확인하지 않음'이고 false 는 '해당하지 않음을 확인'이다. "
                "company_size 로 대신할 수 없다 — 중소기업이면서 대기업집단 "
                "계열사인 경우가 실제로 있고, 공고는 그 둘을 따로 제한한다"
            ),
        ),
    )


def downgrade():
    op.drop_column("companies", "conglomerate_affiliate")
    op.drop_table("company_sw_engineer_grades")
