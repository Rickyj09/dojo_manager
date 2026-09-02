from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.alumno import Alumno
from app.models.finanzas import (
    AlumnoGrupoFamiliar,
    AlumnoPlanFinanciero,
    FrecuenciaEntrenamiento,
    GrupoFamiliar,
    PlanFinanciero,
    ReglaDescuento,
    TarifaPlan,
    Tarifario,
)
from app.services.finanzas.asignaciones import asignar_plan_financiero, resolver_tarifario_vigente
from app.services.finanzas.familias import (
    FinanzasError,
    asignar_alumno_a_familia,
    contar_alumnos_activos_de_familia,
    crear_grupo_familiar,
    obtener_familia_activa_del_alumno,
    retirar_alumno_de_familia,
)
from app.services.finanzas.tarifas import calcular_tarifa


def crear_plan(db, academia_id, codigo):
    plan = PlanFinanciero(academia_id=academia_id, codigo=codigo, nombre=codigo)
    db.session.add(plan)
    db.session.flush()
    return plan


def crear_frecuencia(db, academia_id, codigo, dias):
    frecuencia = FrecuenciaEntrenamiento(
        academia_id=academia_id,
        codigo=codigo,
        nombre=f"{dias} dias",
        dias_semana=dias,
    )
    db.session.add(frecuencia)
    db.session.flush()
    return frecuencia


def crear_tarifario(db, academia_id, inicio=date(2026, 9, 1), fin=None, estado="VIGENTE"):
    tarifario = Tarifario(
        academia_id=academia_id,
        nombre=f"Tarifario {inicio.isoformat()}",
        fecha_inicio_vigencia=inicio,
        fecha_fin_vigencia=fin,
        estado=estado,
        moneda="USD",
    )
    db.session.add(tarifario)
    db.session.flush()
    return tarifario


def crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor):
    tarifa = TarifaPlan(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        valor_base=Decimal(valor),
    )
    db.session.add(tarifa)
    db.session.flush()
    return tarifa


def crear_regla(db, academia_id, codigo, porcentaje, cantidad, decimales=0, desde=None, hasta=None):
    regla = ReglaDescuento(
        academia_id=academia_id,
        codigo=codigo,
        nombre=codigo,
        tipo="HERMANOS",
        porcentaje=Decimal(porcentaje),
        cantidad_minima=cantidad,
        decimales_redondeo=decimales,
        vigencia_desde=desde,
        vigencia_hasta=hasta,
    )
    db.session.add(regla)
    db.session.flush()
    return regla


def crear_alumno_extra(db, base_data, nombres):
    ref = base_data["alumno_a1"]
    alumno = Alumno(
        academia_id=base_data["academia_a"].id,
        nombres=nombres,
        apellidos="Perez",
        fecha_nacimiento=date(2015, 1, 1),
        genero="M",
        categoria_id=ref.categoria_id,
        sucursal_id=ref.sucursal_id,
        grado_id=ref.grado_id,
    )
    db.session.add(alumno)
    db.session.flush()
    return alumno


def preparar_regular_d2(db, base_data, valor="55.00"):
    academia_id = base_data["academia_a"].id
    tarifario = crear_tarifario(db, academia_id)
    plan = crear_plan(db, academia_id, "REGULAR")
    frecuencia = crear_frecuencia(db, academia_id, "D2", 2)
    tarifa = crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor)
    return academia_id, tarifario, plan, frecuencia, tarifa


def test_crear_grupo_familiar_tenant_a(db, base_data):
    grupo = crear_grupo_familiar(academia_id=base_data["academia_a"].id, codigo="FAM-000001", nombre="Familia Perez")
    db.session.commit()

    assert grupo.id is not None
    assert grupo.codigo == "FAM_000001"
    assert grupo.academia_id == base_data["academia_a"].id


def test_mismo_codigo_familiar_permitido_tenant_b(db, base_data):
    crear_grupo_familiar(academia_id=base_data["academia_a"].id, codigo="FAM-000001", nombre="Familia A")
    crear_grupo_familiar(academia_id=base_data["academia_b"].id, codigo="FAM-000001", nombre="Familia B")
    db.session.commit()

    assert GrupoFamiliar.query.filter_by(codigo="FAM_000001").count() == 2


def test_codigo_familiar_duplicado_mismo_tenant_falla(db, base_data):
    crear_grupo_familiar(academia_id=base_data["academia_a"].id, codigo="FAM-000001", nombre="Familia A")

    with pytest.raises(IntegrityError):
        crear_grupo_familiar(academia_id=base_data["academia_a"].id, codigo="FAM-000001", nombre="Familia A2")


