"""add assignment instruction ppe tables

Revision ID: c1d9f0a6b221
Revises: 8f3c1d4a2b77
Create Date: 2026-03-19 21:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d9f0a6b221"
down_revision = "8f3c1d4a2b77"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assignment_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_no", sa.String(length=40), nullable=False),
        sa.Column("assignment_date", sa.Date(), nullable=False),
        sa.Column("delivered_by_id", sa.Integer(), nullable=True),
        sa.Column("airport_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("signed_document_key", sa.String(length=255), nullable=True),
        sa.Column("signed_document_url", sa.String(length=500), nullable=True),
        sa.Column("signed_document_name", sa.String(length=180), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["airport_id"], ["havalimani.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["kullanici.id"]),
        sa.ForeignKeyConstraint(["delivered_by_id"], ["kullanici.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assignment_record", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assignment_record_airport_id"), ["airport_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_record_assignment_date"), ["assignment_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_record_assignment_no"), ["assignment_no"], unique=True)
        batch_op.create_index(batch_op.f("ix_assignment_record_created_by_id"), ["created_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_record_delivered_by_id"), ["delivered_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_record_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_record_status"), ["status"], unique=False)

    op.create_table(
        "assignment_recipient",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment_record.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "user_id", name="uq_assignment_recipient"),
    )
    with op.batch_alter_table("assignment_recipient", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assignment_recipient_assignment_id"), ["assignment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_recipient_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_recipient_user_id"), ["user_id"], unique=False)

    op.create_table(
        "assignment_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("item_name", sa.String(length=180), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("returned_quantity", sa.Float(), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("returned_by_id", sa.Integer(), nullable=True),
        sa.Column("return_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["inventory_asset.id"]),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment_record.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["malzeme.id"]),
        sa.ForeignKeyConstraint(["returned_by_id"], ["kullanici.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assignment_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assignment_item_asset_id"), ["asset_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_item_assignment_id"), ["assignment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_item_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_item_material_id"), ["material_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_item_returned_by_id"), ["returned_by_id"], unique=False)

    op.create_table(
        "assignment_history_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment_record.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["kullanici.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assignment_history_entry", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assignment_history_entry_assignment_id"), ["assignment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_history_entry_created_by_id"), ["created_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_history_entry_event_type"), ["event_type"], unique=False)

    op.create_table(
        "maintenance_instruction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipment_template_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manual_url", sa.String(length=500), nullable=True),
        sa.Column("visual_url", sa.String(length=500), nullable=True),
        sa.Column("revision_no", sa.String(length=40), nullable=True),
        sa.Column("revision_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["equipment_template_id"], ["equipment_template.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("equipment_template_id"),
    )
    with op.batch_alter_table("maintenance_instruction", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_maintenance_instruction_equipment_template_id"), ["equipment_template_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_maintenance_instruction_is_active"), ["is_active"], unique=False)
        batch_op.create_index(batch_op.f("ix_maintenance_instruction_is_deleted"), ["is_deleted"], unique=False)

    op.create_table(
        "ppe_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("airport_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("item_name", sa.String(length=160), nullable=False),
        sa.Column("brand_model", sa.String(length=160), nullable=True),
        sa.Column("size_info", sa.String(length=80), nullable=True),
        sa.Column("delivered_at", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("photo_storage_key", sa.String(length=255), nullable=True),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["airport_id"], ["havalimani.id"]),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment_record.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["kullanici.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ppe_record", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ppe_record_airport_id"), ["airport_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_assignment_id"), ["assignment_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_created_by_id"), ["created_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_delivered_at"), ["delivered_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_user_id"), ["user_id"], unique=False)

    op.create_table(
        "ppe_record_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ppe_record_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("status_after", sa.String(length=30), nullable=False),
        sa.Column("event_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["kullanici.id"]),
        sa.ForeignKeyConstraint(["ppe_record_id"], ["ppe_record.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ppe_record_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ppe_record_event_created_by_id"), ["created_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_event_event_type"), ["event_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_event_ppe_record_id"), ["ppe_record_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ppe_record_event_status_after"), ["status_after"], unique=False)


def downgrade():
    with op.batch_alter_table("ppe_record_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ppe_record_event_status_after"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_event_ppe_record_id"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_event_event_type"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_event_created_by_id"))
    op.drop_table("ppe_record_event")

    with op.batch_alter_table("ppe_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ppe_record_user_id"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_status"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_delivered_at"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_created_by_id"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_assignment_id"))
        batch_op.drop_index(batch_op.f("ix_ppe_record_airport_id"))
    op.drop_table("ppe_record")

    with op.batch_alter_table("maintenance_instruction", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_maintenance_instruction_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_maintenance_instruction_is_active"))
        batch_op.drop_index(batch_op.f("ix_maintenance_instruction_equipment_template_id"))
    op.drop_table("maintenance_instruction")

    with op.batch_alter_table("assignment_history_entry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assignment_history_entry_event_type"))
        batch_op.drop_index(batch_op.f("ix_assignment_history_entry_created_by_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_history_entry_assignment_id"))
    op.drop_table("assignment_history_entry")

    with op.batch_alter_table("assignment_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assignment_item_returned_by_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_item_material_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_item_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_assignment_item_assignment_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_item_asset_id"))
    op.drop_table("assignment_item")

    with op.batch_alter_table("assignment_recipient", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assignment_recipient_user_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_recipient_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_assignment_recipient_assignment_id"))
    op.drop_table("assignment_recipient")

    with op.batch_alter_table("assignment_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assignment_record_status"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_delivered_by_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_created_by_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_assignment_no"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_assignment_date"))
        batch_op.drop_index(batch_op.f("ix_assignment_record_airport_id"))
    op.drop_table("assignment_record")
