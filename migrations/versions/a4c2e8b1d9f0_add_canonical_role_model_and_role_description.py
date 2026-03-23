"""add canonical role model and role description

Revision ID: a4c2e8b1d9f0
Revises: 9f7e2c1b4d6a
Create Date: 2026-03-23 23:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a4c2e8b1d9f0"
down_revision = "9f7e2c1b4d6a"
branch_labels = None
depends_on = None


ROLE_MAPPINGS = {
    "sahip": "sistem_sorumlusu",
    "sistem_sahibi": "sistem_sorumlusu",
    "yetkili": "ekip_sorumlusu",
    "havalimani_yoneticisi": "ekip_sorumlusu",
    "personel": "ekip_uyesi",
    "editor": "ekip_uyesi",
    "bakim_sorumlusu": "ekip_uyesi",
    "depo_sorumlusu": "ekip_uyesi",
    "readonly": "admin",
    "genel_mudurluk": "admin",
}

CORE_ROLES = [
    (
        "sistem_sorumlusu",
        "Sistem Sorumlusu",
        "global",
        "Tüm modüller, tüm havalimanları ve kritik yönetim işlemleri üzerinde tam yetkiye sahiptir.",
    ),
    (
        "ekip_sorumlusu",
        "Ekip Sorumlusu",
        "airport",
        "Kendi havalimanında envanter, bakım, zimmet, tatbikat ve operasyonel kullanıcı işlemlerini yönetebilir.",
    ),
    (
        "ekip_uyesi",
        "Ekip Üyesi",
        "airport",
        "Kendi havalimanı kapsamındaki operasyon kayıtlarını görüntüler, bakım doldurur ve kendine ait zimmetleri izler.",
    ),
    (
        "admin",
        "Admin",
        "global",
        "Tüm havalimanlarını readonly kapsamda izler; kayıtları denetler, ancak değişiklik yapmaz.",
    ),
]

LEGACY_KEYS = [
    "sahip",
    "sistem_sahibi",
    "yetkili",
    "havalimani_yoneticisi",
    "personel",
    "editor",
    "bakim_sorumlusu",
    "depo_sorumlusu",
    "readonly",
    "genel_mudurluk",
]


def upgrade():
    with op.batch_alter_table("role", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))

    bind = op.get_bind()

    for old_role, new_role in ROLE_MAPPINGS.items():
        bind.execute(
            sa.text("UPDATE kullanici SET rol = :new_role WHERE rol = :old_role"),
            {"old_role": old_role, "new_role": new_role},
        )

    for key, label, scope, description in CORE_ROLES:
        role_id = bind.execute(
            sa.text("SELECT id FROM role WHERE key = :key"),
            {"key": key},
        ).scalar()
        if role_id:
            bind.execute(
                sa.text(
                    """
                    UPDATE role
                    SET label = :label,
                        scope = :scope,
                        description = :description,
                        is_system = 1,
                        is_active = 1
                    WHERE key = :key
                    """
                ),
                {
                    "key": key,
                    "label": label,
                    "scope": scope,
                    "description": description,
                },
            )
        else:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role (key, label, description, scope, is_system, is_active, created_at, updated_at)
                    VALUES (:key, :label, :description, :scope, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "key": key,
                    "label": label,
                    "scope": scope,
                    "description": description,
                },
            )

    for key in LEGACY_KEYS:
        bind.execute(
            sa.text(
                """
                UPDATE role
                SET is_system = 1,
                    is_active = 0
                WHERE key = :key
                """
            ),
            {"key": key},
        )


def downgrade():
    # Destructive role rollback intentionally omitted.
    pass
