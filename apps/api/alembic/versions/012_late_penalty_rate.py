"""지체상금 요율(LATE_PENALTY_RATE)을 category 9번째 값으로 추가.

지체상금은 상한(LATE_PENALTY)과 요율(LATE_PENALTY_RATE)이 근거가 달라
분리 결정됨 (9/9 노트-자원 채널, 재현·수빈·홍규 합의).
"""
from alembic import op

revision = "012_late_penalty_rate"
down_revision = "011_contract_clause_findings"


def upgrade():
    op.drop_constraint(
        "contract_clause_findings_category_valid",
        "contract_clause_findings",
        type_="check",
    )
    op.create_check_constraint(
        "contract_clause_findings_category_valid",
        "contract_clause_findings",
        "category IN ('WARRANTY_PERIOD', 'LATE_PENALTY', 'LATE_PENALTY_RATE', "
        "'COPYRIGHT_OWNERSHIP', 'ACCEPTANCE_CRITERIA', 'SCOPE_AMBIGUITY', "
        "'PAYMENT_TERMS', 'LIABILITY_SCOPE', 'TERMINATION_CONDITION')",
    )


def downgrade():
    op.drop_constraint(
        "contract_clause_findings_category_valid",
        "contract_clause_findings",
        type_="check",
    )
    op.create_check_constraint(
        "contract_clause_findings_category_valid",
        "contract_clause_findings",
        "category IN ('WARRANTY_PERIOD', 'LATE_PENALTY', 'COPYRIGHT_OWNERSHIP', "
        "'ACCEPTANCE_CRITERIA', 'SCOPE_AMBIGUITY', 'PAYMENT_TERMS', "
        "'LIABILITY_SCOPE', 'TERMINATION_CONDITION')",
    )