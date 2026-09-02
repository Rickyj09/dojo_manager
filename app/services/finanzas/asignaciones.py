from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import (
    AlumnoPlanFinanciero,
    FrecuenciaEntrenamiento,
    GrupoFamiliar,
    PlanFinanciero,
    ReglaDescuento,
    TarifaPlan,
    Tarifario,
)
from app.services.finanzas.familias import (
    FinanzasError,
    contar_alumnos_activos_de_familia,
    obtener_familia_activa_del_alumno,
)
from app.services.finanzas.tarifas import calcular_tarifa


def resolver_tarifario_vigente(*, academia_id: int, fecha: date) -> Tarifario:
    tarifarios = (
        Tarifario.query
        .filter(
            Tarifario.academia_id == academia_id,
            Tarifario.estado == "VIGENTE",
            Tarifario.fecha_inicio_vigencia <= fecha,
            or_(Tarifario.fecha_fin_vigencia.is_(None), fecha <= Tarifario.fecha_fin_vigencia),
        )
        .all()
    )
    if not tarifarios:
        raise FinanzasError("No existe tarifario vigente para la fecha indicada")
    if len(tarifarios) > 1:
        raise FinanzasError("Existe mas de un tarifario vigente para la fecha indicada")
    return tarifarios[0]


def resolver_regla_hermanos(*, academia_id: int, cantidad_alumnos: int, fecha: date):
    if cantidad_alumnos < 2:
        return None

    return (
        ReglaDescuento.query
        .filter(
            ReglaDescuento.academia_id == academia_id,
            ReglaDescuento.tipo == "HERMANOS",
            ReglaDescuento.activo.is_(True),
            ReglaDescuento.cantidad_minima <= cantidad_alumnos,
            or_(ReglaDescuento.vigencia_desde.is_(None), ReglaDescuento.vigencia_desde <= fecha),
            or_(ReglaDescuento.vigencia_hasta.is_(None), fecha <= ReglaDescuento.vigencia_hasta),
        )
        .order_by(ReglaDescuento.cantidad_minima.desc(), ReglaDescuento.id.asc())
        .first()
    )


def _validar_objeto_tenant(model, entity_id: int, academia_id: int, mensaje: str):
    item = model.query.filter_by(id=entity_id, academia_id=academia_id).first()
    if item is None:
        raise FinanzasError(mensaje)
    return item


def asignar_plan_financiero(
    *,
    academia_id: int,
    alumno_id: int,
    plan_id: int,
    frecuencia_id: int,
    fecha_inicio: date,
    usuario_id: int | None = None,
    tarifario_id: int | None = None,
    tarifa_plan_id: int | None = None,
    grupo_familiar_id: int | None = None,
    motivo: str | None = None,
):
    alumno = _validar_objeto_tenant(Alumno, alumno_id, academia_id, "Alumno no pertenece a la academia indicada")
    plan = _validar_objeto_tenant(PlanFinanciero, plan_id, academia_id, "Plan no pertenece a la academia indicada")
    frecuencia = _validar_objeto_tenant(
        FrecuenciaEntrenamiento,
        frecuencia_id,
        academia_id,
        "Frecuencia no pertenece a la academia indicada",
    )

    if tarifario_id is None:
        tarifario = resolver_tarifario_vigente(academia_id=academia_id, fecha=fecha_inicio)
    else:
        tarifario = _validar_objeto_tenant(
            Tarifario,
            tarifario_id,
            academia_id,
            "Tarifario no pertenece a la academia indicada",
        )

    if tarifa_plan_id is None:
        tarifa = (
            TarifaPlan.query
            .filter_by(
                academia_id=academia_id,
                tarifario_id=tarifario.id,
                plan_id=plan.id,
                frecuencia_id=frecuencia.id,
                activo=True,
            )
            .first()
        )
    else:
        tarifa = (
            TarifaPlan.query
            .filter_by(
                id=tarifa_plan_id,
                academia_id=academia_id,
                tarifario_id=tarifario.id,
                plan_id=plan.id,
                frecuencia_id=frecuencia.id,
                activo=True,
            )
            .first()
        )
    if tarifa is None:
        raise FinanzasError("Tarifa/configuracion no disponible")

    if grupo_familiar_id is not None:
        grupo_familiar = _validar_objeto_tenant(
            GrupoFamiliar,
            grupo_familiar_id,
            academia_id,
            "Grupo familiar no pertenece a la academia indicada",
        )
        familia_activa = obtener_familia_activa_del_alumno(academia_id=academia_id, alumno_id=alumno.id)
        if familia_activa is None or familia_activa.id != grupo_familiar.id:
            raise FinanzasError("El alumno no pertenece a la familia indicada")
    else:
        grupo_familiar = obtener_familia_activa_del_alumno(academia_id=academia_id, alumno_id=alumno.id)

    cantidad_familia = 1
    if grupo_familiar is not None:
        cantidad_familia = contar_alumnos_activos_de_familia(
            academia_id=academia_id,
            grupo_familiar_id=grupo_familiar.id,
        )

    regla = resolver_regla_hermanos(
        academia_id=academia_id,
        cantidad_alumnos=cantidad_familia,
        fecha=fecha_inicio,
    )
    regla_ids = [regla.id] if regla is not None else []

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={
            "reglas_descuento_ids": regla_ids,
            "cantidad_alumnos": cantidad_familia,
            "fecha": fecha_inicio,
        },
    )

    descuento = resultado.descuentos_aplicados[0]["descuento"] if resultado.descuentos_aplicados else Decimal("0.00")
    porcentaje = regla.porcentaje if regla is not None else None

    anterior = (
        AlumnoPlanFinanciero.query
        .filter_by(academia_id=academia_id, alumno_id=alumno.id, estado="ACTIVO")
        .first()
    )
    if anterior is not None:
        if fecha_inicio <= anterior.fecha_inicio:
            raise FinanzasError("La nueva asignacion debe iniciar despues de la asignacion activa")
        anterior.fecha_fin = fecha_inicio - timedelta(days=1)
        anterior.estado = "FINALIZADO"

    asignacion = AlumnoPlanFinanciero(
        academia_id=academia_id,
        alumno_id=alumno.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        tarifario_id=tarifario.id,
        tarifa_plan_id=tarifa.id,
        grupo_familiar_id=grupo_familiar.id if grupo_familiar is not None else None,
        regla_descuento_id=regla.id if regla is not None else None,
        fecha_inicio=fecha_inicio,
        tarifa_base_snapshot=resultado.tarifa_base,
        descuento_porcentaje_snapshot=porcentaje,
        descuento_valor_snapshot=descuento,
        valor_final_snapshot=resultado.valor_final,
        moneda_snapshot=tarifario.moneda,
        estado="ACTIVO",
        motivo=motivo,
        created_by_id=usuario_id,
    )
    db.session.add(asignacion)
    db.session.flush()
    return asignacion
