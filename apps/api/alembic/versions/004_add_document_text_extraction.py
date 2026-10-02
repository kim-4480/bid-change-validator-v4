"""Store deterministic text extracted from notice documents."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "004_document_text"
down_revision = "003_notice_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notice_documents",
        sa.Column("extraction_status", sa.Text(), nullable=False, server_default="PENDING"),
    )
    op.add_column("notice_documents", sa.Column("extracted_text", sa.Text()))
    op.add_column("notice_documents", sa.Column("extracted_blocks", postgresql.JSONB()))
    op.add_column("notice_documents", sa.Column("extracted_char_count", sa.Integer()))
    op.add_column("notice_documents", sa.Column("extracted_text_sha256", sa.String(64)))
    op.add_column("notice_documents", sa.Column("text_extractor", sa.Text()))
    op.add_column("notice_documents", sa.Column("extracted_at", sa.DateTime(timezone=True)))
    op.add_column("notice_documents", sa.Column("extraction_error", sa.Text()))
    op.create_check_constraint(
        "notice_documents_extraction_status_valid",
        "notice_documents",
        "extraction_status IN ('PENDING', 'EXTRACTED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "notice_documents_extraction_status_valid",
        "notice_documents",
        type_="check",
    )
    op.drop_column("notice_documents", "extraction_error")
    op.drop_column("notice_documents", "extracted_at")
    op.drop_column("notice_documents", "text_extractor")
    op.drop_column("notice_documents", "extracted_text_sha256")
    op.drop_column("notice_documents", "extracted_char_count")
    op.drop_column("notice_documents", "extracted_blocks")
    op.drop_column("notice_documents", "extracted_text")
    op.drop_column("notice_documents", "extraction_status")
