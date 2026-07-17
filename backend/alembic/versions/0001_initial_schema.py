"""Initial schema — the COMPLETE DocMesh schema, including the Phase-3 graph tables.

Shipping everything in one migration is deliberate: the schema was designed up front,
so later phases add code, not DDL. Mirror of app/storage/tables.py.

Revision ID: 0001
Revises:
Create Date: 2026-07-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(8), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "file_type IN ('pdf','docx','txt','md')", name="ck_documents_file_type"
        ),
        sa.CheckConstraint(
            "status IN ('queued','parsing','chunking','embedding','indexing','done','failed')",
            name="ck_documents_status",
        ),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=True)
    op.create_index("ix_documents_created_at", "documents", ["created_at"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vector_id", sa.Integer(), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_vector_id", "chunks", ["vector_id"], unique=True)
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"])

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ingestion_events_document_id_id", "ingestion_events", ["document_id", "id"]
    )

    op.create_table(
        "edges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "source_doc_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_doc_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("semantic_score", sa.Float(), nullable=True),
        sa.Column("entity_score", sa.Float(), nullable=True),
        sa.Column("topic_score", sa.Float(), nullable=True),
        sa.Column("combined_score", sa.Float(), nullable=False),
        sa.Column("top_pairs", sa.JSON(), nullable=True),
        sa.Column("shared_entities", sa.JSON(), nullable=True),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_doc_id < target_doc_id", name="ck_edges_ordered_pair"),
        sa.UniqueConstraint("source_doc_id", "target_doc_id", name="uq_edges_doc_pair"),
    )
    op.create_index("ix_edges_source_doc_id", "edges", ["source_doc_id"])
    op.create_index("ix_edges_target_doc_id", "edges", ["target_doc_id"])
    op.create_index("ix_edges_combined_score", "edges", ["combined_score"])

    op.create_table(
        "edge_explanations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column(
            "edge_id",
            sa.String(32),
            sa.ForeignKey("edges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cache_key", name="uq_edge_explanations_cache_key"),
    )


def downgrade() -> None:
    op.drop_table("edge_explanations")
    op.drop_table("edges")
    op.drop_table("ingestion_events")
    op.drop_table("chunks")
    op.drop_table("documents")
