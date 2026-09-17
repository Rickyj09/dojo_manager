import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from contextlib import nullcontext
from sqlalchemy import or_, update

from app.extensions import db
from app.models.alumno import Alumno
from app.models.academia import Academia
from app.models.finanzas import AlumnoPlanFinanciero, ObligacionFinanciera
from app.services.finanzas.configuracion import obtener_configuracion_financiera
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.vencimientos import calcular_fecha_vencimiento_pension


PERIODO_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@dataclass
class ResumenGeneracionPensiones:
    periodo: str
    academia_id: int
    evaluados: int = 0
    creados: int = 0
    existentes: int = 0
    sin_plan: int = 0
    errores: list[dict] = field(default_factory=list)
    con_plan: int = 0
    omitidos: list[dict] = field(default_factory=list)
    totales: dict = field(default_factory=dict)
    fecha_vencimiento: date | None = None


def parsear_periodo(periodo: str) -> tuple[str, date]:
    periodo = (periodo or "").strip()
    if not PERIODO_RE.match(periodo):
        raise FinanzasError("El periodo debe tener formato YYYY-MM")

    anio, mes = periodo.split("-")
    try:
        return periodo, date(int(anio), int(mes), 1)
    except ValueError as exc:
        raise FinanzasError("El periodo debe tener formato YYYY-MM y un año válido") from exc


def obtener_plan_financiero_vigente(*, academia_id: int, alumno_id: int, fecha_referencia: date):
    planes = (
        AlumnoPlanFinanciero.query
        .filter(
            AlumnoPlanFinanciero.academia_id == academia_id,
            AlumnoPlanFinanciero.alumno_id == alumno_id,
            AlumnoPlanFinanciero.estado.in_(("ACTIVO", "FINALIZADO")),
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


def previsualizar_obligaciones_mensuales(*, academia_id: int, periodo: str) -> ResumenGeneracionPensiones:
    # El mismo recorrido y resolución que la generación, sin flush ni bloqueos.
    with db.session.no_autoflush:
        return _procesar_obligaciones_mensuales(academia_id=academia_id, periodo=periodo, escribir=False)


def generar_obligaciones_mensuales(*, academia_id: int, periodo: str) -> ResumenGeneracionPensiones:
    return _procesar_obligaciones_mensuales(academia_id=academia_id, periodo=periodo, escribir=True)


def _procesar_obligaciones_mensuales(*, academia_id: int, periodo: str, escribir: bool):
    periodo, fecha_periodo = parsear_periodo(periodo)
    if escribir:
        # Serializa las generaciones de la academia hasta commit/rollback, incluso
        # en SQLite (SELECT FOR UPDATE no bloquea allí). La UNIQUE sigue siendo
        # la última garantía para cualquier otro escritor.
        db.session.execute(update(Academia).where(Academia.id == academia_id)
                           .values(activo=Academia.activo)
                           .execution_options(synchronize_session=False))
    resumen = ResumenGeneracionPensiones(periodo=periodo, academia_id=academia_id)
    configuracion = obtener_configuracion_financiera(academia_id=academia_id)
    dia_vencimiento = configuracion.dia_vencimiento_pension if configuracion else None
    fecha_vencimiento = calcular_fecha_vencimiento_pension(periodo, dia_vencimiento)
    resumen.fecha_vencimiento = fecha_vencimiento

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
        try:
            with db.session.begin_nested() if escribir else nullcontext():
                plan = obtener_plan_financiero_vigente(
                    academia_id=academia_id,
                    alumno_id=alumno.id,
                    fecha_referencia=fecha_periodo,
                )
                valido = plan is not None and all(
                    valor is not None and Decimal(valor).is_finite() and Decimal(valor) >= 0
                    for valor in (plan.tarifa_base_snapshot, plan.descuento_valor_snapshot, plan.valor_final_snapshot)
                ) and bool(plan.moneda_snapshot and plan.moneda_snapshot.strip())
                if valido:
                    resumen.con_plan += 1
                if existente is not None:
                    resumen.existentes += 1
                    continue
                if not valido:
                    resumen.sin_plan += 1
                    resumen.omitidos.append({"alumno_id": alumno.id, "nombre": f"{alumno.apellidos} {alumno.nombres}"})
                    continue

                if escribir:
                    _crear_obligacion_pension(
                        academia_id=academia_id,
                        alumno=alumno,
                        plan=plan,
                        periodo=periodo,
                        fecha_emision=fecha_periodo,
                        fecha_vencimiento=fecha_vencimiento,
                    )
                resumen.creados += 1
                moneda = plan.moneda_snapshot
                resumen.totales[moneda] = resumen.totales.get(moneda, Decimal("0.00")) + Decimal(plan.valor_final_snapshot)
        except FinanzasError:
            if existente is not None:
                resumen.existentes += 1
            else:
                resumen.sin_plan += 1
                resumen.omitidos.append({"alumno_id": alumno.id, "nombre": f"{alumno.apellidos} {alumno.nombres}"})
        except Exception as exc:
            resumen.errores.append(
                {
                    "alumno_id": alumno.id,
                    "error": str(exc),
                }
            )

    return resumen
