"""add asset spare part link table

Revision ID: e8c4a1f7d2b0
Revises: c9e1a4f2b6d3
Create Date: 2026-03-25 01:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e8c4a1f7d2b0"
down_revision = "c9e1a4f2b6d3"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name):
    return sa.inspect(bind).has_table(table_name)


def upgrade():
    bind = op.get_bind()
    if _table_exists(bind, "asset_spare_part_link"):
        return

    op.create_table(
        "asset_spare_part_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("spare_part_id", sa.Integer(), nullable=False),
        sa.Column("quantity_required", sa.Float(), nullable=False, server_default="1"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["asset_id"], ["inventory_asset.id"]),
        sa.ForeignKeyConstraint(["spare_part_id"], ["spare_part.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "spare_part_id", name="uq_asset_spare_part_link"),
    )
    op.create_index("ix_asset_spare_part_link_asset_id", "asset_spare_part_link", ["asset_id"], unique=False)
    op.create_index("ix_asset_spare_part_link_spare_part_id", "asset_spare_part_link", ["spare_part_id"], unique=False)
    op.create_index("ix_asset_spare_part_link_is_active", "asset_spare_part_link", ["is_active"], unique=False)


def downgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "asset_spare_part_link"):
        return

    op.drop_index("ix_asset_spare_part_link_is_active", table_name="asset_spare_part_link")
    op.drop_index("ix_asset_spare_part_link_spare_part_id", table_name="asset_spare_part_link")
    op.drop_index("ix_asset_spare_part_link_asset_id", table_name="asset_spare_part_link")
    op.drop_table("asset_spare_part_link")
