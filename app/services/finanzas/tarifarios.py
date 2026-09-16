"""Administración de catálogos de precios, sin alterar snapshots financieros."""
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from app.extensions import db
from app.models.academia import Academia
from app.models.finanzas import (
    AlumnoPlanFinanciero, FrecuenciaEntrenamiento, PlanFinanciero, TarifaPlan, Tarifario,
)
from app.services.finanzas.familias import FinanzasError


ESTADOS_TARIFARIO = ("BORRADOR", "VIGENTE", "CERRADO")


def validar_referencias_activas(*, academia_id, plan_id, frecuencia_id):
    for modelo, entity_id, etiqueta in (
        (PlanFinanciero, plan_id, "Plan"),
        (FrecuenciaEntrenamiento, frecuencia_id, "Frecuencia"),
    ):
        item = modelo.query.filter_by(id=entity_id, academia_id=academia_id).first()
        if item is None or not item.activo:
            raise FinanzasError(f"{etiqueta} no disponible: debe estar activo y pertenecer a la academia")


def validar_tarifario_utilizable(tarifario, *, academia_id, fecha):
    if tarifario.academia_id != academia_id:
        raise FinanzasError("Tarifario no pertenece a la academia indicada")
    if tarifario.estado != "VIGENTE":
        raise FinanzasError("El tarifario debe estar VIGENTE para utilizar sus tarifas")
    if fecha < tarifario.fecha_inicio_vigencia or (
        tarifario.fecha_fin_vigencia is not None and fecha > tarifario.fecha_fin_vigencia
    ):
        raise FinanzasError("El tarifario esta fuera de vigencia para la fecha indicada")


def tarifas_editables(tarifario):
    # Un borrador futuro se puede preparar, pero nunca seleccionar para asignar.
    return tarifario.estado in ("BORRADOR", "VIGENTE") and (
        tarifario.fecha_fin_vigencia is None or tarifario.fecha_fin_vigencia >= date.today()
    )


def _fecha(valor, etiqueta, *, opcional=False):
    if not valor and opcional:
        return None
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        raise FinanzasError(f"{etiqueta} no valida")


def guardar_tarifario(*, academia_id, usuario_id, datos, tarifario=None):
    # Serializa las escrituras del catálogo por academia en motores con FOR UPDATE.
    academia = Academia.query.filter_by(id=academia_id).with_for_update().first()
    if academia is None:
        raise FinanzasError("Academia no disponible")
    if tarifario is not None:
        if tarifario.academia_id != academia_id:
            raise FinanzasError("Tarifario no pertenece a la academia indicada")
        if tarifario.estado == "CERRADO":
            raise FinanzasError("Un tarifario CERRADO es de solo consulta")
    nombre = (datos.get("nombre") or "").strip()
    if not nombre or len(nombre) > 120:
        raise FinanzasError("El nombre es obligatorio y admite hasta 120 caracteres")
    moneda = (datos.get("moneda") or "USD").strip().upper()
    if len(moneda) != 3:
        raise FinanzasError("La moneda debe usar codigo ISO de 3 letras")
    inicio = _fecha(datos.get("fecha_inicio_vigencia"), "Fecha de inicio")
    fin = _fecha(datos.get("fecha_fin_vigencia"), "Fecha de fin", opcional=True)
    if fin is not None and fin < inicio:
        raise FinanzasError("La fecha de fin no puede ser anterior al inicio")
    estado = datos.get("estado")
    if estado not in ESTADOS_TARIFARIO:
        raise FinanzasError("Estado de tarifario no valido")
    if tarifario is not None and tarifario.estado == "VIGENTE" and estado == "BORRADOR":
        raise FinanzasError("Un tarifario VIGENTE solo puede mantenerse vigente o cerrarse")
    if estado == "VIGENTE":
        if fin is not None and fin < date.today():
            raise FinanzasError("No se puede publicar un tarifario cuya vigencia ya termino")
        solapados = Tarifario.query.filter(
            Tarifario.academia_id == academia_id,
            Tarifario.estado == "VIGENTE",
            Tarifario.fecha_inicio_vigencia <= (fin or date.max),
            or_(Tarifario.fecha_fin_vigencia.is_(None), Tarifario.fecha_fin_vigencia >= inicio),
        )
        if tarifario is not None:
            solapados = solapados.filter(Tarifario.id != tarifario.id)
        if solapados.first() is not None:
            raise FinanzasError("La vigencia se solapa con otro tarifario VIGENTE de la academia")
    if tarifario is not None:
        usado = AlumnoPlanFinanciero.query.filter_by(
            academia_id=academia_id, tarifario_id=tarifario.id,
        ).first()
        if usado and (moneda != tarifario.moneda or inicio != tarifario.fecha_inicio_vigencia):
            raise FinanzasError("Un tarifario utilizado conserva su moneda y fecha de inicio; cree otro tarifario")
    else:
        tarifario = Tarifario(academia_id=academia_id, created_by_id=usuario_id)
    tarifario.nombre = nombre
    tarifario.descripcion = (datos.get("descripcion") or "").strip() or None
    tarifario.moneda = moneda
    tarifario.fecha_inicio_vigencia = inicio
    tarifario.fecha_fin_vigencia = fin
    tarifario.estado = estado
    db.session.add(tarifario)
    db.session.flush()
    return tarifario


