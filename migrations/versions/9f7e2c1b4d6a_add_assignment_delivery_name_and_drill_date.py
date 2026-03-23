"""add assignment delivery name and drill date

Revision ID: 9f7e2c1b4d6a
Revises: f3b1a9d4c7e2
Create Date: 2026-03-23 20:32:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f7e2c1b4d6a"
down_revision = "f3b1a9d4c7e2"
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
    if not _has_column("assignment_record", "delivered_by_name"):
        op.add_column("assignment_record", sa.Column("delivered_by_name", sa.String(length=160), nullable=True))

    if not _has_column("tatbikat_belgesi", "tatbikat_tarihi"):
        op.add_column("tatbikat_belgesi", sa.Column("tatbikat_tarihi", sa.Date(), nullable=True))
    if not _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_tatbikat_tarihi"):
        op.create_index("ix_tatbikat_belgesi_tatbikat_tarihi", "tatbikat_belgesi", ["tatbikat_tarihi"], unique=False)


def downgrade():
    if _has_index("tatbikat_belgesi", "ix_tatbikat_belgesi_tatbikat_tarihi"):
        op.drop_index("ix_tatbikat_belgesi_tatbikat_tarihi", table_name="tatbikat_belgesi")
    if _has_column("tatbikat_belgesi", "tatbikat_tarihi"):
        op.drop_column("tatbikat_belgesi", "tatbikat_tarihi")

    if _has_column("assignment_record", "delivered_by_name"):
        op.drop_column("assignment_record", "delivered_by_name")
