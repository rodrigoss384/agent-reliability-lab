"""create conversation history

Revision ID: cf45ebdd644d
Revises: 0001_knowledge_base
Create Date: 2026-08-11
"""
import sqlalchemy as sa
from alembic import op

revision = "cf45ebdd644d"
down_revision = "0001_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 09-tasks.md says: "Validar seed sintético, migration e dimensão vetorial sem escrita parcial; persistir só metadados permitidos do resultado da slice."
    # We will persist conversation turns. Since Redis handles 24h conversation history TTL sliding window,
    # but 09-tasks.md also mentions "Validar seed sintético, migration e dimensão vetorial sem escrita parcial; persistir só metadados permitidos do resultado da slice."
    # Let's create a table for conversation metadata or turns if needed.
    # In the project specs, "traces persistidos guardam apenas metadados sanitizados"
    # Let's create a table `conversation_turns` or `chat_traces` to persist allowed metadata of the slice.
    op.create_table(
        "conversation_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("retrieved_count", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("guardrail_state", sa.String(50), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_length(session_id) > 0", name="ck_conversation_traces_session_nonempty"),
    )


def downgrade() -> None:
    op.drop_table("conversation_traces")
