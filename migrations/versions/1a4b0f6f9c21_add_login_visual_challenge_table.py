"""add login visual challenge table

Revision ID: 1a4b0f6f9c21
Revises: 6b2c217fb7ff
Create Date: 2026-03-18 21:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1a4b0f6f9c21"
down_revision = "6b2c217fb7ff"
branch_labels = None
depends_on = None


def upgrade():
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
    with op.batch_alter_table("login_visual_challenge", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_login_visual_challenge_token"), ["token"], unique=True)
        batch_op.create_index(batch_op.f("ix_login_visual_challenge_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_login_visual_challenge_invalidated_at"), ["invalidated_at"], unique=False)


def downgrade():
    with op.batch_alter_table("login_visual_challenge", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_login_visual_challenge_invalidated_at"))
        batch_op.drop_index(batch_op.f("ix_login_visual_challenge_expires_at"))
        batch_op.drop_index(batch_op.f("ix_login_visual_challenge_token"))
    op.drop_table("login_visual_challenge")
