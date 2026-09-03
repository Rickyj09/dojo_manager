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
    decimales_redondeo = db.Column(db.Integer, nullable=False, default=2)
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
        db.CheckConstraint("decimales_redondeo >= 0 AND decimales_redondeo <= 4", name="ck_reglas_descuento_decimales_rango"),
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

    @validates("decimales_redondeo")
    def _validar_decimales_redondeo(self, key, value):
        value = int(value)
        if value < 0 or value > 4:
            raise ValueError("Los decimales de redondeo deben estar entre 0 y 4")
        return value


class ConfiguracionFinanciera(TenantMixin, db.Model):
    __tablename__ = "configuraciones_financieras"

    id = db.Column(db.Integer, primary_key=True)
    dia_vencimiento_pension = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("academia_id", name="uq_configuraciones_financieras_academia"),
        db.CheckConstraint(
            "dia_vencimiento_pension IS NULL OR (dia_vencimiento_pension >= 1 AND dia_vencimiento_pension <= 31)",
            name="ck_configuraciones_financieras_dia_vencimiento_pension",
        ),
    )

    @validates("dia_vencimiento_pension")
    def _validar_dia_vencimiento_pension(self, key, value):
        if value is None or value == "":
            return None
        value = int(value)
        if value < 1 or value > 31:
            raise ValueError("El dia de vencimiento de pension debe estar entre 1 y 31")
        return value


class GrupoFamiliar(TenantMixin, db.Model):
    __tablename__ = "grupos_familiares"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    observaciones = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    alumnos = db.relationship("AlumnoGrupoFamiliar", back_populates="grupo_familiar")

    __table_args__ = (
        db.UniqueConstraint("academia_id", "codigo", name="uq_grupos_familiares_academia_codigo"),
        db.Index("ix_grupos_familiares_academia_activo", "academia_id", "activo"),
    )

    @validates("codigo")
    def _validar_codigo(self, key, value):
        return normalizar_codigo(value)


class AlumnoGrupoFamiliar(TenantMixin, db.Model):
    __tablename__ = "alumnos_grupos_familiares"

    id = db.Column(db.Integer, primary_key=True)
    grupo_familiar_id = db.Column(db.Integer, db.ForeignKey("grupos_familiares.id"), nullable=False)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    grupo_familiar = db.relationship("GrupoFamiliar", back_populates="alumnos")
    alumno = db.relationship("Alumno")

    __table_args__ = (
        db.UniqueConstraint(
            "academia_id",
            "grupo_familiar_id",
            "alumno_id",
            "fecha_inicio",
            name="uq_alumnos_grupos_familiares_membresia",
        ),
        db.Index("ix_alumnos_grupos_familiares_alumno_activo", "academia_id", "alumno_id", "activo"),
        db.Index("ix_alumnos_grupos_familiares_grupo_activo", "academia_id", "grupo_familiar_id", "activo"),
        db.CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_alumnos_grupos_familiares_fechas"),
    )


