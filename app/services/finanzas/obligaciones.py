import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import AlumnoPlanFinanciero, ObligacionFinanciera
from app.services.finanzas.configuracion import obtener_configuracion_financiera
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.vencimientos import calcular_fecha_vencimiento_pension


PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass
class ResumenGeneracionPensiones:
    periodo: str
    academia_id: int
    evaluados: int = 0
    creados: int = 0
    existentes: int = 0
    sin_plan: int = 0
    errores: list[dict] = field(default_factory=list)


def parsear_periodo(periodo: str) -> tuple[str, date]:
    periodo = (periodo or "").strip()
    if not PERIODO_RE.match(periodo):
        raise FinanzasError("El periodo debe tener formato YYYY-MM")

    anio, mes = periodo.split("-")
    return periodo, date(int(anio), int(mes), 1)


def obtener_plan_financiero_vigente(*, academia_id: int, alumno_id: int, fecha_referencia: date):
    planes = (
        AlumnoPlanFinanciero.query
        .filter(
            AlumnoPlanFinanciero.academia_id == academia_id,
            AlumnoPlanFinanciero.alumno_id == alumno_id,
            AlumnoPlanFinanciero.estado == "ACTIVO",
            AlumnoPlanFinanciero.fecha_inicio <= fecha_referencia,
            or_(
                AlumnoPlanFinanciero.fecha_fin.is_(None),
                fecha_referencia <= AlumnoPlanFinanciero.fecha_fin,
            ),
        )
        .all()
    )
    if len(planes) > 1:
        raise FinanzasError("El alumno tiene mas de un plan financiero activo para el periodo")
    return planes[0] if planes else None


def _crear_obligacion_pension(
    *,
    academia_id: int,
    alumno: Alumno,
    plan: AlumnoPlanFinanciero,
    periodo: str,
    fecha_emision: date,
    fecha_vencimiento: date | None,
):
    obligacion = ObligacionFinanciera(
        academia_id=academia_id,
        alumno_id=alumno.id,
        alumno_plan_financiero_id=plan.id,
        periodo=periodo,
        tipo_obligacion="PENSION",
        concepto=f"Pension {periodo}",
        origen="GENERACION_MENSUAL",
        fecha_emision=fecha_emision,
        fecha_vencimiento=fecha_vencimiento,
        tarifa_base_snapshot=Decimal(plan.tarifa_base_snapshot),
        porcentaje_descuento_snapshot=plan.descuento_porcentaje_snapshot,
        valor_descuento_snapshot=Decimal(plan.descuento_valor_snapshot),
        valor_final_snapshot=Decimal(plan.valor_final_snapshot),
        moneda_snapshot=plan.moneda_snapshot,
        estado="PENDIENTE",
    )
    db.session.add(obligacion)
    db.session.flush()
    return obligacion


def generar_obligaciones_mensuales(*, academia_id: int, periodo: str) -> ResumenGeneracionPensiones:
    periodo, fecha_periodo = parsear_periodo(periodo)
    resumen = ResumenGeneracionPensiones(periodo=periodo, academia_id=academia_id)
    configuracion = obtener_configuracion_financiera(academia_id=academia_id)
    dia_vencimiento = configuracion.dia_vencimiento_pension if configuracion else None
    fecha_vencimiento = calcular_fecha_vencimiento_pension(periodo, dia_vencimiento)

    alumnos = (
        Alumno.query
        .filter(Alumno.academia_id == academia_id, Alumno.activo.is_(True))
        .order_by(Alumno.apellidos.asc(), Alumno.nombres.asc(), Alumno.id.asc())
        .all()
    )

    for alumno in alumnos:
        resumen.evaluados += 1

        existente = (
            ObligacionFinanciera.query
            .filter_by(
                academia_id=academia_id,
                alumno_id=alumno.id,
                periodo=periodo,
                tipo_obligacion="PENSION",
            )
            .first()
        )
        if existente is not None:
            resumen.existentes += 1
            continue

        try:
            with db.session.begin_nested():
                plan = obtener_plan_financiero_vigente(
                    academia_id=academia_id,
                    alumno_id=alumno.id,
                    fecha_referencia=fecha_periodo,
                )
                if plan is None:
                    resumen.sin_plan += 1
                    continue

                _crear_obligacion_pension(
                    academia_id=academia_id,
                    alumno=alumno,
                    plan=plan,
                    periodo=periodo,
                    fecha_emision=fecha_periodo,
                    fecha_vencimiento=fecha_vencimiento,
                )
                resumen.creados += 1
        except Exception as exc:
            resumen.errores.append(
                {
                    "alumno_id": alumno.id,
                    "error": str(exc),
                }
            )

    return resumen
