"""Track downloaded notice document files."""

from alembic import op
import sqlalchemy as sa


revision = "003_notice_documents"
down_revision = "002_bid_notices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notice_documents",
        sa.Column("download_status", sa.Text(), nullable=False, server_default="PENDING"),
    )
    op.add_column("notice_documents", sa.Column("storage_key", sa.Text()))
    op.add_column("notice_documents", sa.Column("content_type", sa.Text()))
    op.add_column("notice_documents", sa.Column("file_size_bytes", sa.BigInteger()))
    op.add_column("notice_documents", sa.Column("file_sha256", sa.String(64)))
    op.add_column("notice_documents", sa.Column("downloaded_at", sa.DateTime(timezone=True)))
    op.add_column("notice_documents", sa.Column("download_error", sa.Text()))
    op.create_check_constraint(
        "notice_documents_download_status_valid",
        "notice_documents",
        "download_status IN ('PENDING', 'DOWNLOADED', 'FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "notice_documents_download_status_valid",
        "notice_documents",
        type_="check",
    )
    op.drop_column("notice_documents", "download_error")
    op.drop_column("notice_documents", "downloaded_at")
    op.drop_column("notice_documents", "file_sha256")
    op.drop_column("notice_documents", "file_size_bytes")
    op.drop_column("notice_documents", "content_type")
    op.drop_column("notice_documents", "storage_key")
    op.drop_column("notice_documents", "download_status")