def test_alumno_tenant_b_no_puede_entrar_a_familia_a(db, base_data):
    grupo = crear_grupo_familiar(academia_id=base_data["academia_a"].id, codigo="FAM-000001", nombre="Familia A")

    with pytest.raises(FinanzasError, match="Alumno no pertenece"):
        asignar_alumno_a_familia(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_b1"].id,
            grupo_familiar_id=grupo.id,
            fecha_inicio=date(2026, 9, 1),
        )


def test_alumno_no_puede_tener_dos_familias_activas(db, base_data):
    academia_id = base_data["academia_a"].id
    grupo_1 = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia 1")
    grupo_2 = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000002", nombre="Familia 2")
    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        grupo_familiar_id=grupo_1.id,
        fecha_inicio=date(2026, 9, 1),
    )

    with pytest.raises(FinanzasError, match="familia activa"):
        asignar_alumno_a_familia(
            academia_id=academia_id,
            alumno_id=base_data["alumno_a1"].id,
            grupo_familiar_id=grupo_2.id,
            fecha_inicio=date(2026, 9, 2),
        )


def test_retirar_alumno_conserva_historial(db, base_data):
    academia_id = base_data["academia_a"].id
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    membresia = asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        grupo_familiar_id=grupo.id,
        fecha_inicio=date(2026, 9, 1),
    )

    retirar_alumno_de_familia(academia_id=academia_id, alumno_id=base_data["alumno_a1"].id, fecha_fin=date(2026, 10, 1))
    db.session.commit()

    membresia_guardada = db.session.get(AlumnoGrupoFamiliar, membresia.id)
    assert membresia_guardada.activo is False
    assert membresia_guardada.fecha_fin == date(2026, 10, 1)


def test_contar_un_alumno_sin_descuento_hermanos(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    asignar_alumno_a_familia(academia_id=academia_id, alumno_id=base_data["alumno_a1"].id, grupo_familiar_id=grupo.id, fecha_inicio=date(2026, 9, 1))
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2)
    db.session.commit()

    cantidad = contar_alumnos_activos_de_familia(academia_id=academia_id, grupo_familiar_id=grupo.id)
    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": cantidad, "fecha": date(2026, 9, 1)},
    )

    assert cantidad == 1
    assert resultado.valor_final == Decimal("55.00")


def test_contar_dos_aplica_regla_10(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    for alumno in (base_data["alumno_a1"], base_data["alumno_a2"]):
        asignar_alumno_a_familia(academia_id=academia_id, alumno_id=alumno.id, grupo_familiar_id=grupo.id, fecha_inicio=date(2026, 9, 1))
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": 2, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("50.00")


def test_contar_tres_aplica_regla_15(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    alumno_3 = crear_alumno_extra(db, base_data, "Luis")
    for alumno in (base_data["alumno_a1"], base_data["alumno_a2"], alumno_3):
        asignar_alumno_a_familia(academia_id=academia_id, alumno_id=alumno.id, grupo_familiar_id=grupo.id, fecha_inicio=date(2026, 9, 1))
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2)
    crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": 3, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("47.00")


def test_cuatro_utiliza_regla_maxima_aplicable(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2)
    regla_3 = crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": 4, "fecha": date(2026, 9, 1)},
    )

    assert resultado.descuentos_aplicados[0]["regla_id"] == regla_3.id
    assert resultado.valor_final == Decimal("47.00")


def test_regla_expirada_no_aplica(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, desde=date(2026, 1, 1), hasta=date(2026, 8, 31))
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": 2, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("55.00")


def test_regla_futura_no_aplica(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, desde=date(2026, 10, 1))
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": 2, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("55.00")


def test_redondeo_cero_decimales(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    regla = crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3, decimales=0)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"reglas_descuento_ids": [regla.id], "cantidad_alumnos": 3, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("47.00")


def test_redondeo_dos_decimales(db, base_data):
    academia_id, tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    regla = crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3, decimales=2)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"reglas_descuento_ids": [regla.id], "cantidad_alumnos": 3, "fecha": date(2026, 9, 1)},
    )

    assert resultado.valor_final == Decimal("46.75")


