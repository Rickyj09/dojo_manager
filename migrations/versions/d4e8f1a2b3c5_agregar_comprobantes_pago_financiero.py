"""Agregar comprobantes de pago financiero

Revision ID: d4e8f1a2b3c5
Revises: b6c1d8e9f0a2
Create Date: 2026-09-03 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e8f1a2b3c5"
down_revision = "b6c1d8e9f0a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pagos_comprobantes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pago_financiero_id", sa.Integer(), nullable=False),
        sa.Column("nombre_original", sa.String(length=255), nullable=False),
        sa.Column("nombre_interno", sa.String(length=80), nullable=False),
        sa.Column("ruta_relativa", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("observacion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("tamano_bytes > 0", name="ck_pagos_comprobantes_tamano_positivo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["pago_financiero_id"], ["pagos_financieros.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pago_financiero_id", "sha256", name="uq_pagos_comprobantes_pago_sha256"),
    )
    with op.batch_alter_table("pagos_comprobantes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pagos_comprobantes_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_pagos_comprobantes_pago", ["academia_id", "pago_financiero_id"], unique=False)


def downgrade():
    with op.batch_alter_table("pagos_comprobantes", schema=None) as batch_op:
        batch_op.drop_index("ix_pagos_comprobantes_pago")
        batch_op.drop_index(batch_op.f("ix_pagos_comprobantes_academia_id"))
    op.drop_table("pagos_comprobantes")
