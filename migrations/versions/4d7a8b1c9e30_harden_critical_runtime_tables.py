"""harden critical runtime tables

Revision ID: 4d7a8b1c9e30
Revises: c1d9f0a6b221
Create Date: 2026-03-22 17:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d7a8b1c9e30"
down_revision = "c1d9f0a6b221"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_index(table_name, index_name):
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _ensure_site_settings_table():
    if not _has_table("site_ayarlari"):
        op.create_table(
            "site_ayarlari",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("baslik", sa.String(length=200), nullable=True),
            sa.Column("alt_metin", sa.Text(), nullable=True),
            sa.Column("iletisim_notu", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    bind = op.get_bind()
    site_ayarlari = sa.table(
        "site_ayarlari",
        sa.column("id", sa.Integer()),
        sa.column("baslik", sa.String(length=200)),
        sa.column("alt_metin", sa.Text()),
        sa.column("iletisim_notu", sa.Text()),
    )
    baseline_exists = bind.execute(
        sa.select(site_ayarlari.c.id).limit(1)
    ).first()
    if baseline_exists is None:
        bind.execute(
            site_ayarlari.insert().values(
                id=1,
                baslik="SAR-X ARFF SAR",
                alt_metin="",
                iletisim_notu="",
            )
        )


def _ensure_auth_lockout_table():
    if not _has_table("auth_lockout"):
        op.create_table(
            "auth_lockout",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("identifier", sa.String(length=180), nullable=False),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("last_failed_at", sa.DateTime(), nullable=True),
            sa.Column("last_ip", sa.String(length=45), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("auth_lockout", "ix_auth_lockout_identifier"):
        op.create_index("ix_auth_lockout_identifier", "auth_lockout", ["identifier"], unique=True)
    if not _has_index("auth_lockout", "ix_auth_lockout_locked_until"):
        op.create_index("ix_auth_lockout_locked_until", "auth_lockout", ["locked_until"], unique=False)


def _ensure_login_visual_challenge_table():
    if not _has_table("login_visual_challenge"):
        op.create_table(
            "login_visual_challenge",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=96), nullable=False),
            sa.Column("code", sa.String(length=12), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("invalidated_at", sa.DateTime(), nullable=True),
            sa.Column("last_rendered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("login_visual_challenge", "ix_login_visual_challenge_token"):
        op.create_index("ix_login_visual_challenge_token", "login_visual_challenge", ["token"], unique=True)
    if not _has_index("login_visual_challenge", "ix_login_visual_challenge_expires_at"):
        op.create_index("ix_login_visual_challenge_expires_at", "login_visual_challenge", ["expires_at"], unique=False)
    if not _has_index("login_visual_challenge", "ix_login_visual_challenge_invalidated_at"):
        op.create_index("ix_login_visual_challenge_invalidated_at", "login_visual_challenge", ["invalidated_at"], unique=False)


def upgrade():
    _ensure_site_settings_table()
    _ensure_auth_lockout_table()
    _ensure_login_visual_challenge_table()


def downgrade():
    # Production güvenliği için destructive downgrade uygulanmaz.
    pass
