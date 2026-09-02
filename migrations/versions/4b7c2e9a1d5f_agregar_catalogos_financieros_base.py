"""Agregar catalogos financieros base

Revision ID: 4b7c2e9a1d5f
Revises: b1fa7a3cb11a
Create Date: 2026-09-02 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "4b7c2e9a1d5f"
down_revision = "b1fa7a3cb11a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planes_financieros",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("objetivo", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academia_id", "codigo", name="uq_planes_financieros_academia_codigo"),
    )
    with op.batch_alter_table("planes_financieros", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_planes_financieros_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_planes_financieros_academia_activo", ["academia_id", "activo"], unique=False)

    op.create_table(
        "frecuencias_entrenamiento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("dias_semana", sa.Integer(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("dias_semana >= 0", name="ck_frecuencias_entrenamiento_dias_no_negativo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academia_id", "codigo", name="uq_frecuencias_entrenamiento_academia_codigo"),
    )
    with op.batch_alter_table("frecuencias_entrenamiento", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_frecuencias_entrenamiento_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_frecuencias_entrenamiento_academia_activo", ["academia_id", "activo"], unique=False)

    op.create_table(
        "tarifarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_inicio_vigencia", sa.Date(), nullable=False),
        sa.Column("fecha_fin_vigencia", sa.Date(), nullable=True),
        sa.Column(
            "estado",
            sa.Enum("BORRADOR", "VIGENTE", "CERRADO", name="fin_tarifario_estado", native_enum=False),
            nullable=False,
        ),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "fecha_fin_vigencia IS NULL OR fecha_fin_vigencia >= fecha_inicio_vigencia",
            name="ck_tarifarios_fechas_coherentes",
        ),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tarifarios", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tarifarios_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_tarifarios_academia_estado", ["academia_id", "estado"], unique=False)

    op.create_table(
        "reglas_descuento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum("HERMANOS", "BECA", "CONVENIO", "PROMOCION", "ESPECIAL", "OTRO", name="fin_regla_descuento_tipo", native_enum=False),
            nullable=False,
        ),
        sa.Column("porcentaje", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("valor_fijo", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("cantidad_minima", sa.Integer(), nullable=True),
        sa.Column("requiere_autorizacion", sa.Boolean(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("vigencia_desde", sa.Date(), nullable=True),
        sa.Column("vigencia_hasta", sa.Date(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("porcentaje IS NULL OR (porcentaje >= 0 AND porcentaje <= 100)", name="ck_reglas_descuento_porcentaje_rango"),
        sa.CheckConstraint("valor_fijo IS NULL OR valor_fijo >= 0", name="ck_reglas_descuento_valor_fijo_no_negativo"),
        sa.CheckConstraint("cantidad_minima IS NULL OR cantidad_minima >= 0", name="ck_reglas_descuento_cantidad_no_negativa"),
        sa.CheckConstraint("porcentaje IS NULL OR valor_fijo IS NULL", name="ck_reglas_descuento_un_modo"),
        sa.CheckConstraint("vigencia_hasta IS NULL OR vigencia_desde IS NULL OR vigencia_hasta >= vigencia_desde", name="ck_reglas_descuento_fechas_coherentes"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("academia_id", "codigo", name="uq_reglas_descuento_academia_codigo"),
    )
    with op.batch_alter_table("reglas_descuento", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reglas_descuento_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_reglas_descuento_academia_tipo", ["academia_id", "tipo"], unique=False)

    op.create_table(
        "tarifas_plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tarifario_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("frecuencia_id", sa.Integer(), nullable=False),
        sa.Column("valor_base", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("academia_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("valor_base >= 0", name="ck_tarifas_plan_valor_base_no_negativo"),
        sa.ForeignKeyConstraint(["academia_id"], ["academias.id"]),
        sa.ForeignKeyConstraint(["frecuencia_id"], ["frecuencias_entrenamiento.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["planes_financieros.id"]),
        sa.ForeignKeyConstraint(["tarifario_id"], ["tarifarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "academia_id",
            "tarifario_id",
            "plan_id",
            "frecuencia_id",
            name="uq_tarifas_plan_academia_tarifario_plan_frecuencia",
        ),
    )
    with op.batch_alter_table("tarifas_plan", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tarifas_plan_academia_id"), ["academia_id"], unique=False)
        batch_op.create_index("ix_tarifas_plan_academia_activo", ["academia_id", "activo"], unique=False)


def downgrade():
    with op.batch_alter_table("tarifas_plan", schema=None) as batch_op:
        batch_op.drop_index("ix_tarifas_plan_academia_activo")
        batch_op.drop_index(batch_op.f("ix_tarifas_plan_academia_id"))
    op.drop_table("tarifas_plan")

    with op.batch_alter_table("reglas_descuento", schema=None) as batch_op:
        batch_op.drop_index("ix_reglas_descuento_academia_tipo")
        batch_op.drop_index(batch_op.f("ix_reglas_descuento_academia_id"))
    op.drop_table("reglas_descuento")

    with op.batch_alter_table("tarifarios", schema=None) as batch_op:
        batch_op.drop_index("ix_tarifarios_academia_estado")
        batch_op.drop_index(batch_op.f("ix_tarifarios_academia_id"))
    op.drop_table("tarifarios")

    with op.batch_alter_table("frecuencias_entrenamiento", schema=None) as batch_op:
        batch_op.drop_index("ix_frecuencias_entrenamiento_academia_activo")
        batch_op.drop_index(batch_op.f("ix_frecuencias_entrenamiento_academia_id"))
    op.drop_table("frecuencias_entrenamiento")

    with op.batch_alter_table("planes_financieros", schema=None) as batch_op:
        batch_op.drop_index("ix_planes_financieros_academia_activo")
        batch_op.drop_index(batch_op.f("ix_planes_financieros_academia_id"))
    op.drop_table("planes_financieros")
