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


def upgrade():
    with op.batch_alter_table("assignment_record", schema=None) as batch_op:
        batch_op.add_column(sa.Column("delivered_by_name", sa.String(length=160), nullable=True))

    with op.batch_alter_table("tatbikat_belgesi", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tatbikat_tarihi", sa.Date(), nullable=True))
        batch_op.create_index(batch_op.f("ix_tatbikat_belgesi_tatbikat_tarihi"), ["tatbikat_tarihi"], unique=False)


def downgrade():
    with op.batch_alter_table("tatbikat_belgesi", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tatbikat_belgesi_tatbikat_tarihi"))
        batch_op.drop_column("tatbikat_tarihi")

    with op.batch_alter_table("assignment_record", schema=None) as batch_op:
        batch_op.drop_column("delivered_by_name")
