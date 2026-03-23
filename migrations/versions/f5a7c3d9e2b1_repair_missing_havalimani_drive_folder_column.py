"""repair missing havalimani drive_folder_id column

Revision ID: f5a7c3d9e2b1
Revises: a4c2e8b1d9f0
Create Date: 2026-03-23 23:55:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f5a7c3d9e2b1"
down_revision = "a4c2e8b1d9f0"
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
    if _has_table("havalimani") and not _has_column("havalimani", "drive_folder_id"):
        op.add_column("havalimani", sa.Column("drive_folder_id", sa.String(length=255), nullable=True))

    if _has_table("havalimani") and not _has_index("havalimani", "ix_havalimani_drive_folder_id"):
        op.create_index("ix_havalimani_drive_folder_id", "havalimani", ["drive_folder_id"], unique=False)


def downgrade():
    # Production güvenliği için eksik kolon onarımını geri almak istemiyoruz.
    pass
