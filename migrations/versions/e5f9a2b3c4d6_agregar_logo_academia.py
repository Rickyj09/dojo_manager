"""Agregar identidad visual por academia.

Revision ID: e5f9a2b3c4d6
Revises: d4e8f1a2b3c5
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f9a2b3c4d6"
down_revision = "d4e8f1a2b3c5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("academias") as batch_op:
        batch_op.add_column(sa.Column("logo_filename", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("academias") as batch_op:
        batch_op.drop_column("logo_filename")