def test_matriz_completa_borjas_lions(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = crear_tarifario(db, academia_id)
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, decimales=0)
    crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3, decimales=0)
    casos = [
        ("REGULAR", "D2", 2, "55.00", "50.00", "47.00"),
        ("REGULAR", "D3", 3, "60.00", "54.00", "51.00"),
        ("REGULAR", "D4", 4, "70.00", "63.00", "60.00"),
        ("DESARROLLO", "D3", 3, "65.00", "59.00", "55.00"),
        ("DESARROLLO", "D4", 4, "75.00", "68.00", "64.00"),
        ("DESARROLLO", "D5", 5, "85.00", "77.00", "72.00"),
        ("PREMIUM", "D3", 3, "95.00", "86.00", "81.00"),
        ("PREMIUM_PLUS", "D2", 2, "125.00", "113.00", "106.00"),
        ("PREMIUM_PLUS", "D3", 3, "125.00", "113.00", "106.00"),
        ("ELITE", "D5", 5, "75.00", "68.00", "64.00"),
        ("ELITE", "D6", 6, "85.00", "77.00", "72.00"),
    ]

    for plan_codigo, frecuencia_codigo, dias, base, _dos, _tres in casos:
        plan = PlanFinanciero.query.filter_by(academia_id=academia_id, codigo=plan_codigo).first() or crear_plan(db, academia_id, plan_codigo)
        frecuencia = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id, codigo=frecuencia_codigo).first() or crear_frecuencia(db, academia_id, frecuencia_codigo, dias)
        crear_tarifa(db, academia_id, tarifario, plan, frecuencia, base)
    db.session.commit()

    for plan_codigo, frecuencia_codigo, _dias, base, dos, tres in casos:
        plan = PlanFinanciero.query.filter_by(academia_id=academia_id, codigo=plan_codigo).one()
        frecuencia = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id, codigo=frecuencia_codigo).one()
        for cantidad, esperado in [(1, base), (2, dos), (3, tres)]:
            resultado = calcular_tarifa(
                academia_id=academia_id,
                tarifario_id=tarifario.id,
                plan_id=plan.id,
                frecuencia_id=frecuencia.id,
                contexto_descuentos={"tipo": "HERMANOS", "cantidad_alumnos": cantidad, "fecha": date(2026, 9, 1)},
            )
            assert resultado.valor_final == Decimal(esperado)


def test_asignar_plan_individual(db, base_data):
    academia_id, _tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    db.session.commit()

    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
        usuario_id=base_data["admin_a"].id,
    )
    db.session.commit()

    assert asignacion.valor_final_snapshot == Decimal("55.00")
    assert asignacion.regla_descuento_id is None


def test_asignar_plan_con_dos_hermanos(db, base_data):
    academia_id, _tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    for alumno in (base_data["alumno_a1"], base_data["alumno_a2"]):
        asignar_alumno_a_familia(academia_id=academia_id, alumno_id=alumno.id, grupo_familiar_id=grupo.id, fecha_inicio=date(2026, 9, 1))
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, decimales=0)
    db.session.commit()

    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
    )

    assert asignacion.grupo_familiar_id == grupo.id
    assert asignacion.descuento_porcentaje_snapshot == Decimal("10.00")
    assert asignacion.descuento_valor_snapshot == Decimal("5.00")
    assert asignacion.valor_final_snapshot == Decimal("50.00")


def test_asignar_plan_con_tres_hermanos_snapshot_correcto(db, base_data):
    academia_id, _tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo = crear_grupo_familiar(academia_id=academia_id, codigo="FAM-000001", nombre="Familia")
    alumno_3 = crear_alumno_extra(db, base_data, "Luis")
    for alumno in (base_data["alumno_a1"], base_data["alumno_a2"], alumno_3):
        asignar_alumno_a_familia(academia_id=academia_id, alumno_id=alumno.id, grupo_familiar_id=grupo.id, fecha_inicio=date(2026, 9, 1))
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, decimales=0)
    regla_3 = crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3, decimales=0)
    db.session.commit()

    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
    )

    assert asignacion.tarifa_base_snapshot == Decimal("55.00")
    assert asignacion.regla_descuento_id == regla_3.id
    assert asignacion.descuento_porcentaje_snapshot == Decimal("15.00")
    assert asignacion.descuento_valor_snapshot == Decimal("8.00")
    assert asignacion.valor_final_snapshot == Decimal("47.00")
    assert asignacion.moneda_snapshot == "USD"


def test_cambio_tarifario_no_altera_snapshot(db, base_data):
    academia_id, tarifario, plan, frecuencia, tarifa = preparar_regular_d2(db, base_data)
    db.session.commit()
    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
    )
    tarifa.valor_base = Decimal("99.00")
    tarifario.moneda = "USD"
    db.session.commit()

    assert db.session.get(AlumnoPlanFinanciero, asignacion.id).valor_final_snapshot == Decimal("55.00")


def test_cambio_de_plan_finaliza_asignacion_anterior(db, base_data):
    academia_id, tarifario, plan_regular, frecuencia, _ = preparar_regular_d2(db, base_data, "60.00")
    plan_desarrollo = crear_plan(db, academia_id, "DESARROLLO")
    crear_tarifa(db, academia_id, tarifario, plan_desarrollo, frecuencia, "75.00")
    db.session.commit()
    primera = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan_regular.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
    )
    segunda = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan_desarrollo.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 11, 1),
    )
    db.session.commit()

    assert primera.estado == "FINALIZADO"
    assert primera.fecha_fin == date(2026, 10, 31)
    assert segunda.estado == "ACTIVO"
    assert segunda.valor_final_snapshot == Decimal("75.00")


