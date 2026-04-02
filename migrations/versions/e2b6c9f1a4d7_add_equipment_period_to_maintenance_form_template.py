"""Add equipment template and period type to maintenance form templates.

Revision ID: e2b6c9f1a4d7
Revises: c6d8e2f4a1b3
Create Date: 2026-04-02 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2b6c9f1a4d7"
down_revision = "c6d8e2f4a1b3"
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

    if not inspector.has_table("maintenance_form_template"):
        return

    if not _has_column(inspector, "maintenance_form_template", "equipment_template_id"):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.add_column(sa.Column("equipment_template_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "maintenance_form_template", "period_type"):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.add_column(sa.Column("period_type", sa.String(length=20), nullable=True))
        inspector = sa.inspect(bind)

    if inspector.has_table("equipment_template") and not _has_fk(
        inspector,
        "maintenance_form_template",
        "equipment_template_id",
        "equipment_template",
    ):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "fk_maintenance_form_template_equipment_template_id_equipment_template",
                "equipment_template",
                ["equipment_template_id"],
                ["id"],
            )
        inspector = sa.inspect(bind)

    if not _has_index(
        inspector,
        "maintenance_form_template",
        "ix_maintenance_form_template_equipment_template_id",
    ):
        op.create_index(
            "ix_maintenance_form_template_equipment_template_id",
            "maintenance_form_template",
            ["equipment_template_id"],
            unique=False,
        )

    if not _has_index(inspector, "maintenance_form_template", "ix_maintenance_form_template_period_type"):
        op.create_index(
            "ix_maintenance_form_template_period_type",
            "maintenance_form_template",
            ["period_type"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("maintenance_form_template"):
        return

    if _has_index(inspector, "maintenance_form_template", "ix_maintenance_form_template_period_type"):
        op.drop_index("ix_maintenance_form_template_period_type", table_name="maintenance_form_template")

    inspector = sa.inspect(bind)
    if _has_index(
        inspector,
        "maintenance_form_template",
        "ix_maintenance_form_template_equipment_template_id",
    ):
        op.drop_index("ix_maintenance_form_template_equipment_template_id", table_name="maintenance_form_template")

    inspector = sa.inspect(bind)
    if _has_fk(
        inspector,
        "maintenance_form_template",
        "equipment_template_id",
        "equipment_template",
    ):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.drop_constraint(
                "fk_maintenance_form_template_equipment_template_id_equipment_template",
                type_="foreignkey",
            )

    inspector = sa.inspect(bind)
    if _has_column(inspector, "maintenance_form_template", "period_type"):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.drop_column("period_type")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "maintenance_form_template", "equipment_template_id"):
        with op.batch_alter_table("maintenance_form_template", schema=None) as batch_op:
            batch_op.drop_column("equipment_template_id")
