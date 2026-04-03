"""Add PPE assignment tables and allow pool PPE records without person.

Revision ID: a7b1c3d5e9f1
Revises: d4c3b2a1e9f8
Create Date: 2026-04-02 13:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b1c3d5e9f1"
down_revision = "d4c3b2a1e9f8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("ppe_record"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.Integer(),
                nullable=True,
                existing_nullable=False,
            )

    if not inspector.has_table("ppe_assignment_record"):
        op.create_table(
            "ppe_assignment_record",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assignment_no", sa.String(length=40), nullable=False),
            sa.Column("assignment_date", sa.Date(), nullable=False),
            sa.Column("delivered_by_id", sa.Integer(), nullable=True),
            sa.Column("delivered_by_name", sa.String(length=160), nullable=False),
            sa.Column("recipient_user_id", sa.Integer(), nullable=False),
            sa.Column("airport_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("signed_document_key", sa.String(length=255), nullable=True),
            sa.Column("signed_document_url", sa.String(length=500), nullable=True),
            sa.Column("signed_document_name", sa.String(length=180), nullable=True),
            sa.Column("signed_document_drive_file_id", sa.String(length=255), nullable=True),
            sa.Column("signed_document_drive_folder_id", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["airport_id"], ["havalimani.id"]),
            sa.ForeignKeyConstraint(["created_by_id"], ["kullanici.id"]),
            sa.ForeignKeyConstraint(["delivered_by_id"], ["kullanici.id"]),
            sa.ForeignKeyConstraint(["recipient_user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assignment_no"),
        )
        op.create_index(op.f("ix_ppe_assignment_record_assignment_date"), "ppe_assignment_record", ["assignment_date"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_airport_id"), "ppe_assignment_record", ["airport_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_created_by_id"), "ppe_assignment_record", ["created_by_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_delivered_by_id"), "ppe_assignment_record", ["delivered_by_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_is_deleted"), "ppe_assignment_record", ["is_deleted"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_recipient_user_id"), "ppe_assignment_record", ["recipient_user_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_record_status"), "ppe_assignment_record", ["status"], unique=False)

    if not inspector.has_table("ppe_assignment_item"):
        op.create_table(
            "ppe_assignment_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assignment_id", sa.Integer(), nullable=False),
            sa.Column("ppe_record_id", sa.Integer(), nullable=True),
            sa.Column("item_name", sa.String(length=160), nullable=False),
            sa.Column("category", sa.String(length=80), nullable=True),
            sa.Column("subcategory", sa.String(length=120), nullable=True),
            sa.Column("brand", sa.String(length=120), nullable=True),
            sa.Column("model_name", sa.String(length=120), nullable=True),
            sa.Column("serial_no", sa.String(length=120), nullable=True),
            sa.Column("size_info", sa.String(length=80), nullable=True),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(length=30), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["assignment_id"], ["ppe_assignment_record.id"]),
            sa.ForeignKeyConstraint(["ppe_record_id"], ["ppe_record.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ppe_assignment_item_assignment_id"), "ppe_assignment_item", ["assignment_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_item_category"), "ppe_assignment_item", ["category"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_item_is_deleted"), "ppe_assignment_item", ["is_deleted"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_item_ppe_record_id"), "ppe_assignment_item", ["ppe_record_id"], unique=False)
        op.create_index(op.f("ix_ppe_assignment_item_subcategory"), "ppe_assignment_item", ["subcategory"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("ppe_assignment_item"):
        op.drop_index(op.f("ix_ppe_assignment_item_subcategory"), table_name="ppe_assignment_item")
        op.drop_index(op.f("ix_ppe_assignment_item_ppe_record_id"), table_name="ppe_assignment_item")
        op.drop_index(op.f("ix_ppe_assignment_item_is_deleted"), table_name="ppe_assignment_item")
        op.drop_index(op.f("ix_ppe_assignment_item_category"), table_name="ppe_assignment_item")
        op.drop_index(op.f("ix_ppe_assignment_item_assignment_id"), table_name="ppe_assignment_item")
        op.drop_table("ppe_assignment_item")

    if inspector.has_table("ppe_assignment_record"):
        op.drop_index(op.f("ix_ppe_assignment_record_status"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_recipient_user_id"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_is_deleted"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_delivered_by_id"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_created_by_id"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_airport_id"), table_name="ppe_assignment_record")
        op.drop_index(op.f("ix_ppe_assignment_record_assignment_date"), table_name="ppe_assignment_record")
        op.drop_table("ppe_assignment_record")

    if inspector.has_table("ppe_record"):
        with op.batch_alter_table("ppe_record", schema=None) as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.Integer(),
                nullable=False,
                existing_nullable=True,
            )