def test_tenant_a_no_puede_usar_plan_b(db, base_data):
    academia_a_id, _tarifario, _plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    plan_b = crear_plan(db, base_data["academia_b"].id, "PLAN_B")
    db.session.commit()

    with pytest.raises(FinanzasError, match="Plan no pertenece"):
        asignar_plan_financiero(
            academia_id=academia_a_id,
            alumno_id=base_data["alumno_a1"].id,
            plan_id=plan_b.id,
            frecuencia_id=frecuencia.id,
            fecha_inicio=date(2026, 9, 1),
        )


def test_tenant_a_no_puede_usar_tarifa_b(db, base_data):
    academia_a_id, _tarifario_a, plan_a, frecuencia_a, _ = preparar_regular_d2(db, base_data)
    academia_b_id = base_data["academia_b"].id
    tarifario_b = crear_tarifario(db, academia_b_id)
    plan_b = crear_plan(db, academia_b_id, "REGULAR")
    frecuencia_b = crear_frecuencia(db, academia_b_id, "D2", 2)
    tarifa_b = crear_tarifa(db, academia_b_id, tarifario_b, plan_b, frecuencia_b, "55.00")
    db.session.commit()

    with pytest.raises(FinanzasError, match="Tarifa/configuracion"):
        asignar_plan_financiero(
            academia_id=academia_a_id,
            alumno_id=base_data["alumno_a1"].id,
            plan_id=plan_a.id,
            frecuencia_id=frecuencia_a.id,
            fecha_inicio=date(2026, 9, 1),
            tarifa_plan_id=tarifa_b.id,
        )


def test_tenant_a_no_puede_usar_familia_b(db, base_data):
    academia_a_id, _tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    grupo_b = crear_grupo_familiar(academia_id=base_data["academia_b"].id, codigo="FAM-000001", nombre="Familia B")
    db.session.commit()

    with pytest.raises(FinanzasError, match="Grupo familiar no pertenece"):
        asignar_plan_financiero(
            academia_id=academia_a_id,
            alumno_id=base_data["alumno_a1"].id,
            plan_id=plan.id,
            frecuencia_id=frecuencia.id,
            fecha_inicio=date(2026, 9, 1),
            grupo_familiar_id=grupo_b.id,
        )


def test_tarifario_inexistente_genera_error(db, base_data):
    academia_id = base_data["academia_a"].id
    plan = crear_plan(db, academia_id, "REGULAR")
    frecuencia = crear_frecuencia(db, academia_id, "D2", 2)
    db.session.commit()

    with pytest.raises(FinanzasError, match="No existe tarifario vigente"):
        asignar_plan_financiero(
            academia_id=academia_id,
            alumno_id=base_data["alumno_a1"].id,
            plan_id=plan.id,
            frecuencia_id=frecuencia.id,
            fecha_inicio=date(2026, 9, 1),
        )


def test_dos_tarifarios_vigentes_solapados_generan_error(db, base_data):
    academia_id = base_data["academia_a"].id
    crear_tarifario(db, academia_id, inicio=date(2026, 1, 1), fin=date(2026, 12, 31))
    crear_tarifario(db, academia_id, inicio=date(2026, 9, 1), fin=None)
    db.session.commit()

    with pytest.raises(FinanzasError, match="mas de un tarifario"):
        resolver_tarifario_vigente(academia_id=academia_id, fecha=date(2026, 9, 1))


def test_frecuencia_sin_tarifa_plan_genera_error(db, base_data):
    academia_id, _tarifario, plan, _frecuencia, _ = preparar_regular_d2(db, base_data)
    frecuencia_sin_tarifa = crear_frecuencia(db, academia_id, "D3", 3)
    db.session.commit()

    with pytest.raises(FinanzasError, match="Tarifa/configuracion"):
        asignar_plan_financiero(
            academia_id=academia_id,
            alumno_id=base_data["alumno_a1"].id,
            plan_id=plan.id,
            frecuencia_id=frecuencia_sin_tarifa.id,
            fecha_inicio=date(2026, 9, 1),
        )


def test_alumno_sin_familia_funciona_como_individual(db, base_data):
    academia_id, _tarifario, plan, frecuencia, _ = preparar_regular_d2(db, base_data)
    crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2, decimales=0)
    db.session.commit()

    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 9, 1),
    )

    assert obtener_familia_activa_del_alumno(academia_id=academia_id, alumno_id=base_data["alumno_a1"].id) is None
    assert asignacion.grupo_familiar_id is None
    assert asignacion.valor_final_snapshot == Decimal("55.00")
