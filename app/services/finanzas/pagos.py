from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import ObligacionFinanciera, PagoAplicacion, PagoFinanciero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.tarifas import redondear_dinero


def _decimal(value) -> Decimal:
    return redondear_dinero(Decimal(value))


def _sumar_aplicaciones(query) -> Decimal:
    total = query.scalar()
    return _decimal(total or Decimal("0.00"))


def registrar_pago(
    *,
    academia_id: int,
    alumno_id: int,
    fecha_pago: date,
    valor,
    medio_pago: str,
    moneda: str = "USD",
    referencia: str | None = None,
    observacion: str | None = None,
) -> PagoFinanciero:
    valor = _decimal(valor)
    if valor <= 0:
        raise FinanzasError("El valor del pago debe ser mayor a cero")

    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        raise FinanzasError("Alumno no pertenece a la academia indicada")

    pago = PagoFinanciero(
        academia_id=academia_id,
        alumno_id=alumno.id,
        fecha_pago=fecha_pago,
        valor=valor,
        moneda=moneda,
        medio_pago=(medio_pago or "").strip().upper(),
        referencia=referencia,
        observacion=observacion,
        estado="REGISTRADO",
    )
    db.session.add(pago)
    db.session.flush()
    return pago


def calcular_total_aplicado_pago(*, academia_id: int, pago_id: int) -> Decimal:
    return _sumar_aplicaciones(
        db.session.query(func.coalesce(func.sum(PagoAplicacion.valor_aplicado), 0)).filter(
            PagoAplicacion.academia_id == academia_id,
            PagoAplicacion.pago_id == pago_id,
        )
    )


def calcular_saldo_pago(*, academia_id: int, pago_id: int) -> Decimal:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    return _decimal(Decimal(pago.valor) - calcular_total_aplicado_pago(academia_id=academia_id, pago_id=pago.id))


def calcular_total_pagado_obligacion(*, academia_id: int, obligacion_financiera_id: int) -> Decimal:
    return _sumar_aplicaciones(
        db.session.query(func.coalesce(func.sum(PagoAplicacion.valor_aplicado), 0))
        .join(PagoFinanciero, PagoFinanciero.id == PagoAplicacion.pago_id)
        .filter(
            PagoAplicacion.academia_id == academia_id,
            PagoAplicacion.obligacion_financiera_id == obligacion_financiera_id,
            PagoFinanciero.academia_id == academia_id,
            PagoFinanciero.estado == "REGISTRADO",
        )
    )


def calcular_saldo_obligacion(*, academia_id: int, obligacion_financiera_id: int) -> Decimal:
    obligacion = ObligacionFinanciera.query.filter_by(id=obligacion_financiera_id, academia_id=academia_id).first()
    if obligacion is None:
        raise FinanzasError("Obligacion no pertenece a la academia indicada")
    total = Decimal(obligacion.valor_final_snapshot)
    aplicado = calcular_total_pagado_obligacion(
        academia_id=academia_id,
        obligacion_financiera_id=obligacion.id,
    )
    return _decimal(total - aplicado)


def obtener_estado_pago_obligacion(*, academia_id: int, obligacion_financiera_id: int) -> str:
    obligacion = ObligacionFinanciera.query.filter_by(id=obligacion_financiera_id, academia_id=academia_id).first()
    if obligacion is None:
        raise FinanzasError("Obligacion no pertenece a la academia indicada")
    if obligacion.estado == "ANULADA":
        return "ANULADA"

    total = Decimal(obligacion.valor_final_snapshot)
    aplicado = calcular_total_pagado_obligacion(
        academia_id=academia_id,
        obligacion_financiera_id=obligacion.id,
    )
    if aplicado == 0:
        return "PENDIENTE"
    if aplicado < total:
        return "PARCIAL"
    return "PAGADA"


def aplicar_pago(*, academia_id: int, pago_id: int, obligacion_financiera_id: int, valor_aplicado) -> PagoAplicacion:
    valor_aplicado = _decimal(valor_aplicado)
    if valor_aplicado <= 0:
        raise FinanzasError("El valor aplicado debe ser mayor a cero")

    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    if pago.estado == "ANULADO":
        raise FinanzasError("No se puede aplicar un pago anulado")

    obligacion = ObligacionFinanciera.query.filter_by(id=obligacion_financiera_id, academia_id=academia_id).first()
    if obligacion is None:
        raise FinanzasError("Obligacion no pertenece a la academia indicada")
    if obligacion.estado == "ANULADA":
        raise FinanzasError("No se puede aplicar a una obligacion anulada")
    if obligacion.alumno_id != pago.alumno_id:
        raise FinanzasError("El pago no pertenece al alumno de la obligacion")

    saldo_pago = calcular_saldo_pago(academia_id=academia_id, pago_id=pago.id)
    if valor_aplicado > saldo_pago:
        raise FinanzasError("El valor aplicado excede el saldo disponible del pago")

    saldo_obligacion = calcular_saldo_obligacion(
        academia_id=academia_id,
        obligacion_financiera_id=obligacion.id,
    )
    if valor_aplicado > saldo_obligacion:
        raise FinanzasError("El valor aplicado excede el saldo de la obligacion")

    aplicacion = PagoAplicacion(
        academia_id=academia_id,
        pago_id=pago.id,
        obligacion_financiera_id=obligacion.id,
        valor_aplicado=valor_aplicado,
    )
    db.session.add(aplicacion)
    db.session.flush()
    return aplicacion


def anular_pago(*, academia_id: int, pago_id: int) -> PagoFinanciero:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    if calcular_total_aplicado_pago(academia_id=academia_id, pago_id=pago.id) > 0:
        raise FinanzasError("No se puede anular un pago con aplicaciones")
    pago.estado = "ANULADO"
    db.session.flush()
    return pago
