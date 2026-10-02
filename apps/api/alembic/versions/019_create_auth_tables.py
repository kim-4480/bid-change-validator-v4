"""Create application users and revocable authentication sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_auth_tables"
down_revision = "018_company_profile_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="USER"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("BTRIM(username) <> ''", name="app_users_username_not_blank"),
        sa.CheckConstraint("role IN ('ADMIN', 'USER')", name="app_users_role_valid"),
        sa.CheckConstraint(
            "failed_login_attempts >= 0", name="app_users_failed_attempts_nonnegative"
        ),
    )
    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_auth_sessions_user_expires",
        "auth_sessions",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_sessions_user_expires", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("app_users")
