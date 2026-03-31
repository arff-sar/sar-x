"""add passkey credential lifecycle fields

Revision ID: 8d6e4b2c1f90
Revises: 3f4b2c1d9a7e
Create Date: 2026-03-31 10:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "8d6e4b2c1f90"
down_revision = "3f4b2c1d9a7e"
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
    if not _has_table("passkey_credential"):
        return

    if not _has_column("passkey_credential", "friendly_name"):
        op.add_column("passkey_credential", sa.Column("friendly_name", sa.String(length=120), nullable=True))
    if not _has_column("passkey_credential", "is_active"):
        op.add_column(
            "passkey_credential",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if not _has_column("passkey_credential", "revoked_at"):
        op.add_column("passkey_credential", sa.Column("revoked_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    if _has_column("passkey_credential", "is_active"):
        bind.execute(sa.text("UPDATE passkey_credential SET is_active = TRUE WHERE is_active IS NULL"))

    if not _has_index("passkey_credential", "ix_passkey_credential_is_active"):
        op.create_index("ix_passkey_credential_is_active", "passkey_credential", ["is_active"])
    if not _has_index("passkey_credential", "ix_passkey_credential_revoked_at"):
        op.create_index("ix_passkey_credential_revoked_at", "passkey_credential", ["revoked_at"])


def downgrade():
    if not _has_table("passkey_credential"):
        return

    with op.batch_alter_table("passkey_credential", schema=None) as batch_op:
        if _has_index("passkey_credential", "ix_passkey_credential_revoked_at"):
            batch_op.drop_index("ix_passkey_credential_revoked_at")
        if _has_index("passkey_credential", "ix_passkey_credential_is_active"):
            batch_op.drop_index("ix_passkey_credential_is_active")
        if _has_column("passkey_credential", "revoked_at"):
            batch_op.drop_column("revoked_at")
        if _has_column("passkey_credential", "is_active"):
            batch_op.drop_column("is_active")
        if _has_column("passkey_credential", "friendly_name"):
            batch_op.drop_column("friendly_name")
