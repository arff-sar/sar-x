"""add user settings email change and push preference tables

Revision ID: b9f2d7c4e1a0
Revises: 8d6e4b2c1f90
Create Date: 2026-04-01 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "b9f2d7c4e1a0"
down_revision = "8d6e4b2c1f90"
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
        if not _has_column("kullanici", "ust_beden"):
            op.add_column("kullanici", sa.Column("ust_beden", sa.String(length=8), nullable=True))
        if not _has_column("kullanici", "alt_beden"):
            op.add_column("kullanici", sa.Column("alt_beden", sa.String(length=8), nullable=True))

    if not _has_table("email_change_token"):
        op.create_table(
            "email_change_token",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("old_email", sa.String(length=120), nullable=False),
            sa.Column("new_email", sa.String(length=120), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("requested_from_ip", sa.String(length=45), nullable=True),
            sa.Column("requested_user_agent", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_email_change_token_hash"),
        )
    if _has_table("email_change_token"):
        if not _has_index("email_change_token", "ix_email_change_token_user_id"):
            op.create_index("ix_email_change_token_user_id", "email_change_token", ["user_id"])
        if not _has_index("email_change_token", "ix_email_change_token_token_hash"):
            op.create_index("ix_email_change_token_token_hash", "email_change_token", ["token_hash"], unique=True)
        if not _has_index("email_change_token", "ix_email_change_token_expires_at"):
            op.create_index("ix_email_change_token_expires_at", "email_change_token", ["expires_at"])
        if not _has_index("email_change_token", "ix_email_change_token_consumed_at"):
            op.create_index("ix_email_change_token_consumed_at", "email_change_token", ["consumed_at"])

    if not _has_table("user_notification_preference"):
        op.create_table(
            "user_notification_preference",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("preference_key", sa.String(length=64), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "preference_key", name="uq_user_notification_preference_user_key"),
        )
    if _has_table("user_notification_preference"):
        if not _has_index("user_notification_preference", "ix_user_notification_preference_user_id"):
            op.create_index("ix_user_notification_preference_user_id", "user_notification_preference", ["user_id"])
        if not _has_index("user_notification_preference", "ix_user_notification_preference_preference_key"):
            op.create_index("ix_user_notification_preference_preference_key", "user_notification_preference", ["preference_key"])
        if not _has_index("user_notification_preference", "ix_user_notification_preference_is_enabled"):
            op.create_index("ix_user_notification_preference_is_enabled", "user_notification_preference", ["is_enabled"])

    if not _has_table("push_device_subscription"):
        op.create_table(
            "push_device_subscription",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("device_id", sa.String(length=64), nullable=False),
            sa.Column("platform", sa.String(length=20), nullable=False, server_default="mobile"),
            sa.Column("user_agent", sa.String(length=80), nullable=True),
            sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["kullanici.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "device_id", name="uq_push_device_subscription_user_device"),
        )
    if _has_table("push_device_subscription"):
        if not _has_index("push_device_subscription", "ix_push_device_subscription_user_id"):
            op.create_index("ix_push_device_subscription_user_id", "push_device_subscription", ["user_id"])
        if not _has_index("push_device_subscription", "ix_push_device_subscription_device_id"):
            op.create_index("ix_push_device_subscription_device_id", "push_device_subscription", ["device_id"])
        if not _has_index("push_device_subscription", "ix_push_device_subscription_is_active"):
            op.create_index("ix_push_device_subscription_is_active", "push_device_subscription", ["is_active"])
        if not _has_index("push_device_subscription", "ix_push_device_subscription_last_seen_at"):
            op.create_index("ix_push_device_subscription_last_seen_at", "push_device_subscription", ["last_seen_at"])


def downgrade():
    # Canlı veride kullanıcı ayar geçmişini korumak için geriye dönüşte otomatik silme yapmıyoruz.
    pass
