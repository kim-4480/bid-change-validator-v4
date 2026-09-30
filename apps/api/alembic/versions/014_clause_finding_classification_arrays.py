"""계약조항 한 원문에서 함께 탐지된 복수 위험 분류를 보존한다."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "014_clause_finding_arrays"
down_revision = "013_dropped_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contract_clause_findings",
        sa.Column(
            "risk_types",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "contract_clause_findings",
        sa.Column(
            "categories",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE contract_clause_findings
        SET risk_types = jsonb_build_array(risk_type),
            categories = jsonb_build_array(category)
        """
    )
    op.create_check_constraint(
        "contract_clause_findings_risk_types_array",
        "contract_clause_findings",
        "jsonb_typeof(risk_types) = 'array'",
    )
    op.create_check_constraint(
        "contract_clause_findings_categories_array",
        "contract_clause_findings",
        "jsonb_typeof(categories) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "contract_clause_findings_categories_array",
        "contract_clause_findings",
        type_="check",
    )
    op.drop_constraint(
        "contract_clause_findings_risk_types_array",
        "contract_clause_findings",
        type_="check",
    )
    op.drop_column("contract_clause_findings", "categories")
    op.drop_column("contract_clause_findings", "risk_types")
