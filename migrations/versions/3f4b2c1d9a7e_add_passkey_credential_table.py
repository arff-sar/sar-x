"""add passkey credential table

Revision ID: 3f4b2c1d9a7e
Revises: 7b9e1a2c4d8f
Create Date: 2026-03-31 01:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "3f4b2c1d9a7e"
down_revision = "7b9e1a2c4d8f"
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
    if not _has_table("passkey_credential"):
        op.create_table(
            "passkey_credential",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("credential_id", sa.String(length=255), nullable=False),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("algorithm", sa.Integer(), nullable=False),
            sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transports_json", sa.Text(), nullable=True),
            sa.Column("backup_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("backup_state", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("passkey_credential", "ix_passkey_credential_user_id"):
        op.create_index("ix_passkey_credential_user_id", "passkey_credential", ["user_id"])
    if not _has_index("passkey_credential", "ix_passkey_credential_credential_id"):
        op.create_index("ix_passkey_credential_credential_id", "passkey_credential", ["credential_id"], unique=True)
    if not _has_index("passkey_credential", "ix_passkey_credential_last_used_at"):
        op.create_index("ix_passkey_credential_last_used_at", "passkey_credential", ["last_used_at"])


def downgrade():
    with op.batch_alter_table("passkey_credential", schema=None) as batch_op:
        batch_op.drop_index("ix_passkey_credential_last_used_at")
        batch_op.drop_index("ix_passkey_credential_credential_id")
        batch_op.drop_index("ix_passkey_credential_user_id")
    op.drop_table("passkey_credential")
