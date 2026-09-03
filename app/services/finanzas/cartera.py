from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import ObligacionFinanciera, PagoAplicacion, PagoFinanciero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.pagos import (
    calcular_saldo_pago,
    obtener_estado_pago_obligacion,
)
from app.services.finanzas.tarifas import redondear_dinero


@dataclass(frozen=True)
class ResumenCartera:
    total_obligaciones: Decimal
    total_aplicado: Decimal
    saldo_pendiente: Decimal
    saldo_pagos_sin_aplicar: Decimal
    cantidad_alumnos_con_saldo: int
    cantidad_obligaciones_pendientes: int
    cantidad_obligaciones_parciales: int
    cantidad_obligaciones_pagadas: int


@dataclass(frozen=True)
class FilaCarteraAlumno:
    alumno_id: int
    nombre: str
    total_obligaciones: Decimal
    total_aplicado: Decimal
    saldo_pendiente: Decimal
    saldo_pagos_sin_aplicar: Decimal
    cantidad_obligaciones_pendientes: int
    cantidad_obligaciones_parciales: int
    ultima_fecha_pago: date | None


@dataclass(frozen=True)
class ObligacionEstadoCuenta:
    obligacion: ObligacionFinanciera
    valor_original: Decimal
    total_aplicado: Decimal
    saldo: Decimal
    estado_derivado: str


@dataclass(frozen=True)
class PagoEstadoCuenta:
    pago: PagoFinanciero
    total_aplicado: Decimal
    saldo_sin_aplicar: Decimal


@dataclass(frozen=True)
class EstadoCuentaAlumno:
    alumno: Alumno
    obligaciones: list[ObligacionEstadoCuenta]
    pagos: list[PagoEstadoCuenta]
    total_generado: Decimal
    total_pagado: Decimal
    saldo_pendiente: Decimal
    saldo_pagos_sin_aplicar: Decimal


def _money(value) -> Decimal:
    return redondear_dinero(Decimal(value or 0))


def _alumno_de_academia(academia_id: int, alumno_id: int) -> Alumno:
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        raise FinanzasError("Alumno no pertenece a la academia indicada")
    return alumno


def _totales_aplicados_por_obligacion(academia_id: int, alumno_id: int | None = None) -> dict[int, Decimal]:
    query = (
        db.session.query(
            PagoAplicacion.obligacion_financiera_id,
            func.coalesce(func.sum(PagoAplicacion.valor_aplicado), 0),
        )
        .join(PagoFinanciero, PagoFinanciero.id == PagoAplicacion.pago_id)
        .filter(
            PagoAplicacion.academia_id == academia_id,
            PagoFinanciero.academia_id == academia_id,
            PagoFinanciero.estado == "REGISTRADO",
        )
        .group_by(PagoAplicacion.obligacion_financiera_id)
    )
    if alumno_id is not None:
        query = query.join(
            ObligacionFinanciera,
            ObligacionFinanciera.id == PagoAplicacion.obligacion_financiera_id,
        ).filter(ObligacionFinanciera.alumno_id == alumno_id)

    return {row[0]: _money(row[1]) for row in query.all()}


def _totales_aplicados_por_pago(academia_id: int, alumno_id: int | None = None) -> dict[int, Decimal]:
    query = (
        db.session.query(PagoAplicacion.pago_id, func.coalesce(func.sum(PagoAplicacion.valor_aplicado), 0))
        .join(PagoFinanciero, PagoFinanciero.id == PagoAplicacion.pago_id)
        .filter(
            PagoAplicacion.academia_id == academia_id,
            PagoFinanciero.academia_id == academia_id,
            PagoFinanciero.estado == "REGISTRADO",
        )
        .group_by(PagoAplicacion.pago_id)
    )
    if alumno_id is not None:
        query = query.filter(PagoFinanciero.alumno_id == alumno_id)

    return {row[0]: _money(row[1]) for row in query.all()}


