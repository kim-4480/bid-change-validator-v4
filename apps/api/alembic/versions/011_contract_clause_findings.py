"""계약조항 검토 결과(요청 5)를 저장할 테이블.

재현님이 짠 탐지기(bid-change-validator-llm-rag, detect/standard_diff.py의
_make_finding, detect/pattern_match.py의 detect_patterns)가 실제로 반환하는
finding dict 구조를 그대로 옮겼다 — 새로 설계하지 않고 이미 동작하는 코드의
출력 형태를 따라간 것.

카테고리는 수빈님·재현님이 일반 채널에서 이미 합의한 8종
(WARRANTY_PERIOD/LATE_PENALTY/COPYRIGHT_OWNERSHIP/ACCEPTANCE_CRITERIA/
SCOPE_AMBIGUITY/PAYMENT_TERMS/LIABILITY_SCOPE/TERMINATION_CONDITION) 그대로
CHECK로 고정한다 (category 컬럼). 다만 rule_id는 별도로 열어둔다 — 실제
재현님 코드의 rule_id는 카테고리보다 더 세분화되어 있어서(예: WARRANTY_PERIOD
한 카테고리에 warranty_period·warranty_bond_rate 두 rule_id가 매핑됨) rule_id까지
CHECK로 닫으면 표현이 안 된다. PAYMENT_TERMS·LIABILITY_SCOPE는 카테고리는
이미 정해졌지만 이 마이그레이션 시점 기준으로 탐지 로직(rule_id)이 아직
구현되어 있지 않다 — 그 경우 rule_id는 NULL로 두고 category만 채운다.

category ↔ rule_id 매핑 (탐지기 구현 시점 기준):
  WARRANTY_PERIOD      -> warranty_period, warranty_bond_rate
  LATE_PENALTY         -> penalty_cap
  COPYRIGHT_OWNERSHIP  -> ip_ownership
  ACCEPTANCE_CRITERIA  -> inspection_period
  SCOPE_AMBIGUITY      -> open_ended_scope
  TERMINATION_CONDITION -> termination_threshold
  PAYMENT_TERMS        -> (미구현)
  LIABILITY_SCOPE    -> (미구현)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "011_contract_clause_findings"
down_revision = "010_company_sw_engineer_grades"


def upgrade():
    # ── 검토 실행(run) — qualification_analysis_runs와 같은 패턴 ──────────
    op.create_table(
        "contract_clause_review_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notice_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="qualification_analysis_runs.status 와 동일한 관례",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="contract_clause_review_runs_status_valid",
        ),
    )
    op.create_index(
        "idx_contract_clause_review_runs_version_created",
        "contract_clause_review_runs",
        ["notice_version_id", "created_at"],
    )

    # ── 검토 결과(finding) 1건당 1행 — detect/standard_diff.py _make_finding,
    # detect/pattern_match.py detect_patterns 의 반환 dict 필드를 그대로 컬럼화 ──
    op.create_table(
        "contract_clause_findings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "review_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_clause_review_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Text(),
            nullable=False,
            comment=(
                "수빈님·재현님이 일반 채널에서 합의한 8종 고정 카테고리. "
                "이 컬럼이 프론트/리포트에서 그룹핑 기준으로 쓰는 값"
            ),
        ),
        sa.Column(
            "rule_id",
            sa.Text(),
            nullable=True,
            comment=(
                "탐지 규칙 식별자(카테고리보다 세분화됨). 예: warranty_period, "
                "warranty_bond_rate, ip_ownership, penalty_cap, "
                "inspection_period, termination_threshold(이상 "
                "standard_diff.py), open_ended_scope(pattern_match.py). "
                "PAYMENT_TERMS·LIABILITY_SCOPE 카테고리는 탐지 로직이 "
                "아직 없어 rule_id가 NULL이다 — category는 있는데 rule_id가 "
                "없는 건 '탐지기 미구현'을 뜻하지 결측이 아니다"
            ),
        ),
        sa.Column(
            "risk_type",
            sa.Text(),
            nullable=False,
            comment="사람이 읽는 라벨. 예: '하자보수 기간 과다', '과업범위 모호(포괄조항)'",
        ),
        sa.Column(
            "detection_method",
            sa.Text(),
            nullable=False,
            comment="standard_diff(경로 A, 표준 대조) | pattern_match(경로 B, 형식 탐지)",
        ),
        sa.Column(
            "matched_via",
            sa.Text(),
            nullable=True,
            comment=(
                "standard_diff 경로에서만 채워진다: regex(1차 정규식) 또는 "
                "embedding_llm(정규식 실패 후 임베딩+LLM 보강). "
                "pattern_match 경로는 이 값이 없다"
            ),
        ),
        sa.Column(
            "verdict",
            sa.Text(),
            nullable=False,
            comment="'확인 필요' | '적합' | '확인 불가' — 판정은 코드가 하고 LLM은 관여하지 않는다",
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column("rfp_clause_label", sa.Text(), nullable=True),
        sa.Column("rfp_chunk_id", sa.Text(), nullable=True),
        sa.Column("rfp_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "rfp_value",
            postgresql.JSONB(),
            nullable=True,
            comment=(
                "수치 판정 규칙에서만 채워진다 ({'value':.., 'unit':..} 형태). "
                "문언 판정(저작권)·패턴 판정(포괄조항)은 NULL — 표준값이 없는 "
                "유형이라 원래부터 없는 게 정상이다"
            ),
        ),
        sa.Column(
            "standard",
            postgresql.JSONB(),
            nullable=True,
            comment=(
                "{source, clause_ref, std_desc, text_excerpt, chapter} 형태. "
                "과업범위 모호(포괄조항)는 대응하는 표준 수치가 없는 유형이라 "
                "탐지기가 이 값을 항상 NULL로 반환한다 — 결측이 아니라 설계상 없음"
            ),
        ),
        sa.Column(
            "form",
            sa.Text(),
            nullable=True,
            comment="pattern_match 경로에서만 채워짐 — 매칭된 문형 이름(예: '잔여지시어+재량동사+열린대상')",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "verdict IN ('확인 필요', '적합', '확인 불가')",
            name="contract_clause_findings_verdict_valid",
        ),
        sa.CheckConstraint(
            "detection_method IN ('standard_diff', 'pattern_match')",
            name="contract_clause_findings_method_valid",
        ),
        sa.CheckConstraint(
            "category IN ('WARRANTY_PERIOD', 'LATE_PENALTY', 'COPYRIGHT_OWNERSHIP', "
            "'ACCEPTANCE_CRITERIA', 'SCOPE_AMBIGUITY', 'PAYMENT_TERMS', "
            "'LIABILITY_SCOPE', 'TERMINATION_CONDITION')",
            name="contract_clause_findings_category_valid",
        ),
        comment="계약조항 검토 결과 1건 = 탐지기 finding dict 1개. 화면에는 verdict='확인 필요'인 행 위주로 노출",
    )
    op.create_index(
        "idx_contract_clause_findings_run",
        "contract_clause_findings",
        ["review_run_id"],
    )
    op.create_index(
        "idx_contract_clause_findings_category_verdict",
        "contract_clause_findings",
        ["category", "verdict"],
    )


def downgrade():
    op.drop_table("contract_clause_findings")
    op.drop_table("contract_clause_review_runs")
