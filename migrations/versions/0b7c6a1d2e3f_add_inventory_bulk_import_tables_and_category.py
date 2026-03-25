"""add inventory bulk import tables and category

Revision ID: 0b7c6a1d2e3f
Revises: f5a7c3d9e2b1
Create Date: 2026-03-26 09:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0b7c6a1d2e3f"
down_revision = "f5a7c3d9e2b1"
branch_labels = None
depends_on = None


def _has_table(bind, table_name):
    return sa.inspect(bind).has_table(table_name)


def upgrade():
    bind = op.get_bind()
    if not _has_table(bind, "inventory_category"):
        op.create_table(
            "inventory_category",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["kullanici.id"]),
            sa.UniqueConstraint("name", name="uq_inventory_category_name"),
        )

    if not _has_table(bind, "inventory_bulk_import_job"):
        op.create_table(
            "inventory_bulk_import_job",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
            sa.Column("havalimani_id", sa.Integer(), nullable=True),
            sa.Column("source_filename", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="completed"),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["kullanici.id"]),
            sa.ForeignKeyConstraint(["havalimani_id"], ["havalimani.id"]),
        )

    if not _has_table(bind, "inventory_bulk_import_row_result"):
        op.create_table(
            "inventory_bulk_import_row_result",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("row_no", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("serial_no", sa.String(length=120), nullable=True),
            sa.Column("asset_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["inventory_asset.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["inventory_bulk_import_job.id"]),
        )


def downgrade():
    bind = op.get_bind()
    if _has_table(bind, "inventory_bulk_import_row_result"):
        op.drop_table("inventory_bulk_import_row_result")
    if _has_table(bind, "inventory_bulk_import_job"):
        op.drop_table("inventory_bulk_import_job")
    if _has_table(bind, "inventory_category"):
        op.drop_table("inventory_category")

