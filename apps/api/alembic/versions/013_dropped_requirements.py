"""분석 실행이 버린 자격요건 후보를 남긴다 (dropped_requirements).

왜 별도 컬럼인가
----------------
추출기가 근거 검증에 실패한 후보를 그냥 버리면, 화면에는 "요건 5건"만 보이고
"3건을 왜 버렸는지"는 어디에도 남지 않는다. 그러면 누락과 정상 제외를 구분할
방법이 없다. 버린 이유를 같은 실행 행에 붙여 두는 것이 목적이다.

lineage 에 대하여
-----------------
이 변경은 원래 `010_dropped_requirements` 로 develop 과 나란한 가지에 있었고,
합치려면 merge revision 이 필요했다. PR #104 리뷰 의견(🟡)대로 가지를 만들지
않고 공용 DB 가 이미 올라와 있는 최신 head(012) 위에 선형으로 다시 얹는다.
스키마 결과는 같고 migration 그래프만 단순해진다.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "013_dropped_requirements"
down_revision = "012_late_penalty_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qualification_analysis_runs",
        sa.Column(
            "dropped_requirements",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "근거 검증에서 탈락한 요건 후보. 빈 배열은 '버린 것이 없음'이고, "
                "컬럼 자체가 없으면 '아직 기록하지 않던 시절'이라는 뜻이다 — "
                "누락과 정상 제외를 가르는 근거이므로 NULL 을 허용하지 않는다"
            ),
        ),
    )
    # 이 컬럼을 읽는 쪽은 항상 리스트를 가정한다. 객체나 문자열이 들어오면
    # 조회 시점이 아니라 저장 시점에 막는 편이 원인을 찾기 쉽다.
    op.create_check_constraint(
        "qualification_analysis_runs_dropped_requirements_array",
        "qualification_analysis_runs",
        "jsonb_typeof(dropped_requirements) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "qualification_analysis_runs_dropped_requirements_array",
        "qualification_analysis_runs",
        type_="check",
    )
    op.drop_column("qualification_analysis_runs", "dropped_requirements")
