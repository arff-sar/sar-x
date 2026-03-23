"""add drill documents and airport drive folder

Revision ID: e4a1b9c2d7f0
Revises: d2f6e1a4c3b8
Create Date: 2026-03-23 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4a1b9c2d7f0"
down_revision = "d2f6e1a4c3b8"
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

    if not _has_table("tatbikat_belgesi"):
        op.create_table(
            "tatbikat_belgesi",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("havalimani_id", sa.Integer(), nullable=False),
            sa.Column("yukleyen_kullanici_id", sa.Integer(), nullable=False),
            sa.Column("baslik", sa.String(length=180), nullable=False),
            sa.Column("aciklama", sa.Text(), nullable=True),
            sa.Column("dosya_adi", sa.String(length=255), nullable=False),
            sa.Column("drive_file_id", sa.String(length=255), nullable=False),
            sa.Column("drive_folder_id", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=False),
            sa.Column("dosya_boyutu", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["havalimani_id"], ["havalimani.id"]),
            sa.ForeignKeyConstraint(["yukleyen_kullanici_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_havalimani_id"):
        op.create_index("ix_tatbikat_belgesi_havalimani_id", "tatbikat_belgesi", ["havalimani_id"], unique=False)
    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_yukleyen_kullanici_id"):
        op.create_index("ix_tatbikat_belgesi_yukleyen_kullanici_id", "tatbikat_belgesi", ["yukleyen_kullanici_id"], unique=False)
    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_drive_file_id"):
        op.create_index("ix_tatbikat_belgesi_drive_file_id", "tatbikat_belgesi", ["drive_file_id"], unique=True)
    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_drive_folder_id"):
        op.create_index("ix_tatbikat_belgesi_drive_folder_id", "tatbikat_belgesi", ["drive_folder_id"], unique=False)
    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_is_deleted"):
        op.create_index("ix_tatbikat_belgesi_is_deleted", "tatbikat_belgesi", ["is_deleted"], unique=False)


def downgrade():
    pass