def obtener_obligaciones_alumno(*, academia_id: int, alumno_id: int, incluir_anuladas: bool = True):
    _alumno_de_academia(academia_id, alumno_id)
    query = ObligacionFinanciera.query.filter_by(academia_id=academia_id, alumno_id=alumno_id)
    if not incluir_anuladas:
        query = query.filter(ObligacionFinanciera.estado != "ANULADA")
    obligaciones = query.order_by(ObligacionFinanciera.periodo.asc(), ObligacionFinanciera.id.asc()).all()
    aplicados = _totales_aplicados_por_obligacion(academia_id, alumno_id)

    resultado = []
    for obligacion in obligaciones:
        total = _money(obligacion.valor_final_snapshot)
        aplicado = aplicados.get(obligacion.id, Decimal("0.00"))
        if obligacion.estado == "ANULADA":
            saldo = Decimal("0.00")
            estado = "ANULADA"
        else:
            saldo = _money(total - aplicado)
            estado = obtener_estado_pago_obligacion(
                academia_id=academia_id,
                obligacion_financiera_id=obligacion.id,
            )
        resultado.append(
            ObligacionEstadoCuenta(
                obligacion=obligacion,
                valor_original=total,
                total_aplicado=aplicado,
                saldo=saldo,
                estado_derivado=estado,
            )
        )
    return resultado


def obtener_pagos_alumno(*, academia_id: int, alumno_id: int, incluir_anulados: bool = True):
    _alumno_de_academia(academia_id, alumno_id)
    query = PagoFinanciero.query.filter_by(academia_id=academia_id, alumno_id=alumno_id)
    if not incluir_anulados:
        query = query.filter(PagoFinanciero.estado != "ANULADO")
    pagos = query.order_by(PagoFinanciero.fecha_pago.desc(), PagoFinanciero.id.desc()).all()
    aplicados = _totales_aplicados_por_pago(academia_id, alumno_id)

    resultado = []
    for pago in pagos:
        total_aplicado = aplicados.get(pago.id, Decimal("0.00"))
        saldo = Decimal("0.00") if pago.estado == "ANULADO" else calcular_saldo_pago(academia_id=academia_id, pago_id=pago.id)
        resultado.append(PagoEstadoCuenta(pago=pago, total_aplicado=total_aplicado, saldo_sin_aplicar=saldo))
    return resultado


def obtener_estado_cuenta_alumno(*, academia_id: int, alumno_id: int) -> EstadoCuentaAlumno:
    alumno = _alumno_de_academia(academia_id, alumno_id)
    obligaciones = obtener_obligaciones_alumno(academia_id=academia_id, alumno_id=alumno_id, incluir_anuladas=True)
    pagos = obtener_pagos_alumno(academia_id=academia_id, alumno_id=alumno_id, incluir_anulados=True)

    obligaciones_operativas = [item for item in obligaciones if item.estado_derivado != "ANULADA"]
    pagos_operativos = [item for item in pagos if item.pago.estado != "ANULADO"]
    total_generado = _money(sum((item.valor_original for item in obligaciones_operativas), Decimal("0.00")))
    total_pagado = _money(sum((item.total_aplicado for item in obligaciones_operativas), Decimal("0.00")))
    saldo_pendiente = _money(sum((item.saldo for item in obligaciones_operativas), Decimal("0.00")))
    saldo_pagos_sin_aplicar = _money(sum((item.saldo_sin_aplicar for item in pagos_operativos), Decimal("0.00")))

    return EstadoCuentaAlumno(
        alumno=alumno,
        obligaciones=obligaciones,
        pagos=pagos,
        total_generado=total_generado,
        total_pagado=total_pagado,
        saldo_pendiente=saldo_pendiente,
        saldo_pagos_sin_aplicar=saldo_pagos_sin_aplicar,
    )


