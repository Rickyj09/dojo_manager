"""Agregar configuracion de vencimiento financiero

Revision ID: b6c1d8e9f0a2
Revises: a3f5c7d9e2b4
Create Date: 2026-09-03 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b6c1d8e9f0a2"
down_revision = "a3f5c7d9e2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "configuraciones_financieras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dia_vencimiento_pension", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "dia_vencimiento_pension IS NULL OR (dia_vencimiento_pension >= 1 AND dia_vencimiento_pension <= 31)",
            name="ck_configuraciones_financieras_dia_vencimiento_pension",
        ),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academia_id", name="uq_configuraciones_financieras_academia"),
    )
    with op.batch_alter_table("configuraciones_financieras", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_configuraciones_financieras_academia_id"), ["academia_id"], unique=False)


def downgrade():
    with op.batch_alter_table("configuraciones_financieras", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_configuraciones_financieras_academia_id"))
    op.drop_table("configuraciones_financieras")
