from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import ObligacionFinanciera, PagoAplicacion, PagoFinanciero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.tarifas import redondear_dinero


MEDIOS_PAGO_FINANCIERO = ("EFECTIVO", "TRANSFERENCIA", "DEPOSITO", "TARJETA", "OTRO")


@dataclass(frozen=True)
class AplicacionPagoInput:
    obligacion_financiera_id: int
    valor_aplicado: Decimal


def _decimal(value) -> Decimal:
    try:
        return redondear_dinero(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        raise FinanzasError("El valor debe ser un numero valido")


def _validar_precision_monetaria(value, nombre: str) -> Decimal:
    valor = _decimal(value)
    try:
        if Decimal(str(value)).as_tuple().exponent < -2:
            raise FinanzasError(f"{nombre} no puede tener mas de 2 decimales")
    except InvalidOperation:
        raise FinanzasError(f"{nombre} debe ser un numero valido")
    return valor


def _normalizar_medio_pago(medio_pago: str) -> str:
    medio = (medio_pago or "").strip().upper()
    if medio not in MEDIOS_PAGO_FINANCIERO:
        raise FinanzasError("Medio de pago invalido")
    return medio


def _normalizar_moneda(moneda: str) -> str:
    moneda = (moneda or "USD").strip().upper()
    if len(moneda) != 3:
        raise FinanzasError("La moneda debe usar codigo ISO de 3 letras")
    return moneda


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
    valor = _validar_precision_monetaria(valor, "El valor del pago")
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
        moneda=_normalizar_moneda(moneda),
        medio_pago=_normalizar_medio_pago(medio_pago),
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
    valor_aplicado = _validar_precision_monetaria(valor_aplicado, "El valor aplicado")
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


def aplicar_pago_a_obligaciones(
    *,
    academia_id: int,
    pago_id: int,
    aplicaciones: list[dict] | list[AplicacionPagoInput],
) -> list[PagoAplicacion]:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    if pago.estado == "ANULADO":
        raise FinanzasError("No se puede aplicar un pago anulado")

    normalizadas = []
    for item in aplicaciones:
        obligacion_id = item.obligacion_financiera_id if isinstance(item, AplicacionPagoInput) else item.get("obligacion_financiera_id")
        valor = item.valor_aplicado if isinstance(item, AplicacionPagoInput) else item.get("valor_aplicado")
        valor = _validar_precision_monetaria(valor, "El valor aplicado")
        if valor <= 0:
            raise FinanzasError("El valor aplicado debe ser mayor a cero")
        try:
            obligacion_id = int(obligacion_id)
        except (TypeError, ValueError):
            raise FinanzasError("Obligacion invalida")
        normalizadas.append(AplicacionPagoInput(obligacion_financiera_id=obligacion_id, valor_aplicado=valor))

    if not normalizadas:
        raise FinanzasError("Debe indicar al menos una aplicacion")

    total_a_aplicar = redondear_dinero(sum((item.valor_aplicado for item in normalizadas), Decimal("0.00")))
    saldo_pago = calcular_saldo_pago(academia_id=academia_id, pago_id=pago.id)
    if total_a_aplicar > saldo_pago:
        raise FinanzasError("El valor aplicado excede el saldo disponible del pago")

    saldos_por_obligacion = {}
    for item in normalizadas:
        obligacion = ObligacionFinanciera.query.filter_by(
            id=item.obligacion_financiera_id,
            academia_id=academia_id,
        ).first()
        if obligacion is None:
            raise FinanzasError("Obligacion no pertenece a la academia indicada")
        if obligacion.estado == "ANULADA":
            raise FinanzasError("No se puede aplicar a una obligacion anulada")
        if obligacion.alumno_id != pago.alumno_id:
            raise FinanzasError("El pago no pertenece al alumno de la obligacion")
        saldos_por_obligacion[obligacion.id] = calcular_saldo_obligacion(
            academia_id=academia_id,
            obligacion_financiera_id=obligacion.id,
        )

    totales_por_obligacion = {}
    for item in normalizadas:
        totales_por_obligacion[item.obligacion_financiera_id] = (
            totales_por_obligacion.get(item.obligacion_financiera_id, Decimal("0.00")) + item.valor_aplicado
        )
    for obligacion_id, total in totales_por_obligacion.items():
        if redondear_dinero(total) > saldos_por_obligacion[obligacion_id]:
            raise FinanzasError("El valor aplicado excede el saldo de la obligacion")

    creadas = []
    for item in normalizadas:
        aplicacion = PagoAplicacion(
            academia_id=academia_id,
            pago_id=pago.id,
            obligacion_financiera_id=item.obligacion_financiera_id,
            valor_aplicado=item.valor_aplicado,
        )
        db.session.add(aplicacion)
        creadas.append(aplicacion)
    db.session.flush()
    return creadas


def anular_pago(*, academia_id: int, pago_id: int) -> PagoFinanciero:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    if calcular_total_aplicado_pago(academia_id=academia_id, pago_id=pago.id) > 0:
        raise FinanzasError("No se puede anular un pago con aplicaciones")
    pago.estado = "ANULADO"
    db.session.flush()
    return pago
