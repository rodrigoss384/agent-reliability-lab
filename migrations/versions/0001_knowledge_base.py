"""create synthetic knowledge base with pgvector

Revision ID: 0001_knowledge_base
Revises:
Create Date: 2026-08-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_knowledge_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_length(source) > 0", name="ck_knowledge_documents_source_nonempty"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_documents")
