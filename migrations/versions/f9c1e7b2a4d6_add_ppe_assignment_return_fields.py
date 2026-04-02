"""add return tracking fields to ppe assignment record

Revision ID: f9c1e7b2a4d6
Revises: e2b6c9f1a4d7
Create Date: 2026-04-02 21:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9c1e7b2a4d6"
down_revision = "e2b6c9f1a4d7"
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


def _has_fk(table_name, constrained_column, referred_table):
    if not _has_table(table_name):
        return False
    for fk in _inspector().get_foreign_keys(table_name):
        constrained = fk.get("constrained_columns") or []
        referred = fk.get("referred_table")
        if constrained == [constrained_column] and referred == referred_table:
            return True
    return False


def upgrade():
    if not _has_table("ppe_assignment_record"):
        return

    if not _has_column("ppe_assignment_record", "returned_at"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.add_column(sa.Column("returned_at", sa.DateTime(), nullable=True))

    if not _has_column("ppe_assignment_record", "returned_by_id"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.add_column(sa.Column("returned_by_id", sa.Integer(), nullable=True))

    if not _has_column("ppe_assignment_record", "returned_note"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.add_column(sa.Column("returned_note", sa.Text(), nullable=True))

    if _has_table("kullanici") and not _has_fk("ppe_assignment_record", "returned_by_id", "kullanici"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "fk_ppe_assignment_record_returned_by_id_kullanici",
                "kullanici",
                ["returned_by_id"],
                ["id"],
            )

    if not _has_index("ppe_assignment_record", "ix_ppe_assignment_record_returned_at"):
        op.create_index(
            "ix_ppe_assignment_record_returned_at",
            "ppe_assignment_record",
            ["returned_at"],
            unique=False,
        )

    if not _has_index("ppe_assignment_record", "ix_ppe_assignment_record_returned_by_id"):
        op.create_index(
            "ix_ppe_assignment_record_returned_by_id",
            "ppe_assignment_record",
            ["returned_by_id"],
            unique=False,
        )


def downgrade():
    if not _has_table("ppe_assignment_record"):
        return

    if _has_index("ppe_assignment_record", "ix_ppe_assignment_record_returned_by_id"):
        op.drop_index("ix_ppe_assignment_record_returned_by_id", table_name="ppe_assignment_record")

    if _has_index("ppe_assignment_record", "ix_ppe_assignment_record_returned_at"):
        op.drop_index("ix_ppe_assignment_record_returned_at", table_name="ppe_assignment_record")

    if _has_fk("ppe_assignment_record", "returned_by_id", "kullanici"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.drop_constraint("fk_ppe_assignment_record_returned_by_id_kullanici", type_="foreignkey")

    if _has_column("ppe_assignment_record", "returned_note"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.drop_column("returned_note")

    if _has_column("ppe_assignment_record", "returned_by_id"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.drop_column("returned_by_id")

    if _has_column("ppe_assignment_record", "returned_at"):
        with op.batch_alter_table("ppe_assignment_record", schema=None) as batch_op:
            batch_op.drop_column("returned_at")
