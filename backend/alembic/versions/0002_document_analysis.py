"""Phase 3 — per-document graph analysis rows.

Amends 0001's "later phases add code, not DDL" plan: the Phase 3 design chose a
separate 1:1 document_analysis table over JSON columns on documents (different
owner, wholesale-replace write cadence, and the row doubles as the recompute
completion marker). Mirror of app/storage/tables.py:document_analysis.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_analysis",
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dominant_topic_id", sa.Integer(), nullable=True),
        sa.Column("top_topics", sa.JSON(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("document_analysis")
