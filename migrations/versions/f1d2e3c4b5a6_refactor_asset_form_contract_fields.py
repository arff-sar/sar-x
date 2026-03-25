"""refactor asset form contract fields

Revision ID: f1d2e3c4b5a6
Revises: e8c4a1f7d2b0
Create Date: 2026-03-25 10:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f1d2e3c4b5a6"
down_revision = "e8c4a1f7d2b0"
branch_labels = None
depends_on = None


def _has_table(bind, table_name):
    return sa.inspect(bind).has_table(table_name)


def _has_column(bind, table_name, column_name):
    if not _has_table(bind, table_name):
        return False
    return column_name in {item["name"] for item in sa.inspect(bind).get_columns(table_name)}


def _safe_add_column(table_name, column):
    bind = op.get_bind()
    if not _has_table(bind, table_name):
        return
    if not _has_column(bind, table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)


def upgrade():
    bind = op.get_bind()

    _safe_add_column(
        "inventory_asset",
        sa.Column("asset_type", sa.String(length=30), nullable=True, server_default="equipment"),
    )
    _safe_add_column(
        "inventory_asset",
        sa.Column("is_demirbas", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _safe_add_column(
        "inventory_asset",
        sa.Column("calibration_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _safe_add_column(
        "inventory_asset",
        sa.Column("calibration_period_days", sa.Integer(), nullable=True),
    )
    _safe_add_column(
        "inventory_asset",
        sa.Column("maintenance_period_months", sa.Integer(), nullable=True),
    )
    _safe_add_column(
        "inventory_asset",
        sa.Column("manual_url", sa.String(length=500), nullable=True),
    )

    _safe_add_column(
        "equipment_template",
        sa.Column("maintenance_period_months", sa.Integer(), nullable=True),
    )

    _safe_add_column(
        "calibration_record",
        sa.Column("certificate_drive_file_id", sa.String(length=255), nullable=True),
    )
    _safe_add_column(
        "calibration_record",
        sa.Column("certificate_drive_folder_id", sa.String(length=255), nullable=True),
    )
    _safe_add_column(
        "calibration_record",
        sa.Column("certificate_mime_type", sa.String(length=120), nullable=True),
    )
    _safe_add_column(
        "calibration_record",
        sa.Column("certificate_size_bytes", sa.Integer(), nullable=True),
    )

    if _has_table(bind, "inventory_asset"):
        if _has_column(bind, "inventory_asset", "asset_tag") and _has_column(bind, "inventory_asset", "is_demirbas"):
            bind.execute(
                sa.text(
                    "UPDATE inventory_asset "
                    "SET is_demirbas = TRUE "
                    "WHERE asset_tag IS NOT NULL AND TRIM(asset_tag) <> ''"
                )
            )

        if _has_column(bind, "inventory_asset", "maintenance_period_days") and _has_column(
            bind, "inventory_asset", "maintenance_period_months"
        ):
            bind.execute(
                sa.text(
                    "UPDATE inventory_asset "
                    "SET maintenance_period_months = CASE "
                    "WHEN maintenance_period_days IS NULL THEN maintenance_period_months "
                    "WHEN maintenance_period_days <= 30 THEN 1 "
                    "WHEN maintenance_period_days >= 360 THEN 12 "
                    "ELSE CAST(((maintenance_period_days + 29) / 30) AS INTEGER) "
                    "END "
                    "WHERE maintenance_period_months IS NULL"
                )
            )

        if _has_column(bind, "inventory_asset", "asset_type"):
            bind.execute(
                sa.text(
                    "UPDATE inventory_asset "
                    "SET asset_type = CASE "
                    "WHEN parent_asset_id IS NOT NULL THEN 'spare_part' "
                    "ELSE 'equipment' END "
                    "WHERE asset_type IS NULL OR TRIM(asset_type) = ''"
                )
            )

    if _has_table(bind, "equipment_template"):
        if _has_column(bind, "equipment_template", "maintenance_period_days") and _has_column(
            bind, "equipment_template", "maintenance_period_months"
        ):
            bind.execute(
                sa.text(
                    "UPDATE equipment_template "
                    "SET maintenance_period_months = CASE "
                    "WHEN maintenance_period_days IS NULL THEN maintenance_period_months "
                    "WHEN maintenance_period_days <= 30 THEN 1 "
                    "WHEN maintenance_period_days >= 360 THEN 12 "
                    "ELSE CAST(((maintenance_period_days + 29) / 30) AS INTEGER) "
                    "END "
                    "WHERE maintenance_period_months IS NULL"
                )
            )


def downgrade():
    bind = op.get_bind()
    if _has_table(bind, "calibration_record"):
        with op.batch_alter_table("calibration_record") as batch_op:
            if _has_column(bind, "calibration_record", "certificate_size_bytes"):
                batch_op.drop_column("certificate_size_bytes")
            if _has_column(bind, "calibration_record", "certificate_mime_type"):
                batch_op.drop_column("certificate_mime_type")
            if _has_column(bind, "calibration_record", "certificate_drive_folder_id"):
                batch_op.drop_column("certificate_drive_folder_id")
            if _has_column(bind, "calibration_record", "certificate_drive_file_id"):
                batch_op.drop_column("certificate_drive_file_id")

    if _has_table(bind, "equipment_template") and _has_column(bind, "equipment_template", "maintenance_period_months"):
        with op.batch_alter_table("equipment_template") as batch_op:
            batch_op.drop_column("maintenance_period_months")

    if _has_table(bind, "inventory_asset"):
        with op.batch_alter_table("inventory_asset") as batch_op:
            if _has_column(bind, "inventory_asset", "manual_url"):
                batch_op.drop_column("manual_url")
            if _has_column(bind, "inventory_asset", "maintenance_period_months"):
                batch_op.drop_column("maintenance_period_months")
            if _has_column(bind, "inventory_asset", "calibration_period_days"):
                batch_op.drop_column("calibration_period_days")
            if _has_column(bind, "inventory_asset", "calibration_required"):
                batch_op.drop_column("calibration_required")
            if _has_column(bind, "inventory_asset", "is_demirbas"):
                batch_op.drop_column("is_demirbas")
            if _has_column(bind, "inventory_asset", "asset_type"):
                batch_op.drop_column("asset_type")
