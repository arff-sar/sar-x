"""add brand column to kutu

Revision ID: c9e1a4f2b6d3
Revises: f5a7c3d9e2b1
Create Date: 2026-03-24 21:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9e1a4f2b6d3"
down_revision = "f5a7c3d9e2b1"
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


def upgrade():
    if _has_table("kutu") and not _has_column("kutu", "marka"):
        op.add_column("kutu", sa.Column("marka", sa.String(length=120), nullable=True))


def downgrade():
    # Production güvenliği için bu kolon geri alınmaz.
    pass
