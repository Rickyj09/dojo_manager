from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import PagoAplicacion, PagoFinanciero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.pagos import MEDIOS_PAGO_FINANCIERO
from app.services.finanzas.tarifas import redondear_dinero


ESTADOS_PAGO_FINANCIERO = (
    "REGISTRADO",
    "ANULADO",
)


@dataclass(frozen=True)
class FilaReportePago:
    pago_id: int
    alumno_id: int
    nombre_alumno: str
    numero_identidad: str | None
    fecha_pago: date
    medio_pago: str
    referencia: str | None
    estado: str
    moneda: str
    valor: Decimal
    total_aplicado: Decimal
    saldo_sin_aplicar: Decimal


@dataclass(frozen=True)
class ResumenReportePagos:
    cantidad_pagos: int
    cantidad_registrados: int
    cantidad_anulados: int
    total_recibido: Decimal
    total_aplicado: Decimal
    saldo_sin_aplicar: Decimal


def _money(value) -> Decimal:
    return redondear_dinero(
        Decimal(value or 0)
    )


def obtener_reporte_pagos(
    *,
    academia_id: int,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    q: str | None = None,
    medio_pago: str | None = None,
    estado: str | None = None,
    alumno_ids: set[int] | None = None,
):
    if fecha_desde and fecha_hasta:
        if fecha_desde > fecha_hasta:
            raise FinanzasError(
                "La fecha desde no puede ser posterior "
                "a la fecha hasta."
            )

    medio_pago = (
        (medio_pago or "").strip().upper()
        or None
    )

    estado = (
        (estado or "").strip().upper()
        or None
    )

    if (
        medio_pago is not None
        and medio_pago not in MEDIOS_PAGO_FINANCIERO
    ):
        raise FinanzasError(
            "Medio de pago no válido."
        )

    if (
        estado is not None
        and estado not in ESTADOS_PAGO_FINANCIERO
    ):
        raise FinanzasError(
            "Estado de pago no válido."
        )

    query = (
        db.session.query(
            PagoFinanciero,
            Alumno,
        )
        .join(
            Alumno,
            Alumno.id == PagoFinanciero.alumno_id,
        )
        .filter(
            PagoFinanciero.academia_id == academia_id,
            Alumno.academia_id == academia_id,
        )
    )

    if alumno_ids is not None:
        query = query.filter(
            Alumno.id.in_(alumno_ids)
        )

    if fecha_desde is not None:
        query = query.filter(
            PagoFinanciero.fecha_pago >= fecha_desde
        )

    if fecha_hasta is not None:
        query = query.filter(
            PagoFinanciero.fecha_pago <= fecha_hasta
        )

    if medio_pago is not None:
        query = query.filter(
            PagoFinanciero.medio_pago == medio_pago
        )

    if estado is not None:
        query = query.filter(
            PagoFinanciero.estado == estado
        )

    q = (q or "").strip()

    if q:
        patron = f"%{q}%"

        query = query.filter(
            or_(
                Alumno.nombres.ilike(patron),
                Alumno.apellidos.ilike(patron),
                Alumno.numero_identidad.ilike(
                    patron
                ),
            )
        )

    registros = (
        query
        .order_by(
            PagoFinanciero.fecha_pago.desc(),
            PagoFinanciero.id.desc(),
        )
        .all()
    )

    pago_ids = [
        pago.id
        for pago, _alumno in registros
    ]

    aplicados_por_pago = {}

    if pago_ids:
        aplicados = (
            db.session.query(
                PagoAplicacion.pago_id,
                func.coalesce(
                    func.sum(
                        PagoAplicacion.valor_aplicado
                    ),
                    0,
                ),
            )
            .filter(
                PagoAplicacion.academia_id
                == academia_id,
                PagoAplicacion.pago_id.in_(
                    pago_ids
                ),
            )
            .group_by(
                PagoAplicacion.pago_id
            )
            .all()
        )

        aplicados_por_pago = {
            pago_id: _money(total)
            for pago_id, total in aplicados
        }

    filas = []

    for pago, alumno in registros:
        total_aplicado = (
            aplicados_por_pago.get(
                pago.id,
                Decimal("0.00"),
            )
        )

        if pago.estado == "ANULADO":
            saldo_sin_aplicar = Decimal("0.00")
        else:
            saldo_sin_aplicar = _money(
                Decimal(pago.valor)
                - total_aplicado
            )

        filas.append(
            FilaReportePago(
                pago_id=pago.id,
                alumno_id=alumno.id,
                nombre_alumno=(
                    f"{alumno.apellidos} "
                    f"{alumno.nombres}"
                ),
                numero_identidad=(
                    alumno.numero_identidad
                ),
                fecha_pago=pago.fecha_pago,
                medio_pago=pago.medio_pago,
                referencia=pago.referencia,
                estado=pago.estado,
                moneda=pago.moneda,
                valor=_money(pago.valor),
                total_aplicado=total_aplicado,
                saldo_sin_aplicar=(
                    saldo_sin_aplicar
                ),
            )
        )

    filas_registradas = [
        fila
        for fila in filas
        if fila.estado == "REGISTRADO"
    ]

    resumen = ResumenReportePagos(
        cantidad_pagos=len(filas),
        cantidad_registrados=len(
            filas_registradas
        ),
        cantidad_anulados=sum(
            1
            for fila in filas
            if fila.estado == "ANULADO"
        ),
        total_recibido=_money(
            sum(
                (
                    fila.valor
                    for fila in filas_registradas
                ),
                Decimal("0.00"),
            )
        ),
        total_aplicado=_money(
            sum(
                (
                    fila.total_aplicado
                    for fila in filas_registradas
                ),
                Decimal("0.00"),
            )
        ),
        saldo_sin_aplicar=_money(
            sum(
                (
                    fila.saldo_sin_aplicar
                    for fila in filas_registradas
                ),
                Decimal("0.00"),
            )
        ),
    )

    return resumen, filas