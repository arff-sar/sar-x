"""Add PPE-specific assignment link column to ppe_record.

Revision ID: c6d8e2f4a1b3
Revises: a7b1c3d5e9f1
Create Date: 2026-04-02 16:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6d8e2f4a1b3"
down_revision = "a7b1c3d5e9f1"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name, index_name):
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _has_fk(inspector, table_name, constrained_column, referred_table):
    for fk in inspector.get_foreign_keys(table_name):
        constrained = fk.get("constrained_columns") or []
        referred = fk.get("referred_table")
        if constrained == [constrained_column] and referred == referred_table:
            return True
    return False


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("ppe_record") or not inspector.has_table("ppe_assignment_record"):
        return

    if not _has_column(inspector, "ppe_record", "ppe_assignment_id"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.add_column(sa.Column("ppe_assignment_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_fk(inspector, "ppe_record", "ppe_assignment_id", "ppe_assignment_record"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "fk_ppe_record_ppe_assignment_id_ppe_assignment_record",
                "ppe_assignment_record",
                ["ppe_assignment_id"],
                ["id"],
            )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "ppe_record", "ix_ppe_record_ppe_assignment_id"):
        op.create_index(
            "ix_ppe_record_ppe_assignment_id",
            "ppe_record",
            ["ppe_assignment_id"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ppe_record"):
        return

    if _has_index(inspector, "ppe_record", "ix_ppe_record_ppe_assignment_id"):
        op.drop_index("ix_ppe_record_ppe_assignment_id", table_name="ppe_record")

    inspector = sa.inspect(bind)
    if _has_fk(inspector, "ppe_record", "ppe_assignment_id", "ppe_assignment_record"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.drop_constraint(
                "fk_ppe_record_ppe_assignment_id_ppe_assignment_record",
                type_="foreignkey",
            )

    inspector = sa.inspect(bind)
    if _has_column(inspector, "ppe_record", "ppe_assignment_id"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.drop_column("ppe_assignment_id")