class AlumnoPlanFinanciero(TenantMixin, db.Model):
    __tablename__ = "alumnos_planes_financieros"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes_financieros.id"), nullable=False)
    frecuencia_id = db.Column(db.Integer, db.ForeignKey("frecuencias_entrenamiento.id"), nullable=False)
    tarifario_id = db.Column(db.Integer, db.ForeignKey("tarifarios.id"), nullable=False)
    tarifa_plan_id = db.Column(db.Integer, db.ForeignKey("tarifas_plan.id"), nullable=False)
    grupo_familiar_id = db.Column(db.Integer, db.ForeignKey("grupos_familiares.id"), nullable=True)
    regla_descuento_id = db.Column(db.Integer, db.ForeignKey("reglas_descuento.id"), nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=True)
    tarifa_base_snapshot = db.Column(db.Numeric(10, 2), nullable=False)
    descuento_porcentaje_snapshot = db.Column(db.Numeric(5, 2), nullable=True)
    descuento_valor_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    valor_final_snapshot = db.Column(db.Numeric(10, 2), nullable=False)
    moneda_snapshot = db.Column(db.String(3), nullable=False)
    estado = db.Column(
        db.Enum("ACTIVO", "FINALIZADO", "CANCELADO", name="fin_alumno_plan_estado", native_enum=False),
        nullable=False,
        default="ACTIVO",
    )
    motivo = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    alumno = db.relationship("Alumno")
    plan = db.relationship("PlanFinanciero")
    frecuencia = db.relationship("FrecuenciaEntrenamiento")
    tarifario = db.relationship("Tarifario")
    tarifa_plan = db.relationship("TarifaPlan")
    grupo_familiar = db.relationship("GrupoFamiliar")
    regla_descuento = db.relationship("ReglaDescuento")
    created_by = db.relationship("User")

    __table_args__ = (
        db.Index("ix_alumnos_planes_financieros_alumno_estado", "academia_id", "alumno_id", "estado"),
        db.Index("ix_alumnos_planes_financieros_fechas", "academia_id", "fecha_inicio", "fecha_fin"),
        db.CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_alumnos_planes_financieros_fechas"),
        db.CheckConstraint("tarifa_base_snapshot >= 0", name="ck_alumnos_planes_financieros_tarifa_no_negativa"),
        db.CheckConstraint("descuento_valor_snapshot >= 0", name="ck_alumnos_planes_financieros_descuento_no_negativo"),
        db.CheckConstraint("valor_final_snapshot >= 0", name="ck_alumnos_planes_financieros_final_no_negativo"),
    )


