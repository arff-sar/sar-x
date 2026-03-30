"""add user measurements and ppe final fields

Revision ID: 7b9e1a2c4d8f
Revises: cfd5e1cc9bd2
Create Date: 2026-03-30 02:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7b9e1a2c4d8f"
down_revision = "cfd5e1cc9bd2"
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


def upgrade():
    if _has_table("kullanici"):
        user_columns = {
            "kan_grubu_harf": sa.Column("kan_grubu_harf", sa.String(length=4), nullable=True),
            "kan_grubu_rh": sa.Column("kan_grubu_rh", sa.String(length=4), nullable=True),
            "boy_cm": sa.Column("boy_cm", sa.Integer(), nullable=True),
            "kilo_kg": sa.Column("kilo_kg", sa.Integer(), nullable=True),
            "ayak_numarasi": sa.Column("ayak_numarasi", sa.Float(), nullable=True),
            "beden": sa.Column("beden", sa.String(length=8), nullable=True),
        }
        for column_name, column in user_columns.items():
            if not _has_column("kullanici", column_name):
                op.add_column("kullanici", column)

    if _has_table("ppe_record"):
        ppe_columns = {
            "category": sa.Column("category", sa.String(length=80), nullable=True),
            "subcategory": sa.Column("subcategory", sa.String(length=120), nullable=True),
            "brand": sa.Column("brand", sa.String(length=120), nullable=True),
            "model_name": sa.Column("model_name", sa.String(length=120), nullable=True),
            "serial_no": sa.Column("serial_no", sa.String(length=120), nullable=True),
            "apparel_size": sa.Column("apparel_size", sa.String(length=16), nullable=True),
            "shoe_size": sa.Column("shoe_size", sa.String(length=16), nullable=True),
            "production_date": sa.Column("production_date", sa.Date(), nullable=True),
            "expiry_date": sa.Column("expiry_date", sa.Date(), nullable=True),
            "physical_condition": sa.Column("physical_condition", sa.String(length=30), nullable=True),
            "is_active": sa.Column("is_active", sa.Boolean(), nullable=True),
            "manufacturer_url": sa.Column("manufacturer_url", sa.String(length=500), nullable=True),
            "signed_document_key": sa.Column("signed_document_key", sa.String(length=255), nullable=True),
            "signed_document_url": sa.Column("signed_document_url", sa.String(length=500), nullable=True),
            "signed_document_name": sa.Column("signed_document_name", sa.String(length=255), nullable=True),
        }
        for column_name, column in ppe_columns.items():
            if not _has_column("ppe_record", column_name):
                op.add_column("ppe_record", column)

        bind = op.get_bind()
        if _has_column("ppe_record", "physical_condition"):
            bind.execute(sa.text("UPDATE ppe_record SET physical_condition = 'iyi' WHERE physical_condition IS NULL"))
        if _has_column("ppe_record", "is_active"):
            bind.execute(sa.text("UPDATE ppe_record SET is_active = TRUE WHERE is_active IS NULL"))
        for index_name, columns in {
            "ix_ppe_record_category": ["category"],
            "ix_ppe_record_subcategory": ["subcategory"],
            "ix_ppe_record_expiry_date": ["expiry_date"],
            "ix_ppe_record_physical_condition": ["physical_condition"],
            "ix_ppe_record_is_active": ["is_active"],
        }.items():
            if not _has_index("ppe_record", index_name):
                op.create_index(index_name, "ppe_record", columns)

    if _has_table("islem_log") and not _has_column("islem_log", "havalimani_id"):
        op.add_column("islem_log", sa.Column("havalimani_id", sa.Integer(), nullable=True))
    if _has_table("islem_log") and not _has_index("islem_log", "ix_islem_log_havalimani_id"):
        op.create_index("ix_islem_log_havalimani_id", "islem_log", ["havalimani_id"])


def downgrade():
    # Geriye uyumlu canlı veri güvenliği için kolonları otomatik silmiyoruz.
    pass
