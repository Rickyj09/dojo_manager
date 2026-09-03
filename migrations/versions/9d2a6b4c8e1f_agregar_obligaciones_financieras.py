"""Agregar obligaciones financieras

Revision ID: 9d2a6b4c8e1f
Revises: 8c1f0d7e6a2b
Create Date: 2026-09-02 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9d2a6b4c8e1f"
down_revision = "8c1f0d7e6a2b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "obligaciones_financieras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alumno_id", sa.Integer(), nullable=False),
        sa.Column("alumno_plan_financiero_id", sa.Integer(), nullable=True),
        sa.Column("periodo", sa.String(length=7), nullable=False),
        sa.Column(
            "tipo_obligacion",
            sa.Enum(
                "PENSION",
                "MATRICULA",
                "EXAMEN_GRADO",
                "UNIFORME",
                "TORNEO",
                "SEMINARIO",
                "OTRO",
                name="fin_obligacion_tipo",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("concepto", sa.String(length=160), nullable=False),
        sa.Column("origen", sa.String(length=80), nullable=True),
        sa.Column("fecha_emision", sa.Date(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("tarifa_base_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("porcentaje_descuento_snapshot", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("valor_descuento_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("valor_final_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("moneda_snapshot", sa.String(length=3), nullable=False),
        sa.Column(
            "estado",
            sa.Enum("PENDIENTE", "ANULADA", name="fin_obligacion_estado", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("tarifa_base_snapshot >= 0", name="ck_obligaciones_financieras_tarifa_no_negativa"),
        sa.CheckConstraint("valor_descuento_snapshot >= 0", name="ck_obligaciones_financieras_descuento_no_negativo"),
        sa.CheckConstraint("valor_final_snapshot >= 0", name="ck_obligaciones_financieras_final_no_negativo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["alumno_id"], ["alumnos.id"]),
        sa.ForeignKeyConstraint(["alumno_plan_financiero_id"], ["alumnos_planes_financieros.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "academia_id",
            "alumno_id",
            "periodo",
            "tipo_obligacion",
            name="uq_obligaciones_financieras_academia_alumno_periodo_tipo",
        ),
    )
    with op.batch_alter_table("obligaciones_financieras", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_obligaciones_financieras_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_obligaciones_financieras_alumno_periodo", ["academia_id", "alumno_id", "periodo"], unique=False)
        batch_op.create_index("ix_obligaciones_financieras_periodo_estado", ["academia_id", "periodo", "estado"], unique=False)


def downgrade():
    with op.batch_alter_table("obligaciones_financieras", schema=None) as batch_op:
        batch_op.drop_index("ix_obligaciones_financieras_periodo_estado")
        batch_op.drop_index("ix_obligaciones_financieras_alumno_periodo")
        batch_op.drop_index(batch_op.f("ix_obligaciones_financieras_academia_id"))
    op.drop_table("obligaciones_financieras")
