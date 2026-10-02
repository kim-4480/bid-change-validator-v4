"""Link application users to their company profiles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "021_user_company"
down_revision = "020_notice_change_histories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_users",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_app_users_company_id",
        "app_users",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_app_users_company_id", "app_users", ["company_id"])
    op.drop_constraint("app_users_role_valid", "app_users", type_="check")
    op.create_check_constraint(
        "app_users_role_valid",
        "app_users",
        "role IN ('SYSTEM_ADMIN', 'ADMIN', 'USER')",
    )
    op.execute(
        "UPDATE app_users SET role = 'SYSTEM_ADMIN' "
        "WHERE role = 'ADMIN' AND company_id IS NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE app_users SET role = 'ADMIN' WHERE role = 'SYSTEM_ADMIN'")
    op.drop_constraint("app_users_role_valid", "app_users", type_="check")
    op.create_check_constraint(
        "app_users_role_valid",
        "app_users",
        "role IN ('ADMIN', 'USER')",
    )
    op.drop_index("idx_app_users_company_id", table_name="app_users")
    op.drop_constraint("fk_app_users_company_id", "app_users", type_="foreignkey")
    op.drop_column("app_users", "company_id")
