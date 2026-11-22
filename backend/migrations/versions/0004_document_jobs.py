"""Store document jobs, files, and vectors in the database."""

from alembic import op
import sqlalchemy as sa

revision = "0004_document_jobs"
down_revision = "0003_revoked_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("job_token", sa.String(36)))
    op.add_column("documents", sa.Column("job_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_documents_owner_created", "documents", ["user_id", "created_at"])
    op.create_index("ix_conversations_owner_updated", "conversations", ["user_id", "updated_at"])
    op.create_index("ix_messages_conversation_order", "messages", ["conversation_id", "id"])
    op.create_table(
        "document_files",
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("page_number", sa.Integer()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
    )


def downgrade():
    op.drop_table("document_chunks")
    op.drop_table("document_files")
    op.drop_index("ix_documents_owner_created", table_name="documents")
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_index("ix_messages_conversation_order", table_name="messages")
    op.drop_column("documents", "job_attempts")
    op.drop_column("documents", "job_token")