def obtener_cartera_alumnos(
    *,
    academia_id: int,
    q: str | None = None,
    con_saldo: bool = False,
    periodo: str | None = None,
    alumno_ids: set[int] | None = None,
):
    alumnos_query = Alumno.query.filter_by(academia_id=academia_id, activo=True)
    if alumno_ids is not None:
        alumnos_query = alumnos_query.filter(Alumno.id.in_(alumno_ids))
    if q:
        like = f"%{q.strip()}%"
        alumnos_query = alumnos_query.filter(or_(Alumno.nombres.like(like), Alumno.apellidos.like(like), Alumno.numero_identidad.like(like)))
    alumnos = alumnos_query.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).all()

    obligaciones_query = ObligacionFinanciera.query.filter(
        ObligacionFinanciera.academia_id == academia_id,
        ObligacionFinanciera.estado != "ANULADA",
    )
    if periodo:
        obligaciones_query = obligaciones_query.filter(ObligacionFinanciera.periodo == periodo)
    if alumno_ids is not None:
        obligaciones_query = obligaciones_query.filter(ObligacionFinanciera.alumno_id.in_(alumno_ids))
    obligaciones = obligaciones_query.all()
    aplicados = _totales_aplicados_por_obligacion(academia_id)
    pagos_aplicados = _totales_aplicados_por_pago(academia_id)
    ultimos_pagos = {
        row[0]: row[1]
        for row in db.session.query(PagoFinanciero.alumno_id, func.max(PagoFinanciero.fecha_pago))
        .filter(PagoFinanciero.academia_id == academia_id, PagoFinanciero.estado == "REGISTRADO")
        .group_by(PagoFinanciero.alumno_id)
        .all()
    }
    pagos = PagoFinanciero.query.filter(PagoFinanciero.academia_id == academia_id, PagoFinanciero.estado == "REGISTRADO").all()

    por_alumno = {alumno.id: {"total": Decimal("0.00"), "aplicado": Decimal("0.00"), "pendientes": 0, "parciales": 0} for alumno in alumnos}
    for obligacion in obligaciones:
        if obligacion.alumno_id not in por_alumno:
            continue
        total = _money(obligacion.valor_final_snapshot)
        aplicado = aplicados.get(obligacion.id, Decimal("0.00"))
        por_alumno[obligacion.alumno_id]["total"] += total
        por_alumno[obligacion.alumno_id]["aplicado"] += aplicado
        if aplicado == 0:
            por_alumno[obligacion.alumno_id]["pendientes"] += 1
        elif aplicado < total:
            por_alumno[obligacion.alumno_id]["parciales"] += 1

    saldo_pagos_por_alumno = {alumno.id: Decimal("0.00") for alumno in alumnos}
    for pago in pagos:
        if pago.alumno_id in saldo_pagos_por_alumno:
            saldo_pagos_por_alumno[pago.alumno_id] += _money(Decimal(pago.valor) - pagos_aplicados.get(pago.id, Decimal("0.00")))

    filas = []
    for alumno in alumnos:
        datos = por_alumno[alumno.id]
        saldo = _money(datos["total"] - datos["aplicado"])
        if con_saldo and saldo <= 0:
            continue
        filas.append(
            FilaCarteraAlumno(
                alumno_id=alumno.id,
                nombre=f"{alumno.apellidos} {alumno.nombres}",
                total_obligaciones=_money(datos["total"]),
                total_aplicado=_money(datos["aplicado"]),
                saldo_pendiente=saldo,
                saldo_pagos_sin_aplicar=_money(saldo_pagos_por_alumno.get(alumno.id, Decimal("0.00"))),
                cantidad_obligaciones_pendientes=datos["pendientes"],
                cantidad_obligaciones_parciales=datos["parciales"],
                ultima_fecha_pago=ultimos_pagos.get(alumno.id),
            )
        )
    return filas


def obtener_resumen_cartera_academia(
    *,
    academia_id: int,
    periodo: str | None = None,
    alumno_ids: set[int] | None = None,
) -> ResumenCartera:
    filas = obtener_cartera_alumnos(academia_id=academia_id, periodo=periodo, alumno_ids=alumno_ids)
    obligaciones = ObligacionFinanciera.query.filter(
        ObligacionFinanciera.academia_id == academia_id,
        ObligacionFinanciera.estado != "ANULADA",
    )
    if periodo:
        obligaciones = obligaciones.filter(ObligacionFinanciera.periodo == periodo)
    if alumno_ids is not None:
        obligaciones = obligaciones.filter(ObligacionFinanciera.alumno_id.in_(alumno_ids))
    obligaciones = obligaciones.all()
    aplicados = _totales_aplicados_por_obligacion(academia_id)

    pendientes = parciales = pagadas = 0
    for obligacion in obligaciones:
        total = _money(obligacion.valor_final_snapshot)
        aplicado = aplicados.get(obligacion.id, Decimal("0.00"))
        if aplicado == 0:
            pendientes += 1
        elif aplicado < total:
            parciales += 1
        else:
            pagadas += 1

    return ResumenCartera(
        total_obligaciones=_money(sum((fila.total_obligaciones for fila in filas), Decimal("0.00"))),
        total_aplicado=_money(sum((fila.total_aplicado for fila in filas), Decimal("0.00"))),
        saldo_pendiente=_money(sum((fila.saldo_pendiente for fila in filas), Decimal("0.00"))),
        saldo_pagos_sin_aplicar=_money(sum((fila.saldo_pagos_sin_aplicar for fila in filas), Decimal("0.00"))),
        cantidad_alumnos_con_saldo=sum(1 for fila in filas if fila.saldo_pendiente > 0),
        cantidad_obligaciones_pendientes=pendientes,
        cantidad_obligaciones_parciales=parciales,
        cantidad_obligaciones_pagadas=pagadas,
    )
