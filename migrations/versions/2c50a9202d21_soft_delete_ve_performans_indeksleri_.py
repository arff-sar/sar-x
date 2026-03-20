"""Soft delete ve performans indeksleri eklendi

Revision ID: 2c50a9202d21
Revises:
Create Date: 2026-03-16 22:04:13.190094

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2c50a9202d21"
down_revision = None
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


def _ensure_index(table_name, index_name, columns, unique=False):
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(table_name, index_name):
    if _has_index(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _ensure_column(table_name, column):
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_core_tables():
    if not _has_table("havalimani"):
        op.create_table(
            "havalimani",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ad", sa.String(length=100), nullable=False),
            sa.Column("kodu", sa.String(length=10), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if not _has_table("kullanici"):
        op.create_table(
            "kullanici",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kullanici_adi", sa.String(length=50), nullable=False, unique=True),
            sa.Column("sifre_hash", sa.String(length=256), nullable=True),
            sa.Column("tam_ad", sa.String(length=100), nullable=False),
            sa.Column("rol", sa.String(length=20), nullable=False),
            sa.Column("havalimani_id", sa.Integer(), sa.ForeignKey("havalimani.id"), nullable=True),
            sa.Column("sertifika_tarihi", sa.Date(), nullable=True),
            sa.Column("uzmanlik_alani", sa.String(length=100), nullable=True),
            sa.Column("kayit_tarihi", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if not _has_table("kutu"):
        op.create_table(
            "kutu",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kodu", sa.String(length=50), nullable=False, unique=True),
            sa.Column("konum", sa.String(length=100), nullable=True),
            sa.Column("havalimani_id", sa.Integer(), sa.ForeignKey("havalimani.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if not _has_table("malzeme"):
        op.create_table(
            "malzeme",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ad", sa.String(length=100), nullable=False),
            sa.Column("seri_no", sa.String(length=100), nullable=True, unique=True),
            sa.Column("teknik_ozellikler", sa.Text(), nullable=True),
            sa.Column("stok_miktari", sa.Integer(), nullable=True),
            sa.Column("durum", sa.String(length=20), nullable=True),
            sa.Column("kritik_mi", sa.Boolean(), nullable=True),
            sa.Column("son_bakim_tarihi", sa.Date(), nullable=True),
            sa.Column("gelecek_bakim_tarihi", sa.Date(), nullable=True),
            sa.Column("kalibrasyon_tarihi", sa.Date(), nullable=True),
            sa.Column("kutu_id", sa.Integer(), sa.ForeignKey("kutu.id"), nullable=False),
            sa.Column("havalimani_id", sa.Integer(), sa.ForeignKey("havalimani.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if not _has_table("bakim_kaydi"):
        op.create_table(
            "bakim_kaydi",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("malzeme_id", sa.Integer(), sa.ForeignKey("malzeme.id"), nullable=False),
            sa.Column("yapan_personel_id", sa.Integer(), sa.ForeignKey("kullanici.id"), nullable=True),
            sa.Column("islem_notu", sa.Text(), nullable=False),
            sa.Column("maliyet", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    if not _has_table("islem_log"):
        op.create_table(
            "islem_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kullanici_id", sa.Integer(), sa.ForeignKey("kullanici.id"), nullable=True),
            sa.Column("islem_tipi", sa.String(length=50), nullable=False),
            sa.Column("detay", sa.Text(), nullable=True),
            sa.Column("ip_adresi", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.String(length=200), nullable=True),
            sa.Column("zaman", sa.DateTime(), nullable=True),
        )

    if not _has_table("haber"):
        op.create_table(
            "haber",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("baslik", sa.String(length=200), nullable=False),
            sa.Column("icerik", sa.Text(), nullable=False),
            sa.Column("tarih", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def upgrade():
    _create_core_tables()

    _ensure_column("bakim_kaydi", sa.Column("is_deleted", sa.Boolean(), nullable=True))
    _ensure_column("bakim_kaydi", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _ensure_index("bakim_kaydi", "ix_bakim_kaydi_is_deleted", ["is_deleted"])
    _ensure_index("bakim_kaydi", "ix_bakim_kaydi_malzeme_id", ["malzeme_id"])

    _ensure_index("haber", "ix_haber_tarih", ["tarih"])

    _ensure_column("havalimani", sa.Column("is_deleted", sa.Boolean(), nullable=True))
    _ensure_column("havalimani", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _ensure_index("havalimani", "ix_havalimani_is_deleted", ["is_deleted"])

    _ensure_index("islem_log", "ix_islem_log_kullanici_id", ["kullanici_id"])
    _ensure_index("islem_log", "ix_islem_log_zaman", ["zaman"])

    _ensure_column("kullanici", sa.Column("is_deleted", sa.Boolean(), nullable=True))
    _ensure_column("kullanici", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _ensure_index("kullanici", "ix_kullanici_havalimani_id", ["havalimani_id"])
    _ensure_index("kullanici", "ix_kullanici_is_deleted", ["is_deleted"])
    _ensure_index("kullanici", "ix_kullanici_rol", ["rol"])

    _ensure_column("kutu", sa.Column("is_deleted", sa.Boolean(), nullable=True))
    _ensure_column("kutu", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _ensure_index("kutu", "ix_kutu_havalimani_id", ["havalimani_id"])
    _ensure_index("kutu", "ix_kutu_is_deleted", ["is_deleted"])

    _ensure_column("malzeme", sa.Column("is_deleted", sa.Boolean(), nullable=True))
    _ensure_column("malzeme", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    _ensure_index("malzeme", "ix_malzeme_durum", ["durum"])
    _ensure_index("malzeme", "ix_malzeme_gelecek_bakim_tarihi", ["gelecek_bakim_tarihi"])
    _ensure_index("malzeme", "ix_malzeme_havalimani_id", ["havalimani_id"])
    _ensure_index("malzeme", "ix_malzeme_is_deleted", ["is_deleted"])
    _ensure_index("malzeme", "ix_malzeme_kutu_id", ["kutu_id"])


def downgrade():
    _drop_index_if_exists("malzeme", "ix_malzeme_kutu_id")
    _drop_index_if_exists("malzeme", "ix_malzeme_is_deleted")
    _drop_index_if_exists("malzeme", "ix_malzeme_havalimani_id")
    _drop_index_if_exists("malzeme", "ix_malzeme_gelecek_bakim_tarihi")
    _drop_index_if_exists("malzeme", "ix_malzeme_durum")

    _drop_index_if_exists("kutu", "ix_kutu_is_deleted")
    _drop_index_if_exists("kutu", "ix_kutu_havalimani_id")

    _drop_index_if_exists("kullanici", "ix_kullanici_rol")
    _drop_index_if_exists("kullanici", "ix_kullanici_is_deleted")
    _drop_index_if_exists("kullanici", "ix_kullanici_havalimani_id")

    _drop_index_if_exists("islem_log", "ix_islem_log_zaman")
    _drop_index_if_exists("islem_log", "ix_islem_log_kullanici_id")

    _drop_index_if_exists("havalimani", "ix_havalimani_is_deleted")
    _drop_index_if_exists("haber", "ix_haber_tarih")
    _drop_index_if_exists("bakim_kaydi", "ix_bakim_kaydi_malzeme_id")
    _drop_index_if_exists("bakim_kaydi", "ix_bakim_kaydi_is_deleted")
