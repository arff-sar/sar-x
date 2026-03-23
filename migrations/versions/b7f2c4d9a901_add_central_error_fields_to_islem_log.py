"""add central error fields to islem_log

Revision ID: b7f2c4d9a901
Revises: 8f3c1d4a2b77
Create Date: 2026-03-22 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7f2c4d9a901"
down_revision = "8f3c1d4a2b77"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table_name, column_name):
    if not _inspector().has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name, index_name):
    if not _inspector().has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def upgrade():
    columns_to_add = [
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=True),
        sa.Column("user_message", sa.String(length=255), nullable=True),
        sa.Column("owner_message", sa.Text(), nullable=True),
        sa.Column("module", sa.String(length=24), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("exception_type", sa.String(length=120), nullable=True),
        sa.Column("exception_message", sa.Text(), nullable=True),
        sa.Column("traceback_summary", sa.Text(), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=12), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("user_email", sa.String(length=150), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
    ]

    for column in columns_to_add:
        if not _has_column("islem_log", column.name):
            op.add_column("islem_log", column)

    indexes_to_add = [
        ("ix_islem_log_error_code", ["error_code"]),
        ("ix_islem_log_module", ["module"]),
        ("ix_islem_log_request_id", ["request_id"]),
        ("ix_islem_log_resolved", ["resolved"]),
        ("ix_islem_log_severity", ["severity"]),
    ]
    for index_name, columns in indexes_to_add:
        if not _has_index("islem_log", index_name):
            op.create_index(index_name, "islem_log", columns, unique=False)


def downgrade():
    indexes_to_drop = [
        "ix_islem_log_severity",
        "ix_islem_log_resolved",
        "ix_islem_log_request_id",
        "ix_islem_log_module",
        "ix_islem_log_error_code",
    ]
    for index_name in indexes_to_drop:
        if _has_index("islem_log", index_name):
            op.drop_index(index_name, table_name="islem_log")

    columns_to_drop = [
        "ip_address",
        "resolution_note",
        "resolved",
        "user_email",
        "request_id",
        "method",
        "route",
        "traceback_summary",
        "exception_message",
        "exception_type",
        "severity",
        "module",
        "owner_message",
        "user_message",
        "title",
        "error_code",
    ]
    for column_name in columns_to_drop:
        if _has_column("islem_log", column_name):
            op.drop_column("islem_log", column_name)
