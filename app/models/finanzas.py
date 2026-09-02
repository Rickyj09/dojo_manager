import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import event, text
from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import TenantMixin


def normalizar_codigo(value: str) -> str:
    if value is None:
        raise ValueError("El codigo es obligatorio")
    value = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper())
    value = value.strip("_")
    if not value:
        raise ValueError("El codigo es obligatorio")
    return value


class PlanFinanciero(TenantMixin, db.Model):
    __tablename__ = "planes_financieros"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    objetivo = db.Column(db.String(255), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("academia_id", "codigo", name="uq_planes_financieros_academia_codigo"),
        db.Index("ix_planes_financieros_academia_activo", "academia_id", "activo"),
    )

    @validates("codigo")
    def _validar_codigo(self, key, value):
        return normalizar_codigo(value)


class FrecuenciaEntrenamiento(TenantMixin, db.Model):
    __tablename__ = "frecuencias_entrenamiento"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    dias_semana = db.Column(db.Integer, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint("academia_id", "codigo", name="uq_frecuencias_entrenamiento_academia_codigo"),
        db.Index("ix_frecuencias_entrenamiento_academia_activo", "academia_id", "activo"),
        db.CheckConstraint("dias_semana >= 0", name="ck_frecuencias_entrenamiento_dias_no_negativo"),
    )

    @validates("codigo")
    def _validar_codigo(self, key, value):
        return normalizar_codigo(value)


class Tarifario(TenantMixin, db.Model):
    __tablename__ = "tarifarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    fecha_inicio_vigencia = db.Column(db.Date, nullable=False)
    fecha_fin_vigencia = db.Column(db.Date, nullable=True)
    estado = db.Column(
        db.Enum("BORRADOR", "VIGENTE", "CERRADO", name="fin_tarifario_estado", native_enum=False),
        nullable=False,
        default="BORRADOR",
    )
    moneda = db.Column(db.String(3), nullable=False, default="USD")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_by = db.relationship("User")
    tarifas = db.relationship("TarifaPlan", back_populates="tarifario")

    __table_args__ = (
        db.Index("ix_tarifarios_academia_estado", "academia_id", "estado"),
        db.CheckConstraint(
            "fecha_fin_vigencia IS NULL OR fecha_fin_vigencia >= fecha_inicio_vigencia",
            name="ck_tarifarios_fechas_coherentes",
        ),
    )

    @validates("moneda")
    def _validar_moneda(self, key, value):
        value = (value or "USD").strip().upper()
        if len(value) != 3:
            raise ValueError("La moneda debe usar codigo ISO de 3 letras")
        return value


class ReglaDescuento(TenantMixin, db.Model):
    __tablename__ = "reglas_descuento"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(
        db.Enum("HERMANOS", "BECA", "CONVENIO", "PROMOCION", "ESPECIAL", "OTRO", name="fin_regla_descuento_tipo", native_enum=False),
        nullable=False,
    )
    porcentaje = db.Column(db.Numeric(5, 2), nullable=True)
    valor_fijo = db.Column(db.Numeric(10, 2), nullable=True)
    cantidad_minima = db.Column(db.Integer, nullable=True)
    requiere_autorizacion = db.Column(db.Boolean, nullable=False, default=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    vigencia_desde = db.Column(db.Date, nullable=True)
    vigencia_hasta = db.Column(db.Date, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("academia_id", "codigo", name="uq_reglas_descuento_academia_codigo"),
        db.Index("ix_reglas_descuento_academia_tipo", "academia_id", "tipo"),
        db.CheckConstraint("porcentaje IS NULL OR (porcentaje >= 0 AND porcentaje <= 100)", name="ck_reglas_descuento_porcentaje_rango"),
        db.CheckConstraint("valor_fijo IS NULL OR valor_fijo >= 0", name="ck_reglas_descuento_valor_fijo_no_negativo"),
        db.CheckConstraint("cantidad_minima IS NULL OR cantidad_minima >= 0", name="ck_reglas_descuento_cantidad_no_negativa"),
        db.CheckConstraint("porcentaje IS NULL OR valor_fijo IS NULL", name="ck_reglas_descuento_un_modo"),
        db.CheckConstraint("vigencia_hasta IS NULL OR vigencia_desde IS NULL OR vigencia_hasta >= vigencia_desde", name="ck_reglas_descuento_fechas_coherentes"),
    )

    @validates("codigo")
    def _validar_codigo(self, key, value):
        return normalizar_codigo(value)

    @validates("porcentaje")
    def _validar_porcentaje(self, key, value):
        if value is None:
            return None
        value = Decimal(value)
        if value < 0 or value > 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100")
        return value

    @validates("valor_fijo")
    def _validar_valor_fijo(self, key, value):
        if value is None:
            return None
        value = Decimal(value)
        if value < 0:
            raise ValueError("El valor fijo no puede ser negativo")
        return value


class TarifaPlan(TenantMixin, db.Model):
    __tablename__ = "tarifas_plan"

    id = db.Column(db.Integer, primary_key=True)
    tarifario_id = db.Column(db.Integer, db.ForeignKey("tarifarios.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes_financieros.id"), nullable=False)
    frecuencia_id = db.Column(db.Integer, db.ForeignKey("frecuencias_entrenamiento.id"), nullable=False)
    valor_base = db.Column(db.Numeric(10, 2), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    observaciones = db.Column(db.Text, nullable=True)

    tarifario = db.relationship("Tarifario", back_populates="tarifas")
    plan = db.relationship("PlanFinanciero")
    frecuencia = db.relationship("FrecuenciaEntrenamiento")

    __table_args__ = (
        db.UniqueConstraint(
            "academia_id",
            "tarifario_id",
            "plan_id",
            "frecuencia_id",
            name="uq_tarifas_plan_academia_tarifario_plan_frecuencia",
        ),
        db.Index("ix_tarifas_plan_academia_activo", "academia_id", "activo"),
        db.CheckConstraint("valor_base >= 0", name="ck_tarifas_plan_valor_base_no_negativo"),
    )

    @validates("valor_base")
    def _validar_valor_base(self, key, value):
        value = Decimal(value)
        if value < 0:
            raise ValueError("El valor base no puede ser negativo")
        return value


def _validar_tarifa_plan_tenant(mapper, connection, target):
    tablas = (
        ("tarifarios", target.tarifario_id),
        ("planes_financieros", target.plan_id),
        ("frecuencias_entrenamiento", target.frecuencia_id),
    )

    for table_name, entity_id in tablas:
        row = connection.execute(
            text(f"SELECT academia_id FROM {table_name} WHERE id = :entity_id"),
            {"entity_id": entity_id},
        ).fetchone()
        if row is None:
            raise ValueError(f"Referencia financiera inexistente: {table_name}")
        if row[0] != target.academia_id:
            raise ValueError("TarifaPlan no puede relacionar datos de otra academia")


event.listen(TarifaPlan, "before_insert", _validar_tarifa_plan_tenant)
event.listen(TarifaPlan, "before_update", _validar_tarifa_plan_tenant)
