"""repair missing islem_log error columns

Revision ID: f3b1a9d4c7e2
Revises: e4a1b9c2d7f0
Create Date: 2026-03-23 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3b1a9d4c7e2"
down_revision = "e4a1b9c2d7f0"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name, index_name):
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def upgrade():
    if not _has_table("islem_log"):
        return

    with op.batch_alter_table("islem_log") as batch_op:
        if not _has_column("islem_log", "error_code"):
            batch_op.add_column(sa.Column("error_code", sa.String(length=32), nullable=True))
        if not _has_column("islem_log", "title"):
            batch_op.add_column(sa.Column("title", sa.String(length=180), nullable=True))
        if not _has_column("islem_log", "user_message"):
            batch_op.add_column(sa.Column("user_message", sa.String(length=255), nullable=True))
        if not _has_column("islem_log", "owner_message"):
            batch_op.add_column(sa.Column("owner_message", sa.Text(), nullable=True))
        if not _has_column("islem_log", "module"):
            batch_op.add_column(sa.Column("module", sa.String(length=24), nullable=True))
        if not _has_column("islem_log", "severity"):
            batch_op.add_column(sa.Column("severity", sa.String(length=20), nullable=True))
        if not _has_column("islem_log", "exception_type"):
            batch_op.add_column(sa.Column("exception_type", sa.String(length=120), nullable=True))
        if not _has_column("islem_log", "exception_message"):
            batch_op.add_column(sa.Column("exception_message", sa.Text(), nullable=True))
        if not _has_column("islem_log", "traceback_summary"):
            batch_op.add_column(sa.Column("traceback_summary", sa.Text(), nullable=True))
        if not _has_column("islem_log", "route"):
            batch_op.add_column(sa.Column("route", sa.String(length=255), nullable=True))
        if not _has_column("islem_log", "method"):
            batch_op.add_column(sa.Column("method", sa.String(length=12), nullable=True))
        if not _has_column("islem_log", "request_id"):
            batch_op.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        if not _has_column("islem_log", "user_email"):
            batch_op.add_column(sa.Column("user_email", sa.String(length=150), nullable=True))
        if not _has_column("islem_log", "resolved"):
            batch_op.add_column(sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()))
        if not _has_column("islem_log", "resolution_note"):
            batch_op.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))
        if not _has_column("islem_log", "ip_address"):
            batch_op.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))

    if not _has_index("islem_log", "ix_islem_log_error_code"):
        op.create_index("ix_islem_log_error_code", "islem_log", ["error_code"], unique=False)
    if not _has_index("islem_log", "ix_islem_log_module"):
        op.create_index("ix_islem_log_module", "islem_log", ["module"], unique=False)
    if not _has_index("islem_log", "ix_islem_log_request_id"):
        op.create_index("ix_islem_log_request_id", "islem_log", ["request_id"], unique=False)
    if not _has_index("islem_log", "ix_islem_log_resolved"):
        op.create_index("ix_islem_log_resolved", "islem_log", ["resolved"], unique=False)
    if not _has_index("islem_log", "ix_islem_log_severity"):
        op.create_index("ix_islem_log_severity", "islem_log", ["severity"], unique=False)


def downgrade():
    pass
