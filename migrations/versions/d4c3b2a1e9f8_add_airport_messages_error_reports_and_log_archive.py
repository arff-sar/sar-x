"""add airport messages, error reports and log archive tables

Revision ID: d4c3b2a1e9f8
Revises: b9f2d7c4e1a0
Create Date: 2026-04-01 15:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "d4c3b2a1e9f8"
down_revision = "b9f2d7c4e1a0"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_index(table_name, index_name):
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def upgrade():
    if not _has_table("airport_message"):
        op.create_table(
            "airport_message",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("havalimani_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("message_text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["havalimani_id"], ["havalimani.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if _has_table("airport_message"):
        if not _has_index("airport_message", "ix_airport_message_havalimani_id"):
            op.create_index("ix_airport_message_havalimani_id", "airport_message", ["havalimani_id"])
        if not _has_index("airport_message", "ix_airport_message_user_id"):
            op.create_index("ix_airport_message_user_id", "airport_message", ["user_id"])
        if not _has_index("airport_message", "ix_airport_message_created_at"):
            op.create_index("ix_airport_message_created_at", "airport_message", ["created_at"])

    if not _has_table("error_report"):
        op.create_table(
            "error_report",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("havalimani_id", sa.Integer(), nullable=True),
            sa.Column("role_key", sa.String(length=40), nullable=True),
            sa.Column("path", sa.String(length=255), nullable=False),
            sa.Column("error_code", sa.String(length=32), nullable=False),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("error_summary", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["havalimani_id"], ["havalimani.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if _has_table("error_report"):
        if not _has_index("error_report", "ix_error_report_user_id"):
            op.create_index("ix_error_report_user_id", "error_report", ["user_id"])
        if not _has_index("error_report", "ix_error_report_havalimani_id"):
            op.create_index("ix_error_report_havalimani_id", "error_report", ["havalimani_id"])
        if not _has_index("error_report", "ix_error_report_role_key"):
            op.create_index("ix_error_report_role_key", "error_report", ["role_key"])
        if not _has_index("error_report", "ix_error_report_error_code"):
            op.create_index("ix_error_report_error_code", "error_report", ["error_code"])
        if not _has_index("error_report", "ix_error_report_request_id"):
            op.create_index("ix_error_report_request_id", "error_report", ["request_id"])
        if not _has_index("error_report", "ix_error_report_created_at"):
            op.create_index("ix_error_report_created_at", "error_report", ["created_at"])

    if not _has_table("islem_log_archive"):
        op.create_table(
            "islem_log_archive",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_log_id", sa.Integer(), nullable=False),
            sa.Column("archive_scope", sa.String(length=20), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("archived_by_user_id", sa.Integer(), nullable=False),
            sa.Column("archived_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["archived_by_user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if _has_table("islem_log_archive"):
        if not _has_index("islem_log_archive", "ix_islem_log_archive_source_log_id"):
            op.create_index("ix_islem_log_archive_source_log_id", "islem_log_archive", ["source_log_id"])
        if not _has_index("islem_log_archive", "ix_islem_log_archive_archive_scope"):
            op.create_index("ix_islem_log_archive_archive_scope", "islem_log_archive", ["archive_scope"])
        if not _has_index("islem_log_archive", "ix_islem_log_archive_archived_by_user_id"):
            op.create_index("ix_islem_log_archive_archived_by_user_id", "islem_log_archive", ["archived_by_user_id"])
        if not _has_index("islem_log_archive", "ix_islem_log_archive_archived_at"):
            op.create_index("ix_islem_log_archive_archived_at", "islem_log_archive", ["archived_at"])


def downgrade():
    # Canlı ortamdaki arşiv ve mesaj verilerini otomatik geri silmiyoruz.
    pass