def guardar_tarifa(*, academia_id, tarifario, datos, tarifa=None):
    if tarifario.academia_id != academia_id:
        raise FinanzasError("Tarifario no pertenece a la academia indicada")
    if tarifa is not None and (tarifa.academia_id != academia_id or tarifa.tarifario_id != tarifario.id):
        raise FinanzasError("Tarifa no pertenece al tarifario indicado")
    if not tarifas_editables(tarifario):
        raise FinanzasError("No se pueden modificar tarifas de un tarifario cerrado o vencido")
    try:
        plan_id = int(datos.get("plan_id", ""))
        frecuencia_id = int(datos.get("frecuencia_id", ""))
    except (ValueError, TypeError):
        raise FinanzasError("Seleccione un plan y una frecuencia validos")
    validar_referencias_activas(academia_id=academia_id, plan_id=plan_id, frecuencia_id=frecuencia_id)
    try:
        valor = Decimal(datos.get("valor_base", ""))
    except (InvalidOperation, TypeError, ValueError):
        raise FinanzasError("El importe debe ser un numero valido")
    if not valor.is_finite() or valor < 0 or valor > Decimal("99999999.99"):
        raise FinanzasError("El importe debe estar entre 0 y 99999999.99")
    if valor.as_tuple().exponent < -2:
        raise FinanzasError("El importe admite como maximo 2 decimales")
    existente = TarifaPlan.query.filter_by(
        academia_id=academia_id, tarifario_id=tarifario.id, plan_id=plan_id, frecuencia_id=frecuencia_id,
    ).first()
    if existente is not None and (tarifa is None or existente.id != tarifa.id):
        raise FinanzasError("Ya existe una tarifa para ese plan y frecuencia; edite o reactive la existente")
    if tarifa is not None:
        usado = AlumnoPlanFinanciero.query.filter_by(academia_id=academia_id, tarifa_plan_id=tarifa.id).first()
        if usado and (plan_id != tarifa.plan_id or frecuencia_id != tarifa.frecuencia_id):
            raise FinanzasError("Una tarifa utilizada conserva su plan y frecuencia")
    else:
        tarifa = TarifaPlan(academia_id=academia_id, tarifario_id=tarifario.id)
    tarifa.plan_id = plan_id
    tarifa.frecuencia_id = frecuencia_id
    tarifa.valor_base = valor
    tarifa.observaciones = (datos.get("observaciones") or "").strip() or None
    tarifa.activo = datos.get("activo") == "1"
    db.session.add(tarifa)
    db.session.flush()
    return tarifa


def alternar_tarifa(*, academia_id, tarifario, tarifa):
    if tarifario.academia_id != academia_id or tarifa.academia_id != academia_id or tarifa.tarifario_id != tarifario.id:
        raise FinanzasError("Tarifa no pertenece al tarifario indicado")
    if not tarifas_editables(tarifario):
        raise FinanzasError("No se pueden modificar tarifas de un tarifario cerrado o vencido")
    if not tarifa.activo:
        validar_referencias_activas(academia_id=academia_id, plan_id=tarifa.plan_id, frecuencia_id=tarifa.frecuencia_id)
    tarifa.activo = not tarifa.activo
    db.session.flush()
    return tarifa
