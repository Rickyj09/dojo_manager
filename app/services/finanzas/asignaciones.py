from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, update

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
from app.services.finanzas.tarifarios import validar_referencias_activas, validar_tarifario_utilizable


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


def resolver_contexto_descuento_hermanos(
    *,
    academia_id: int,
    alumno_id: int,
    fecha: date,
    grupo_familiar_id: int | None = None,
    aplicar_descuentos: bool = True,
):
    if not aplicar_descuentos:
        return None, 1, None

    alumno = _validar_objeto_tenant(
        Alumno,
        alumno_id,
        academia_id,
        "Alumno no pertenece a la academia indicada",
    )

    if grupo_familiar_id is not None:
        grupo_familiar = _validar_objeto_tenant(
            GrupoFamiliar,
            grupo_familiar_id,
            academia_id,
            "Grupo familiar no pertenece a la academia indicada",
        )

        familia_activa = obtener_familia_activa_del_alumno(
            academia_id=academia_id,
            alumno_id=alumno.id,
            fecha_referencia=fecha,
        )

        if (
            familia_activa is None
            or familia_activa.id != grupo_familiar.id
        ):
            raise FinanzasError(
                "El alumno no pertenece a la familia indicada"
            )

    else:
        grupo_familiar = obtener_familia_activa_del_alumno(
            academia_id=academia_id,
            alumno_id=alumno.id,
            fecha_referencia=fecha,
        )

    cantidad_familia = 1

    if grupo_familiar is not None:
        cantidad_familia = contar_alumnos_activos_de_familia(
            academia_id=academia_id,
            grupo_familiar_id=grupo_familiar.id,
            fecha_referencia=fecha,
        )

    regla = resolver_regla_hermanos(
        academia_id=academia_id,
        cantidad_alumnos=cantidad_familia,
        fecha=fecha,
    )

    return grupo_familiar, cantidad_familia, regla

def resolver_tarifa_asignacion(
    *,
    academia_id, plan_id, frecuencia_id, fecha_inicio,
    tarifario_id=None, tarifa_plan_id=None,
):
    """Resolución común para consultar y guardar, sin mutaciones."""
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

    validar_referencias_activas(academia_id=academia_id, plan_id=plan.id, frecuencia_id=frecuencia.id)
    validar_tarifario_utilizable(tarifario, academia_id=academia_id, fecha=fecha_inicio)

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
        raise FinanzasError("Tarifa/configuracion no disponible. No existe una tarifa activa para el plan y frecuencia seleccionados.")
    return tarifa


def asignar_plan_financiero(
    *, academia_id: int, alumno_id: int, plan_id: int, frecuencia_id: int,
    fecha_inicio: date, usuario_id: int | None = None,
    tarifario_id: int | None = None, tarifa_plan_id: int | None = None,
    grupo_familiar_id: int | None = None, motivo: str | None = None,
    aplicar_descuentos: bool = True, asignacion_actual_id: int | None = None,
):
    # El UPDATE sin cambio de valor serializa por alumno también en SQLite,
    # donde SELECT FOR UPDATE no bloquea. El lock dura hasta commit/rollback.
    bloqueado = db.session.execute(
        update(Alumno).where(Alumno.id == alumno_id, Alumno.academia_id == academia_id)
        .values(activo=Alumno.activo).execution_options(synchronize_session=False)
    )
    if bloqueado.rowcount != 1:
        raise FinanzasError("Alumno no pertenece a la academia indicada")
    alumno = _validar_objeto_tenant(Alumno, alumno_id, academia_id, "Alumno no pertenece a la academia indicada")
    activas = AlumnoPlanFinanciero.query.filter_by(
        academia_id=academia_id, alumno_id=alumno.id, estado="ACTIVO",
    ).populate_existing().all()
    if len(activas) > 1:
        raise FinanzasError("El alumno posee varias asignaciones activas. Revise su configuración antes de continuar.")
    anterior = activas[0] if activas else None
    if asignacion_actual_id is not None and asignacion_actual_id != (anterior.id if anterior else 0):
        raise FinanzasError("La configuración financiera cambió. Vuelva a abrir el formulario antes de guardar.")
    if anterior is not None and fecha_inicio <= anterior.fecha_inicio:
        raise FinanzasError("La nueva asignacion debe iniciar despues de la asignacion activa")

    tarifa = resolver_tarifa_asignacion(
        academia_id=academia_id, plan_id=plan_id, frecuencia_id=frecuencia_id,
        fecha_inicio=fecha_inicio, tarifario_id=tarifario_id, tarifa_plan_id=tarifa_plan_id,
    )
    tarifario, plan, frecuencia = tarifa.tarifario, tarifa.plan, tarifa.frecuencia

    grupo_familiar, cantidad_familia, regla = (
    resolver_contexto_descuento_hermanos(
        academia_id=academia_id,
        alumno_id=alumno.id,
        fecha=fecha_inicio,
        grupo_familiar_id=grupo_familiar_id,
        aplicar_descuentos=aplicar_descuentos,
    )
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
        aplicar_descuentos=aplicar_descuentos,
    )

    descuento = (
        resultado.descuentos_aplicados[0]["descuento"]
        if resultado.descuentos_aplicados
        else Decimal("0.00")
    )

    porcentaje = regla.porcentaje if regla is not None else None

    if anterior is not None:
        anterior.fecha_fin = fecha_inicio - timedelta(days=1)
        anterior.estado = "FINALIZADO"

    asignacion = AlumnoPlanFinanciero(
        academia_id=academia_id,
        alumno_id=alumno.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        tarifario_id=tarifario.id,
        tarifa_plan_id=tarifa.id,
        grupo_familiar_id=(
            grupo_familiar.id
            if grupo_familiar is not None
            else None
        ),
        regla_descuento_id=(
            regla.id
            if regla is not None
            else None
        ),
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