class ObligacionFinanciera(TenantMixin, db.Model):
    __tablename__ = "obligaciones_financieras"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)
    alumno_plan_financiero_id = db.Column(db.Integer, db.ForeignKey("alumnos_planes_financieros.id"), nullable=True)
    periodo = db.Column(db.String(7), nullable=False)
    tipo_obligacion = db.Column(
        db.Enum(
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
    )
    concepto = db.Column(db.String(160), nullable=False)
    origen = db.Column(db.String(80), nullable=True)
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    tarifa_base_snapshot = db.Column(db.Numeric(10, 2), nullable=False)
    porcentaje_descuento_snapshot = db.Column(db.Numeric(5, 2), nullable=True)
    valor_descuento_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    valor_final_snapshot = db.Column(db.Numeric(10, 2), nullable=False)
    moneda_snapshot = db.Column(db.String(3), nullable=False)
    estado = db.Column(
        db.Enum("PENDIENTE", "ANULADA", name="fin_obligacion_estado", native_enum=False),
        nullable=False,
        default="PENDIENTE",
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    alumno = db.relationship("Alumno")
    alumno_plan_financiero = db.relationship("AlumnoPlanFinanciero")

    __table_args__ = (
        db.UniqueConstraint(
            "academia_id",
            "alumno_id",
            "periodo",
            "tipo_obligacion",
            name="uq_obligaciones_financieras_academia_alumno_periodo_tipo",
        ),
        db.Index("ix_obligaciones_financieras_periodo_estado", "academia_id", "periodo", "estado"),
        db.Index("ix_obligaciones_financieras_alumno_periodo", "academia_id", "alumno_id", "periodo"),
        db.CheckConstraint("tarifa_base_snapshot >= 0", name="ck_obligaciones_financieras_tarifa_no_negativa"),
        db.CheckConstraint("valor_descuento_snapshot >= 0", name="ck_obligaciones_financieras_descuento_no_negativo"),
        db.CheckConstraint("valor_final_snapshot >= 0", name="ck_obligaciones_financieras_final_no_negativo"),
    )


class PagoFinanciero(TenantMixin, db.Model):
    __tablename__ = "pagos_financieros"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)
    fecha_pago = db.Column(db.Date, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    moneda = db.Column(db.String(3), nullable=False, default="USD")
    medio_pago = db.Column(
        db.Enum("EFECTIVO", "TRANSFERENCIA", "DEPOSITO", "TARJETA", "OTRO", name="fin_pago_medio", native_enum=False),
        nullable=False,
    )
    referencia = db.Column(db.String(120), nullable=True)
    observacion = db.Column(db.Text, nullable=True)
    estado = db.Column(
        db.Enum("REGISTRADO", "ANULADO", name="fin_pago_estado", native_enum=False),
        nullable=False,
        default="REGISTRADO",
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    alumno = db.relationship("Alumno")
    aplicaciones = db.relationship("PagoAplicacion", back_populates="pago")
    comprobantes = db.relationship("PagoComprobante", back_populates="pago")

    __table_args__ = (
        db.Index("ix_pagos_financieros_academia_fecha", "academia_id", "fecha_pago"),
        db.Index("ix_pagos_financieros_alumno_estado", "academia_id", "alumno_id", "estado"),
        db.CheckConstraint("valor > 0", name="ck_pagos_financieros_valor_positivo"),
    )

    @validates("valor")
    def _validar_valor(self, key, value):
        value = Decimal(value)
        if value <= 0:
            raise ValueError("El valor del pago debe ser mayor a cero")
        return value

    @validates("moneda")
    def _validar_moneda(self, key, value):
        value = (value or "USD").strip().upper()
        if len(value) != 3:
            raise ValueError("La moneda debe usar codigo ISO de 3 letras")
        return value


class PagoAplicacion(TenantMixin, db.Model):
    __tablename__ = "pagos_aplicaciones"

    id = db.Column(db.Integer, primary_key=True)
    pago_id = db.Column(db.Integer, db.ForeignKey("pagos_financieros.id"), nullable=False)
    obligacion_financiera_id = db.Column(db.Integer, db.ForeignKey("obligaciones_financieras.id"), nullable=False)
    valor_aplicado = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    pago = db.relationship("PagoFinanciero", back_populates="aplicaciones")
    obligacion_financiera = db.relationship("ObligacionFinanciera")

    __table_args__ = (
        db.Index("ix_pagos_aplicaciones_pago", "academia_id", "pago_id"),
        db.Index("ix_pagos_aplicaciones_obligacion", "academia_id", "obligacion_financiera_id"),
        db.CheckConstraint("valor_aplicado > 0", name="ck_pagos_aplicaciones_valor_positivo"),
    )

    @validates("valor_aplicado")
    def _validar_valor_aplicado(self, key, value):
        value = Decimal(value)
        if value <= 0:
            raise ValueError("El valor aplicado debe ser mayor a cero")
        return value


class PagoComprobante(TenantMixin, db.Model):
    __tablename__ = "pagos_comprobantes"

    id = db.Column(db.Integer, primary_key=True)
    pago_financiero_id = db.Column(db.Integer, db.ForeignKey("pagos_financieros.id"), nullable=False)
    nombre_original = db.Column(db.String(255), nullable=False)
    nombre_interno = db.Column(db.String(80), nullable=False)
    ruta_relativa = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    extension = db.Column(db.String(10), nullable=False)
    tamano_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    observacion = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    pago = db.relationship("PagoFinanciero", back_populates="comprobantes")
    uploaded_by = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("pago_financiero_id", "sha256", name="uq_pagos_comprobantes_pago_sha256"),
        db.Index("ix_pagos_comprobantes_pago", "academia_id", "pago_financiero_id"),
        db.CheckConstraint("tamano_bytes > 0", name="ck_pagos_comprobantes_tamano_positivo"),
    )


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


def _validar_pago_comprobante_tenant(mapper, connection, target):
    row = connection.execute(
        text("SELECT academia_id FROM pagos_financieros WHERE id = :pago_id"),
        {"pago_id": target.pago_financiero_id},
    ).fetchone()
    if row is None:
        raise ValueError("Pago financiero inexistente")
    if row[0] != target.academia_id:
        raise ValueError("PagoComprobante no puede relacionar datos de otra academia")


event.listen(PagoComprobante, "before_insert", _validar_pago_comprobante_tenant)
event.listen(PagoComprobante, "before_update", _validar_pago_comprobante_tenant)
