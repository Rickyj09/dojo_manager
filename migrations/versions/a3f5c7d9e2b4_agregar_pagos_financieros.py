"""Agregar pagos financieros

Revision ID: a3f5c7d9e2b4
Revises: 9d2a6b4c8e1f
Create Date: 2026-09-02 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a3f5c7d9e2b4"
down_revision = "9d2a6b4c8e1f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pagos_financieros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alumno_id", sa.Integer(), nullable=False),
        sa.Column("fecha_pago", sa.Date(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column(
            "medio_pago",
            sa.Enum("EFECTIVO", "TRANSFERENCIA", "DEPOSITO", "TARJETA", "OTRO", name="fin_pago_medio", native_enum=False),
            nullable=False,
        ),
        sa.Column("referencia", sa.String(length=120), nullable=True),
        sa.Column("observacion", sa.Text(), nullable=True),
        sa.Column(
            "estado",
            sa.Enum("REGISTRADO", "ANULADO", name="fin_pago_estado", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("valor > 0", name="ck_pagos_financieros_valor_positivo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["alumno_id"], ["alumnos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pagos_financieros", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pagos_financieros_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_pagos_financieros_academia_fecha", ["academia_id", "fecha_pago"], unique=False)
        batch_op.create_index("ix_pagos_financieros_alumno_estado", ["academia_id", "alumno_id", "estado"], unique=False)

    op.create_table(
        "pagos_aplicaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pago_id", sa.Integer(), nullable=False),
        sa.Column("obligacion_financiera_id", sa.Integer(), nullable=False),
        sa.Column("valor_aplicado", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("valor_aplicado > 0", name="ck_pagos_aplicaciones_valor_positivo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["obligacion_financiera_id"], ["obligaciones_financieras.id"]),
        sa.ForeignKeyConstraint(["pago_id"], ["pagos_financieros.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pagos_aplicaciones", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pagos_aplicaciones_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_pagos_aplicaciones_obligacion", ["academia_id", "obligacion_financiera_id"], unique=False)
        batch_op.create_index("ix_pagos_aplicaciones_pago", ["academia_id", "pago_id"], unique=False)


def downgrade():
    with op.batch_alter_table("pagos_aplicaciones", schema=None) as batch_op:
        batch_op.drop_index("ix_pagos_aplicaciones_pago")
        batch_op.drop_index("ix_pagos_aplicaciones_obligacion")
        batch_op.drop_index(batch_op.f("ix_pagos_aplicaciones_academia_id"))
    op.drop_table("pagos_aplicaciones")

    with op.batch_alter_table("pagos_financieros", schema=None) as batch_op:
        batch_op.drop_index("ix_pagos_financieros_alumno_estado")
        batch_op.drop_index("ix_pagos_financieros_academia_fecha")
        batch_op.drop_index(batch_op.f("ix_pagos_financieros_academia_id"))
    op.drop_table("pagos_financieros")
