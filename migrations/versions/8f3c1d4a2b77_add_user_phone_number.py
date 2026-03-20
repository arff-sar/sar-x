"""add user phone number

Revision ID: 8f3c1d4a2b77
Revises: 1a4b0f6f9c21
Create Date: 2026-03-19 14:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8f3c1d4a2b77"
down_revision = "1a4b0f6f9c21"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("kullanici", schema=None) as batch_op:
        batch_op.add_column(sa.Column("telefon_numarasi", sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("kullanici", schema=None) as batch_op:
        batch_op.drop_column("telefon_numarasi")
