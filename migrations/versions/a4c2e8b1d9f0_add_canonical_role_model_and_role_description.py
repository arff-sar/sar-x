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


def _inspector(bind):
    return sa.inspect(bind)


def _has_column(bind, table_name, column_name):
    if not _inspector(bind).has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector(bind).get_columns(table_name)}


def _role_table():
    return sa.table(
        "role",
        sa.column("id", sa.Integer()),
        sa.column("key", sa.String(length=50)),
        sa.column("label", sa.String(length=100)),
        sa.column("description", sa.Text()),
        sa.column("scope", sa.String(length=20)),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )


def _core_role_insert_statement(role_table):
    return sa.insert(role_table).values(
        key=sa.bindparam("role_key"),
        label=sa.bindparam("role_label"),
        description=sa.bindparam("role_description"),
        scope=sa.bindparam("role_scope"),
        is_system=sa.true(),
        is_active=sa.true(),
        created_at=sa.func.current_timestamp(),
        updated_at=sa.func.current_timestamp(),
    )


def _core_role_update_statement(role_table):
    return (
        sa.update(role_table)
        .where(role_table.c.key == sa.bindparam("lookup_key"))
        .values(
            label=sa.bindparam("role_label"),
            scope=sa.bindparam("role_scope"),
            description=sa.bindparam("role_description"),
            is_system=sa.true(),
            is_active=sa.true(),
        )
    )


def _legacy_role_deactivate_statement(role_table):
    return (
        sa.update(role_table)
        .where(role_table.c.key == sa.bindparam("legacy_lookup_key"))
        .values(
            is_system=sa.true(),
            is_active=sa.false(),
        )
    )


def upgrade():
    bind = op.get_bind()
    role_table = _role_table()

    if not _has_column(bind, "role", "description"):
        with op.batch_alter_table("role", schema=None) as batch_op:
            batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))

    for old_role, new_role in ROLE_MAPPINGS.items():
        bind.execute(
            sa.text("UPDATE kullanici SET rol = :new_role WHERE rol = :old_role"),
            {"old_role": old_role, "new_role": new_role},
        )

    for key, label, scope, description in CORE_ROLES:
        role_id = bind.execute(
            sa.select(role_table.c.id).where(role_table.c.key == sa.bindparam("lookup_key")),
            {"lookup_key": key},
        ).scalar()
        if role_id:
            bind.execute(
                _core_role_update_statement(role_table),
                {
                    "lookup_key": key,
                    "role_label": label,
                    "role_scope": scope,
                    "role_description": description,
                },
            )
        else:
            bind.execute(
                _core_role_insert_statement(role_table),
                {
                    "role_key": key,
                    "role_label": label,
                    "role_scope": scope,
                    "role_description": description,
                },
            )

    for key in LEGACY_KEYS:
        bind.execute(
            _legacy_role_deactivate_statement(role_table),
            {"legacy_lookup_key": key},
        )


def downgrade():
    # Destructive role rollback intentionally omitted.
    pass
