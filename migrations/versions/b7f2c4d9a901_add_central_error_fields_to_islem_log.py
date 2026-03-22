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


def upgrade():
    with op.batch_alter_table("islem_log") as batch_op:
        batch_op.add_column(sa.Column("error_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column("user_message", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("owner_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("module", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("severity", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("exception_type", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("exception_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("traceback_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("route", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("method", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("user_email", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))
        batch_op.create_index("ix_islem_log_error_code", ["error_code"], unique=False)
        batch_op.create_index("ix_islem_log_module", ["module"], unique=False)
        batch_op.create_index("ix_islem_log_request_id", ["request_id"], unique=False)
        batch_op.create_index("ix_islem_log_resolved", ["resolved"], unique=False)
        batch_op.create_index("ix_islem_log_severity", ["severity"], unique=False)


def downgrade():
    with op.batch_alter_table("islem_log") as batch_op:
        batch_op.drop_index("ix_islem_log_severity")
        batch_op.drop_index("ix_islem_log_resolved")
        batch_op.drop_index("ix_islem_log_request_id")
        batch_op.drop_index("ix_islem_log_module")
        batch_op.drop_index("ix_islem_log_error_code")
        batch_op.drop_column("ip_address")
        batch_op.drop_column("resolution_note")
        batch_op.drop_column("resolved")
        batch_op.drop_column("user_email")
        batch_op.drop_column("request_id")
        batch_op.drop_column("method")
        batch_op.drop_column("route")
        batch_op.drop_column("traceback_summary")
        batch_op.drop_column("exception_message")
        batch_op.drop_column("exception_type")
        batch_op.drop_column("severity")
        batch_op.drop_column("module")
        batch_op.drop_column("owner_message")
        batch_op.drop_column("user_message")
        batch_op.drop_column("title")
        batch_op.drop_column("error_code")
