"""Agregar familias y plan financiero alumno

Revision ID: 8c1f0d7e6a2b
Revises: 4b7c2e9a1d5f
Create Date: 2026-09-02 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "8c1f0d7e6a2b"
down_revision = "4b7c2e9a1d5f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reglas_descuento", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "decimales_redondeo",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("2"),
            )
        )
        batch_op.create_check_constraint(
            "ck_reglas_descuento_decimales_rango",
            "decimales_redondeo >= 0 AND decimales_redondeo <= 4",
        )

    op.create_table(
        "grupos_familiares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academia_id", "codigo", name="uq_grupos_familiares_academia_codigo"),
    )
    with op.batch_alter_table("grupos_familiares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_grupos_familiares_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_grupos_familiares_academia_activo", ["academia_id", "activo"], unique=False)

    op.create_table(
        "alumnos_grupos_familiares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grupo_familiar_id", sa.Integer(), nullable=False),
        sa.Column("alumno_id", sa.Integer(), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_alumnos_grupos_familiares_fechas"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["alumno_id"], ["alumnos.id"]),
        sa.ForeignKeyConstraint(["grupo_familiar_id"], ["grupos_familiares.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "academia_id",
            "grupo_familiar_id",
            "alumno_id",
            "fecha_inicio",
            name="uq_alumnos_grupos_familiares_membresia",
        ),
    )
    with op.batch_alter_table("alumnos_grupos_familiares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alumnos_grupos_familiares_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_alumnos_grupos_familiares_alumno_activo", ["academia_id", "alumno_id", "activo"], unique=False)
        batch_op.create_index("ix_alumnos_grupos_familiares_grupo_activo", ["academia_id", "grupo_familiar_id", "activo"], unique=False)

    op.create_table(
        "alumnos_planes_financieros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alumno_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("frecuencia_id", sa.Integer(), nullable=False),
        sa.Column("tarifario_id", sa.Integer(), nullable=False),
        sa.Column("tarifa_plan_id", sa.Integer(), nullable=False),
        sa.Column("grupo_familiar_id", sa.Integer(), nullable=True),
        sa.Column("regla_descuento_id", sa.Integer(), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("tarifa_base_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("descuento_porcentaje_snapshot", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("descuento_valor_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("valor_final_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("moneda_snapshot", sa.String(length=3), nullable=False),
        sa.Column(
            "estado",
            sa.Enum("ACTIVO", "FINALIZADO", "CANCELADO", name="fin_alumno_plan_estado", native_enum=False),
            nullable=False,
        ),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_alumnos_planes_financieros_fechas"),
        sa.CheckConstraint("tarifa_base_snapshot >= 0", name="ck_alumnos_planes_financieros_tarifa_no_negativa"),
        sa.CheckConstraint("descuento_valor_snapshot >= 0", name="ck_alumnos_planes_financieros_descuento_no_negativo"),
        sa.CheckConstraint("valor_final_snapshot >= 0", name="ck_alumnos_planes_financieros_final_no_negativo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["alumno_id"], ["alumnos.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["frecuencia_id"], ["frecuencias_entrenamiento.id"]),
        sa.ForeignKeyConstraint(["grupo_familiar_id"], ["grupos_familiares.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["planes_financieros.id"]),
        sa.ForeignKeyConstraint(["regla_descuento_id"], ["reglas_descuento.id"]),
        sa.ForeignKeyConstraint(["tarifa_plan_id"], ["tarifas_plan.id"]),
        sa.ForeignKeyConstraint(["tarifario_id"], ["tarifarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("alumnos_planes_financieros", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alumnos_planes_financieros_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_alumnos_planes_financieros_alumno_estado", ["academia_id", "alumno_id", "estado"], unique=False)
        batch_op.create_index("ix_alumnos_planes_financieros_fechas", ["academia_id", "fecha_inicio", "fecha_fin"], unique=False)


def downgrade():
    with op.batch_alter_table("alumnos_planes_financieros", schema=None) as batch_op:
        batch_op.drop_index("ix_alumnos_planes_financieros_fechas")
        batch_op.drop_index("ix_alumnos_planes_financieros_alumno_estado")
        batch_op.drop_index(batch_op.f("ix_alumnos_planes_financieros_academia_id"))
    op.drop_table("alumnos_planes_financieros")

    with op.batch_alter_table("alumnos_grupos_familiares", schema=None) as batch_op:
        batch_op.drop_index("ix_alumnos_grupos_familiares_grupo_activo")
        batch_op.drop_index("ix_alumnos_grupos_familiares_alumno_activo")
        batch_op.drop_index(batch_op.f("ix_alumnos_grupos_familiares_academia_id"))
    op.drop_table("alumnos_grupos_familiares")

    with op.batch_alter_table("grupos_familiares", schema=None) as batch_op:
        batch_op.drop_index("ix_grupos_familiares_academia_activo")
        batch_op.drop_index(batch_op.f("ix_grupos_familiares_academia_id"))
    op.drop_table("grupos_familiares")

    with op.batch_alter_table("reglas_descuento", schema=None) as batch_op:
        batch_op.drop_constraint("ck_reglas_descuento_decimales_rango", type_="check")
        batch_op.drop_column("decimales_redondeo")
