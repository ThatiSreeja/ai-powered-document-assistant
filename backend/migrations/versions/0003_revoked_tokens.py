"""Persist revoked authentication tokens until they expire."""

from alembic import op
import sqlalchemy as sa

revision = "0003_revoked_tokens"
down_revision = "0002_chat_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])


def downgrade():
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
