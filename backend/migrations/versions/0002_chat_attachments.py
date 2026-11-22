"""Associate documents with individual conversations and deduplicate uploads."""
from alembic import op
import sqlalchemy as sa

revision = "0002_chat_attachments"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(64)))
        batch.create_unique_constraint("uq_documents_owner_hash", ["user_id", "content_hash"])
    op.create_table(
        "conversation_documents",
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_conversation_documents_document_id", "conversation_documents", ["document_id"])


def downgrade():
    op.drop_table("conversation_documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_owner_hash", type_="unique")
        batch.drop_column("content_hash")
